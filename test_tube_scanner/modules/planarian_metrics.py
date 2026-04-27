"""
modules/planarian_metrics.py

Intégration des métriques EthoVision XT dans PlanarianScanner.

Architecture :
    PlanarianTracker.process()   → dict brut (cx, cy, speed_px_s, ...)
    EthoVisionMetrics.update()   → enrichit avec métriques EthoVision
    ReductStoreClient.store()    → stocke dans ReductStore avec labels
    ReductStoreClient.export_csv() → exporte vers CSV

Schéma des labels ReductStore :
    experiment  : identifiant de l'expérience (ex: "exp_2026_04_25")
    well        : identifiant du puits (ex: "A1", "B3")
    planarian   : index du planaire dans le puits (ex: "0", "1")
    bucket      : nom du bucket (ex: "planarian_metrics")

Created on 25 avr. 2026
@author: denis
"""

import asyncio
import csv
import io
import json
import logging
import math
import os
import time

from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constantes EthoVision (seuils de mobilité par défaut)
# ---------------------------------------------------------------------------

# Seuils en mm/s — identiques à ceux de la simulation
THRESH_IMMOBILE_DEFAULT = 0.2   # en-dessous : Immobile
THRESH_MOBILE_DEFAULT   = 1.5   # entre les deux : Mobile, au-delà : Highly mobile

# États de mobilité (nomenclature EthoVision XT)
STATE_IMMOBILE    = "Immobile"
STATE_MOBILE      = "Mobile"
STATE_HIGH_MOBILE = "Highly mobile"

# Paramètres comportementaux (défauts — peuvent être importés depuis CSV/Django)
BEHAVIOUR_DEFAULTS = {
    # Thigmotactisme
    "thigmotaxis_wall_dist_mm":  1.0,   # distance à la paroi considérée "near wall"
    # Phototactisme
    "photo_mode":                "none", # none | fixed | sine | radial
    "photo_strength":            0.0,
    # Chimiotactisme
    "chemo_strength":            0.0,
    "chemo_x":                   0.5,   # fraction 0-1
    "chemo_y":                   0.5,
    "chemo_radius_mm":           2.0,
    # Interactions inter-individus
    "avoid_radius_mm":           3.0,
    "aggreg_radius_mm":          6.0,
}


# ---------------------------------------------------------------------------
# Classe EthoVisionMetrics
# ---------------------------------------------------------------------------

class EthoVisionMetrics:
    """
    Calcule et accumule les métriques compatibles EthoVision XT
    à partir des données brutes de PlanarianTracker.

    Gère la conversion pixels → mm via le facteur px_per_mm.
    Une instance par planaire suivi (un puits = une instance).

    Usage :
        metrics = EthoVisionMetrics(px_per_mm=26.25, fps=10)
        for frame, ts in capture:
            annotated, raw = tracker.process(frame, ts)
            record = metrics.update(raw, well_radius_mm=8.0)
            await reduct_client.store(record, labels=...)
        summary = metrics.summary()
    """

    def __init__(
        self,
        px_per_mm: float,
        fps: float,
        thresh_immobile: float = THRESH_IMMOBILE_DEFAULT,
        thresh_mobile:   float = THRESH_MOBILE_DEFAULT,
        behaviour: Optional[dict] = None,
    ):
        """
        Args:
            px_per_mm       : facteur de conversion pixels → mm (calibration optique)
            fps             : fréquence de capture en images/seconde
            thresh_immobile : seuil vitesse Immobile/Mobile en mm/s
            thresh_mobile   : seuil vitesse Mobile/Très mobile en mm/s
            behaviour       : dict de paramètres comportementaux (cf. BEHAVIOUR_DEFAULTS)
        """
        self.px_per_mm       = px_per_mm
        self.fps             = fps
        self.dt              = 1.0 / fps
        self.thresh_immobile = thresh_immobile
        self.thresh_mobile   = thresh_mobile
        self.behaviour       = {**BEHAVIOUR_DEFAULTS, **(behaviour or {})}

        # --- Accumulateurs globaux ---
        self.total_distance_mm  = 0.0
        self.duration_moving_s  = 0.0
        self.duration_stopped_s = 0.0
        self.frame_count        = 0

        # --- Accumulateurs par état de mobilité ---
        self._mob_counts = {
            STATE_IMMOBILE:    0,
            STATE_MOBILE:      0,
            STATE_HIGH_MOBILE: 0,
        }
        self._mob_durations = {
            STATE_IMMOBILE:    0.0,
            STATE_MOBILE:      0.0,
            STATE_HIGH_MOBILE: 0.0,
        }
        self._current_state = None

        # --- Thigmotactisme ---
        self._near_wall_frames = 0

        # --- Historique positions (pour calcul vitesse inter-frame) ---
        self._prev_cx_px = None
        self._prev_cy_px = None
        self._prev_ts    = None

    def _px_to_mm(self, px: float) -> float:
        """Convertit des pixels en millimètres."""
        return px / self.px_per_mm

    def _classify(self, velocity_mm_s: float) -> str:
        """
        Classifie la vitesse selon les seuils EthoVision.

        Args:
            velocity_mm_s : vitesse instantanée en mm/s

        Returns:
            str : STATE_IMMOBILE | STATE_MOBILE | STATE_HIGH_MOBILE
        """
        if velocity_mm_s <= self.thresh_immobile:
            return STATE_IMMOBILE
        elif velocity_mm_s <= self.thresh_mobile:
            return STATE_MOBILE
        return STATE_HIGH_MOBILE

    def update(self, raw: dict, well_radius_mm: float = 8.0) -> dict:
        """
        Calcule les métriques EthoVision pour une frame à partir
        du résultat brut de PlanarianTracker.process().

        Args:
            raw            : dict retourné par PlanarianTracker.process()
                             clés attendues : detected, cx, cy, speed_px_s, ts
            well_radius_mm : rayon du puits en mm (pour le thigmotactisme)

        Returns:
            dict complet avec métriques EthoVision prêtes pour ReductStore
        """
        self.frame_count += 1
        ts = raw.get("timestamp", time.time())

        if not raw.get("detected", False):
            # Planaire non détecté : on accumule l'arrêt et on retourne vide
            self.duration_stopped_s += self.dt
            state = self._current_state or STATE_IMMOBILE
            self._mob_durations[state] += self.dt
            return self._empty_record(ts)

        cx_px = raw["cx"]
        cy_px = raw["cy"]

        # --- Conversion en mm ---
        cx_mm = self._px_to_mm(cx_px)
        cy_mm = self._px_to_mm(cy_px)

        # --- Vitesse en mm/s depuis la vitesse brute pixels/s ---
        speed_px_s    = raw.get("speed_px_s", 0.0)
        velocity_mm_s = self._px_to_mm(speed_px_s)

        # --- Distance parcourue cette frame ---
        dist_mm = velocity_mm_s * self.dt
        self.total_distance_mm += dist_mm

        # --- Mouvement / arrêt ---
        is_moving = velocity_mm_s > self.thresh_immobile
        if is_moving:
            self.duration_moving_s  += self.dt
        else:
            self.duration_stopped_s += self.dt

        # --- État de mobilité ---
        new_state = self._classify(velocity_mm_s)
        if new_state != self._current_state:
            self._mob_counts[new_state] += 1
            self._current_state = new_state
        self._mob_durations[new_state] += self.dt

        # --- Thigmotactisme ---
        # Distance à la paroi du puits (centre = 0, paroi = well_radius_mm)
        well_radius_px  = well_radius_mm * self.px_per_mm
        dist_center_px  = math.sqrt(cx_px**2 + cy_px**2)
        dist_wall_mm    = self._px_to_mm(well_radius_px - dist_center_px)
        near_wall_dist  = self.behaviour.get("thigmotaxis_wall_dist_mm", 1.0)
        is_near_wall    = dist_wall_mm < near_wall_dist
        if is_near_wall:
            self._near_wall_frames += 1

        self._prev_cx_px = cx_px
        self._prev_cy_px = cy_px
        self._prev_ts    = ts

        # --- Record complet ---
        return {
            # Identification temporelle
            "timestamp":                       ts,
            "detected":                        True,
            # Position brute (pixels)
            "cx_px":                           cx_px,
            "cy_px":                           cy_px,
            # Position en mm
            "x_mm":                            round(cx_mm, 4),
            "y_mm":                            round(cy_mm, 4),
            # Vitesse
            "velocity_mm_s":                   round(velocity_mm_s, 4),
            "distance_mm":                     round(dist_mm, 4),
            # Distance totale cumulée (EthoVision : movedCenter-pointTotalmm)
            "total_distance_mm":               round(self.total_distance_mm, 4),
            # Mouvement / arrêt (EthoVision : MovementMoving / Not Moving)
            "moving":                          int(is_moving),
            "duration_moving_s":               round(self.duration_moving_s, 3),
            "duration_stopped_s":              round(self.duration_stopped_s, 3),
            # État de mobilité (EthoVision : Mobility state)
            "mobility_state":                  new_state,
            "mobility_immobile_freq":          self._mob_counts[STATE_IMMOBILE],
            "mobility_immobile_duration_s":    round(self._mob_durations[STATE_IMMOBILE], 3),
            "mobility_mobile_freq":            self._mob_counts[STATE_MOBILE],
            "mobility_mobile_duration_s":      round(self._mob_durations[STATE_MOBILE], 3),
            "mobility_high_mobile_freq":       self._mob_counts[STATE_HIGH_MOBILE],
            "mobility_high_mobile_duration_s": round(self._mob_durations[STATE_HIGH_MOBILE], 3),
            # Thigmotactisme
            "dist_to_wall_mm":                 round(dist_wall_mm, 4),
            "near_wall":                       int(is_near_wall),
            # Données brutes tracker (passthrough)
            "area_px":                         raw.get("area_px", 0),
            "axial_pos":                       raw.get("axial_pos", 0.0),
            "axial_speed":                     raw.get("axial_speed", 0.0),
        }

    def summary(self) -> dict:
        """
        Retourne le résumé global de la session (nomenclature EthoVision XT).
        À appeler en fin d'expérience pour stocker le résumé dans ReductStore.

        Returns:
            dict avec toutes les métriques agrégées
        """
        total_s = self.frame_count * self.dt
        return {
            "total_frames":                        self.frame_count,
            "total_duration_s":                    round(total_s, 3),
            # Distance / vitesse (EthoVision : movedCenter-pointTotalmm / VelocityCenter-pointMeanmm/s)
            "movedCenter_pointTotal_mm":           round(self.total_distance_mm, 4),
            "velocity_mean_mm_s":                  round(
                self.total_distance_mm / total_s if total_s > 0 else 0.0, 4
            ),
            # Mouvement / arrêt
            "movement_moving_duration_s":          round(self.duration_moving_s, 3),
            "movement_not_moving_duration_s":      round(self.duration_stopped_s, 3),
            # Immobile
            "mobility_immobile_frequency":         self._mob_counts[STATE_IMMOBILE],
            "mobility_immobile_duration_s":        round(self._mob_durations[STATE_IMMOBILE], 3),
            # Mobile
            "mobility_mobile_frequency":           self._mob_counts[STATE_MOBILE],
            "mobility_mobile_duration_s":          round(self._mob_durations[STATE_MOBILE], 3),
            # Très mobile
            "mobility_highly_mobile_frequency":    self._mob_counts[STATE_HIGH_MOBILE],
            "mobility_highly_mobile_duration_s":   round(self._mob_durations[STATE_HIGH_MOBILE], 3),
            # Thigmotactisme
            "thigmotaxis_pct_time_near_wall":      round(
                100.0 * self._near_wall_frames / max(self.frame_count, 1), 2
            ),
        }

    def reset(self):
        """
        Réinitialise tous les accumulateurs.
        À appeler lors d'un changement de puits ou de planaire.
        """
        self.__init__(
            self.px_per_mm,
            self.fps,
            self.thresh_immobile,
            self.thresh_mobile,
            self.behaviour,
        )

    @staticmethod
    def _empty_record(ts: float) -> dict:
        """Retourne un enregistrement vide (planaire non détecté)."""
        return {
            "timestamp":  ts,
            "detected":   False,
        }


# ---------------------------------------------------------------------------
# Paramètres expérimentaux (importables depuis CSV ou Django)
# ---------------------------------------------------------------------------

class ExperimentParams:
    """
    Conteneur des paramètres d'une expérience.
    Peut être instancié depuis un dict, un fichier CSV ou un modèle Django.

    Champs obligatoires : experiment, well, px_per_mm, fps
    Tous les autres ont des valeurs par défaut.
    """

    REQUIRED = {"experiment", "well", "px_per_mm", "fps"}

    DEFAULTS = {
        "well_radius_mm":   8.0,
        "thresh_immobile":  THRESH_IMMOBILE_DEFAULT,
        "thresh_mobile":    THRESH_MOBILE_DEFAULT,
        "planarian_count":  1,
        "tube_axis":        "vertical",
        "min_area_px":      20,
        **BEHAVIOUR_DEFAULTS,
    }

    def __init__(self, data: dict):
        """
        Args:
            data : dict contenant au moins les champs REQUIRED
        """
        missing = self.REQUIRED - set(data.keys())
        if missing:
            raise ValueError(f"Paramètres manquants : {missing}")

        merged = {**self.DEFAULTS, **data}
        for k, v in merged.items():
            # Conversion de type automatique si valeur string (vient du CSV)
            setattr(self, k, self._cast(k, v))

    @staticmethod
    def _cast(key: str, value):
        """
        Convertit la valeur en type approprié.
        Les valeurs CSV sont toutes des strings — on les cast automatiquement.

        Args:
            key   : nom du paramètre
            value : valeur brute (str ou type natif)

        Returns:
            valeur convertie
        """
        float_keys = {
            "px_per_mm", "fps", "well_radius_mm", "thresh_immobile", "thresh_mobile",
            "photo_strength", "chemo_strength", "chemo_x", "chemo_y", "chemo_radius_mm",
            "thigmotaxis_wall_dist_mm", "avoid_radius_mm", "aggreg_radius_mm",
        }
        int_keys = {"planarian_count", "min_area_px"}
        if key in float_keys:
            return float(value)
        if key in int_keys:
            return int(value)
        # Booléens CSV ("true"/"false")
        if isinstance(value, str) and value.lower() in ("true", "false"):
            return value.lower() == "true"
        return value

    @classmethod
    def from_csv_row(cls, row: dict) -> "ExperimentParams":
        """
        Instancie depuis une ligne de DictReader CSV.

        Args:
            row : dict issu de csv.DictReader

        Returns:
            ExperimentParams
        """
        return cls(row)

    @classmethod
    def from_csv_file(cls, filepath: str) -> list:
        """
        Charge tous les paramètres d'un fichier CSV (une expérience par ligne).

        Args:
            filepath : chemin vers le fichier CSV

        Returns:
            liste d'ExperimentParams
        """
        results = []
        with open(filepath, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    results.append(cls.from_csv_row(row))
                except ValueError as e:
                    logger.warning(f"Ligne ignorée : {e} — {row}")
        return results

    def to_dict(self) -> dict:
        """Sérialise les paramètres en dict (pour stockage ou affichage Django)."""
        return {k: getattr(self, k) for k in {**self.DEFAULTS, **{r: None for r in self.REQUIRED}}}

    def build_metrics(self) -> "EthoVisionMetrics":
        """
        Construit l'instance EthoVisionMetrics correspondant à ces paramètres.

        Returns:
            EthoVisionMetrics configurée
        """
        behaviour = {k: getattr(self, k) for k in BEHAVIOUR_DEFAULTS if hasattr(self, k)}
        return EthoVisionMetrics(
            px_per_mm       = self.px_per_mm,
            fps             = self.fps,
            thresh_immobile = self.thresh_immobile,
            thresh_mobile   = self.thresh_mobile,
            behaviour       = behaviour,
        )


# ---------------------------------------------------------------------------
# Client ReductStore
# ---------------------------------------------------------------------------

class ReductStoreClient:
    """
    Interface asynchrone avec ReductStore pour PlanarianScanner.

    Schéma des labels :
        experiment  → identifiant de l'expérience
        well        → identifiant du puits (A1, B3, ...)
        planarian   → index du planaire dans le puits
        record_type → "frame" | "summary"

    Chaque entrée stockée contient un payload JSON avec toutes les métriques.
    Le timestamp ReductStore est l'epoch µs de la frame.
    """

    def __init__(
        self,
        url:    str = "http://localhost:8383",
        token:  str = "",
        bucket: str = "planarian_metrics",
    ):
        """
        Args:
            url    : URL du serveur ReductStore
            token  : token d'authentification (vide si pas d'auth)
            bucket : nom du bucket cible
        """
        self.url        = url
        self.token      = token
        self.bucket_name = bucket
        self._client    = None
        self._bucket    = None

    async def connect(self):
        """
        Initialise la connexion et crée le bucket s'il n'existe pas.
        À appeler une fois au démarrage.
        """
        from reduct import Client, BucketSettings, QuotaType

        self._client = Client(self.url, api_token=self.token)
        self._bucket = await self._client.create_bucket(
            self.bucket_name,
            BucketSettings(quota_type=QuotaType.NONE),
            exist_ok=True,
        )
        logger.info(f"ReductStore connecté : {self.url} / bucket={self.bucket_name}")

    async def store_metric(
        self,
        record:      dict,
        experiment:  str,
        well:        str,
        planarian:   int  = 0,
        record_type: str  = "frame",
        ts_us:       Optional[int] = None,
    ):
        """
        Stocke un enregistrement de métriques dans ReductStore.

        Args:
            record      : dict de métriques (issu de EthoVisionMetrics.update())
            experiment  : identifiant de l'expérience
            well        : identifiant du puits
            planarian   : index du planaire (défaut 0)
            record_type : "frame" ou "summary"
            ts_us       : timestamp en microsecondes (défaut : maintenant)
        """
        if self._bucket is None:
            await self.connect()

        ts_us = ts_us or int(time.time() * 1_000_000)

        labels = {
            "experiment":  experiment,
            "well":        well,
            "planarian":   str(planarian),
            "record_type": record_type,
        }

        payload = json.dumps(record).encode("utf-8")

        await self._bucket.write(
            entry_name  = "metrics",
            data        = payload,
            timestamp   = ts_us,
            labels      = labels,
            content_type= "application/json",
        )

    async def store_summary(
        self,
        summary:    dict,
        experiment: str,
        well:       str,
        planarian:  int = 0,
    ):
        """
        Stocke le résumé de fin de session dans ReductStore.

        Args:
            summary    : dict issu de EthoVisionMetrics.summary()
            experiment : identifiant de l'expérience
            well       : identifiant du puits
            planarian  : index du planaire
        """
        await self.store_metric(
            record      = summary,
            experiment  = experiment,
            well        = well,
            planarian   = planarian,
            record_type = "summary",
        )

    async def get_tracking_data(
        self,
        experiment:  str,
        well:        str,
        planarian:   int         = 0,
        record_type: str         = "frame",
        start:       Optional[datetime] = None,
        stop:        Optional[datetime] = None,
    ) -> list:
        """
        Récupère les enregistrements depuis ReductStore avec filtrage par labels.

        Args:
            experiment  : identifiant de l'expérience
            well        : identifiant du puits
            planarian   : index du planaire
            record_type : "frame" | "summary"
            start, stop : plage temporelle (datetime UTC, optionnel)

        Returns:
            liste de dicts métriques
        """
        if self._bucket is None:
            await self.connect()

        labels = {
            "experiment":  experiment,
            "well":        well,
            "planarian":   str(planarian),
            "record_type": record_type,
        }

        kwargs = {"include": labels}
        if start:
            kwargs["start"] = int(start.timestamp() * 1_000_000)
        if stop:
            kwargs["stop"]  = int(stop.timestamp() * 1_000_000)

        records = []
        async for record in self._bucket.query("metrics", **kwargs):
            try:
                data = json.loads(await record.read_all())
                records.append(data)
            except Exception as e:
                logger.warning(f"Entrée illisible ignorée : {e}")

        return records

    async def export_csv(
        self,
        filepath:    str,
        experiment:  str,
        well:        str,
        planarian:   int         = 0,
        record_type: str         = "frame",
        start:       Optional[datetime] = None,
        stop:        Optional[datetime] = None,
    ) -> int:
        """
        Exporte les données depuis ReductStore vers un fichier CSV.

        Args:
            filepath    : chemin du fichier CSV de sortie
            experiment  : identifiant de l'expérience
            well        : identifiant du puits
            planarian   : index du planaire
            record_type : "frame" | "summary"
            start, stop : plage temporelle (datetime UTC, optionnel)

        Returns:
            nombre de lignes exportées
        """
        records = await self.get_tracking_data(
            experiment  = experiment,
            well        = well,
            planarian   = planarian,
            record_type = record_type,
            start       = start,
            stop        = stop,
        )

        if not records:
            logger.warning(f"Aucune donnée pour {experiment}/{well}/{planarian}")
            return 0

        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)

        # Collecte de toutes les clés présentes (union de tous les records)
        fieldnames = list(dict.fromkeys(k for r in records for k in r.keys()))

        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for r in records:
                writer.writerow(r)

        logger.info(f"Export CSV : {len(records)} lignes → {filepath}")
        return len(records)

    async def export_csv_response(
        self,
        experiment:  str,
        well:        str,
        planarian:   int         = 0,
        record_type: str         = "frame",
        start:       Optional[datetime] = None,
        stop:        Optional[datetime] = None,
    ) -> tuple[str, int]:
        """
        Génère le contenu CSV en mémoire (pour une réponse HTTP Django).

        Args:
            experiment, well, planarian, record_type, start, stop : cf. export_csv

        Returns:
            tuple (contenu_csv_str, nb_lignes)
        """
        records = await self.get_tracking_data(
            experiment  = experiment,
            well        = well,
            planarian   = planarian,
            record_type = record_type,
            start       = start,
            stop        = stop,
        )

        if not records:
            return "", 0

        fieldnames = list(dict.fromkeys(k for r in records for k in r.keys()))
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for r in records:
            writer.writerow(r)

        return output.getvalue(), len(records)

    async def close(self):
        """Ferme la connexion ReductStore."""
        if self._client:
            await self._client.close()
            logger.info("ReductStore déconnecté")
