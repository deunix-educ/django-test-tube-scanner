"""
modules/planarian_metrics.py

Intégration des métriques EthoVision XT + comportementales dans PlanarianScanner.

Métriques par frame :
    Mobilité    : velocity, distance, moving, mobility_state
    Thigmo      : dist_to_wall_mm, near_wall
    Photo       : dist_to_light_mm, heading_to_light_deg, fleeing_light
    Chemo       : dist_to_food_mm, heading_to_food_deg, approaching_food, in_food_zone
    Social      : nearest_neighbour_mm, in_avoid_zone, in_aggreg_zone, chem_repulsion_level

Métriques résumé (summary) :
    Mobilité    : movedCenter_pointTotal_mm, velocity_mean_mm_s, durations par état
    Thigmo      : thigmotaxis_pct_time_near_wall
    Photo       : photo_pct_time_fleeing, photo_mean_dist_mm, photo_latency_s
    Chemo       : chemo_pct_time_approaching, chemo_pct_time_in_zone,
                  chemo_latency_s, chemo_mean_dist_mm
    Social      : social_pct_time_avoiding, social_pct_time_aggregating,
                  social_mean_nn_mm, social_contact_events
                  
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
#import asyncio
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

THRESH_IMMOBILE_DEFAULT = 0.2   # en-dessous : Immobile (mm/s)
THRESH_MOBILE_DEFAULT   = 1.5   # entre les deux : Mobile, au-delà : Highly mobile

STATE_IMMOBILE    = "Immobile"
STATE_MOBILE      = "Mobile"
STATE_HIGH_MOBILE = "Highly mobile"

# Paramètres comportementaux (défauts)
BEHAVIOUR_DEFAULTS = {
    # Thigmotactisme
    "thigmotaxis_wall_dist_mm":  1.0,
    # Phototactisme
    "photo_mode":                "none",
    "photo_strength":            0.0,
    "photo_x":                   0.5,
    "photo_y":                   0.5,
    "photo_flee_angle_deg":      90.0,   # angle max tête/source pour considérer "fuite"
    # Chimiotactisme
    "chemo_strength":            0.0,
    "chemo_x":                   0.5,
    "chemo_y":                   0.5,
    "chemo_radius_mm":           2.0,
    "chemo_approach_angle_deg":  90.0,   # angle max tête/nourriture pour considérer "approche"
    # Interactions inter-individus
    "avoid_radius_mm":           3.0,
    "aggreg_radius_mm":          6.0,
}


# ---------------------------------------------------------------------------
# Helpers géométriques
# ---------------------------------------------------------------------------

def _angle_between_deg(vx1: float, vy1: float, vx2: float, vy2: float) -> float:
    """
    Calcule l'angle en degrés entre deux vecteurs 2D.
    Retourne 0.0 si l'un des vecteurs est nul.

    Args:
        vx1, vy1 : premier vecteur
        vx2, vy2 : second vecteur

    Returns:
        angle en degrés [0, 180]
    """
    n1 = math.sqrt(vx1**2 + vy1**2)
    n2 = math.sqrt(vx2**2 + vy2**2)
    if n1 < 1e-9 or n2 < 1e-9:
        return 0.0
    cos_a = max(-1.0, min(1.0, (vx1 * vx2 + vy1 * vy2) / (n1 * n2)))
    return math.degrees(math.acos(cos_a))


def _heading_to_target_deg(
    cx: float, cy: float,
    tx: float, ty: float,
    dx: float, dy: float,
) -> float:
    """
    Calcule l'angle entre la direction de déplacement et le vecteur vers une cible.

    Args:
        cx, cy : position courante
        tx, ty : position cible
        dx, dy : vecteur de déplacement (cx - prev_cx, cy - prev_cy)

    Returns:
        angle en degrés [0, 180] — 0 = va droit vers la cible, 180 = fuit
    """
    to_target_x = tx - cx
    to_target_y = ty - cy
    return _angle_between_deg(dx, dy, to_target_x, to_target_y)


# ---------------------------------------------------------------------------
# Classe EthoVisionMetrics
# ---------------------------------------------------------------------------

class EthoVisionMetrics:
    """
    Calcule et accumule toutes les métriques comportementales compatibles
    EthoVision XT à partir des données brutes de PlanarianTracker.

    Métriques calculées :
        - Mobilité EthoVision (distance, vitesse, états Immobile/Mobile/Très mobile)
        - Thigmotactisme (distance paroi, % temps près du bord)
        - Phototactisme (distance source, orientation, % fuite, latence)
        - Chimiotactisme (distance nourriture, % approche, % zone, latence)
        - Interactions inter-individus (voisin le plus proche, évitement,
          agrégation, répulsion chimique, événements de contact)

    Une instance par planaire suivi.

    Usage :
        metrics = EthoVisionMetrics(px_per_mm=26.25, fps=10, behaviour={...})
        for frame in capture:
            raw = tracker.process(frame, ts)
            record = metrics.update(
                raw,
                well_radius_mm   = 8.0,
                arena_center_px  = (250, 250),
                photo_source_px  = (100, 100),
                others_pos_mm    = [(x1,y1), (x2,y2)],
                chem_level       = 0.3,
            )
            await client.store_metric(record, ...)
        summary = metrics.summary()
    """

    def __init__(
        self,
        px_per_mm:       float,
        fps:             float,
        thresh_immobile: float = THRESH_IMMOBILE_DEFAULT,
        thresh_mobile:   float = THRESH_MOBILE_DEFAULT,
        behaviour:       Optional[dict] = None,
    ):
        """
        Args:
            px_per_mm       : facteur de conversion pixels → mm
            fps             : fréquence de capture (images/s)
            thresh_immobile : seuil vitesse Immobile/Mobile (mm/s)
            thresh_mobile   : seuil vitesse Mobile/Très mobile (mm/s)
            behaviour       : dict de paramètres comportementaux (cf. BEHAVIOUR_DEFAULTS)
        """
        self.px_per_mm       = px_per_mm
        self.fps             = fps
        self.dt              = 1.0 / fps
        self.thresh_immobile = thresh_immobile
        self.thresh_mobile   = thresh_mobile
        self.beh             = {**BEHAVIOUR_DEFAULTS, **(behaviour or {})}

        # --- Accumulateurs mobilité ---
        self.total_distance_mm  = 0.0
        self.duration_moving_s  = 0.0
        self.duration_stopped_s = 0.0
        self.frame_count        = 0

        self._mob_counts = {STATE_IMMOBILE: 0, STATE_MOBILE: 0, STATE_HIGH_MOBILE: 0}
        self._mob_durations = {STATE_IMMOBILE: 0.0, STATE_MOBILE: 0.0, STATE_HIGH_MOBILE: 0.0}
        self._current_state = None

        # --- Accumulateurs thigmotactisme ---
        self._near_wall_frames = 0

        # --- Accumulateurs phototactisme ---
        self._flee_frames      = 0          # frames en fuite
        self._photo_dist_sum   = 0.0        # somme distances source
        self._photo_dist_count = 0
        self._photo_latency_s  = None       # temps avant 1ère fuite (s)

        # --- Accumulateurs chimiotactisme ---
        self._approach_frames  = 0          # frames en approche nourriture
        self._in_zone_frames   = 0          # frames dans la zone nourriture
        self._chemo_dist_sum   = 0.0
        self._chemo_dist_count = 0
        self._chemo_latency_s  = None       # temps avant 1ère entrée zone (s)

        # --- Accumulateurs interactions inter-individus ---
        self._avoid_frames     = 0          # frames en zone d'évitement
        self._aggreg_frames    = 0          # frames en zone d'agrégation
        self._nn_sum           = 0.0        # somme distances voisin le plus proche
        self._nn_count         = 0
        self._contact_events   = 0          # transitions False→True de in_avoid_zone
        self._prev_in_avoid    = False

        # --- Position précédente (vecteur de déplacement) ---
        self._prev_cx_mm = None
        self._prev_cy_mm = None
        self._prev_ts    = None

    # ------------------------------------------------------------------ #
    # Helpers internes
    # ------------------------------------------------------------------ #

    def _px_to_mm(self, px: float) -> float:
        """Convertit des pixels en millimètres."""
        return px / self.px_per_mm

    def _classify(self, v: float) -> str:
        """Classifie la vitesse en état de mobilité EthoVision."""
        if v <= self.thresh_immobile:
            return STATE_IMMOBILE
        elif v <= self.thresh_mobile:
            return STATE_MOBILE
        return STATE_HIGH_MOBILE

    def _elapsed_s(self) -> float:
        """Temps écoulé depuis le début de la session (s)."""
        return self.frame_count * self.dt

    # ------------------------------------------------------------------ #
    # Méthode principale
    # ------------------------------------------------------------------ #

    def update(
        self,
        raw:              dict,
        well_radius_mm:   float                    = 8.0,
        arena_center_px:  tuple                    = (250, 250),
        photo_source_px:  Optional[tuple]          = None,
        others_pos_mm:    Optional[list]           = None,
        chem_level:       float                    = 0.0,
    ) -> dict:
        """
        Calcule toutes les métriques comportementales pour une frame.

        Args:
            raw             : dict brut de PlanarianTracker.process()
                              clés : detected, cx, cy, speed_px_s, ts
            well_radius_mm  : rayon du puits en mm
            arena_center_px : centre de l'arène en pixels (cx, cy)
            photo_source_px : position de la source lumineuse en pixels (ou None)
            others_pos_mm   : liste de (x_mm, y_mm) des autres planaires
            chem_level      : concentration chimique locale [0-1] (depuis ChemicalMap)

        Returns:
            dict complet prêt pour ReductStore
        """
        self.frame_count += 1
        ts = raw.get("timestamp", time.time())

        if not raw.get("detected", False):
            self.duration_stopped_s += self.dt
            state = self._current_state or STATE_IMMOBILE
            self._mob_durations[state] += self.dt
            return {"timestamp": ts, "detected": False}

        # --- Position en mm (relative au centre de l'arène) ---
        cx_px = raw["cx"] - arena_center_px[0]
        cy_px = raw["cy"] - arena_center_px[1]
        cx_mm = self._px_to_mm(cx_px)
        cy_mm = self._px_to_mm(cy_px)

        # --- Vitesse / distance ---
        speed_px_s    = raw.get("speed_px_s", 0.0)
        velocity_mm_s = self._px_to_mm(speed_px_s)
        dist_mm       = velocity_mm_s * self.dt
        self.total_distance_mm += dist_mm

        # Vecteur de déplacement (pour calculs d'angle)
        if self._prev_cx_mm is not None:
            move_dx = cx_mm - self._prev_cx_mm
            move_dy = cy_mm - self._prev_cy_mm
        else:
            move_dx, move_dy = 0.0, 0.0

        # --- Mobilité ---
        is_moving = velocity_mm_s > self.thresh_immobile
        if is_moving:
            self.duration_moving_s  += self.dt
        else:
            self.duration_stopped_s += self.dt

        new_state = self._classify(velocity_mm_s)
        if new_state != self._current_state:
            self._mob_counts[new_state] += 1
            self._current_state = new_state
        self._mob_durations[new_state] += self.dt

        # ================================================================
        # THIGMOTACTISME
        # ================================================================
        well_radius_px = well_radius_mm * self.px_per_mm
        dist_center_px = math.sqrt(cx_px**2 + cy_px**2)
        dist_wall_mm   = self._px_to_mm(well_radius_px - dist_center_px)
        near_wall_thr  = self.beh.get("thigmotaxis_wall_dist_mm", 1.0)
        is_near_wall   = dist_wall_mm < near_wall_thr
        if is_near_wall:
            self._near_wall_frames += 1

        # ================================================================
        # PHOTOTACTISME
        # ================================================================
        photo_mode = self.beh.get("photo_mode", "none")
        dist_light_mm      = 0.0
        heading_light_deg  = 0.0
        fleeing_light      = False

        if photo_mode != "none" and photo_source_px is not None:
            lx_px = photo_source_px[0] - arena_center_px[0]
            ly_px = photo_source_px[1] - arena_center_px[1]
            lx_mm = self._px_to_mm(lx_px)
            ly_mm = self._px_to_mm(ly_px)

            dl = math.sqrt((cx_mm - lx_mm)**2 + (cy_mm - ly_mm)**2)
            dist_light_mm = dl

            self._photo_dist_sum   += dl
            self._photo_dist_count += 1

            # Angle entre déplacement et direction vers la source
            heading_light_deg = _heading_to_target_deg(
                cx_mm, cy_mm, lx_mm, ly_mm, move_dx, move_dy
            )
            # Fuite = planaire s'éloigne de la source (angle > seuil)
            flee_thr  = self.beh.get("photo_flee_angle_deg", 90.0)
            fleeing_light = (heading_light_deg > flee_thr) and is_moving

            if fleeing_light:
                self._flee_frames += 1
                if self._photo_latency_s is None:
                    self._photo_latency_s = self._elapsed_s()

        # ================================================================
        # CHIMIOTACTISME
        # ================================================================
        chemo_x_frac  = self.beh.get("chemo_x", 0.5)
        chemo_y_frac  = self.beh.get("chemo_y", 0.5)
        chemo_r_mm    = self.beh.get("chemo_radius_mm", 2.0)
        chemo_strength= self.beh.get("chemo_strength", 0.0)

        dist_food_mm      = 0.0
        heading_food_deg  = 0.0
        approaching_food  = False
        in_food_zone      = False

        if chemo_strength > 0.0:
            # Position nourriture en mm relative au centre
            fx_mm = (chemo_x_frac - 0.5) * 2.0 * well_radius_mm
            fy_mm = (chemo_y_frac - 0.5) * 2.0 * well_radius_mm

            df = math.sqrt((cx_mm - fx_mm)**2 + (cy_mm - fy_mm)**2)
            dist_food_mm = df

            self._chemo_dist_sum   += df
            self._chemo_dist_count += 1

            in_food_zone = df <= chemo_r_mm
            if in_food_zone:
                self._in_zone_frames += 1
                if self._chemo_latency_s is None:
                    self._chemo_latency_s = self._elapsed_s()

            heading_food_deg = _heading_to_target_deg(
                cx_mm, cy_mm, fx_mm, fy_mm, move_dx, move_dy
            )
            approach_thr = self.beh.get("chemo_approach_angle_deg", 90.0)
            approaching_food = (heading_food_deg < approach_thr) and is_moving

            if approaching_food:
                self._approach_frames += 1

        # ================================================================
        # INTERACTIONS INTER-INDIVIDUS
        # ================================================================
        avoid_r_mm  = self.beh.get("avoid_radius_mm", 3.0)
        aggreg_r_mm = self.beh.get("aggreg_radius_mm", 6.0)

        nearest_nn_mm    = float("inf")
        in_avoid_zone    = False
        in_aggreg_zone   = False

        if others_pos_mm:
            for ox_mm, oy_mm in others_pos_mm:
                d = math.sqrt((cx_mm - ox_mm)**2 + (cy_mm - oy_mm)**2)
                if d < nearest_nn_mm:
                    nearest_nn_mm = d

            if nearest_nn_mm < avoid_r_mm:
                in_avoid_zone = True
                self._avoid_frames += 1
            elif nearest_nn_mm < aggreg_r_mm:
                in_aggreg_zone = True
                self._aggreg_frames += 1

            self._nn_sum   += nearest_nn_mm
            self._nn_count += 1

            # Événement de contact : transition vers zone d'évitement
            if in_avoid_zone and not self._prev_in_avoid:
                self._contact_events += 1
        else:
            nearest_nn_mm = 0.0

        self._prev_in_avoid = in_avoid_zone

        # --- Mise à jour position précédente ---
        self._prev_cx_mm = cx_mm
        self._prev_cy_mm = cy_mm
        self._prev_ts    = ts

        # ================================================================
        # RECORD COMPLET
        # ================================================================
        return {
            # Identification
            "timestamp":                       ts,
            "detected":                        True,
            # Position (mm, relative au centre)
            "x_mm":                            round(cx_mm, 4),
            "y_mm":                            round(cy_mm, 4),
            # Position brute pixels
            "cx_px":                           raw["cx"],
            "cy_px":                           raw["cy"],
            # Mobilité EthoVision
            "velocity_mm_s":                   round(velocity_mm_s, 4),
            "distance_mm":                     round(dist_mm, 4),
            "total_distance_mm":               round(self.total_distance_mm, 4),
            "moving":                          int(is_moving),
            "duration_moving_s":               round(self.duration_moving_s, 3),
            "duration_stopped_s":              round(self.duration_stopped_s, 3),
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
            # Phototactisme
            "dist_to_light_mm":                round(dist_light_mm, 4),
            "heading_to_light_deg":            round(heading_light_deg, 2),
            "fleeing_light":                   int(fleeing_light),
            # Chimiotactisme
            "dist_to_food_mm":                 round(dist_food_mm, 4),
            "heading_to_food_deg":             round(heading_food_deg, 2),
            "approaching_food":                int(approaching_food),
            "in_food_zone":                    int(in_food_zone),
            # Interactions inter-individus
            "nearest_neighbour_mm":            round(nearest_nn_mm, 4) if nearest_nn_mm != float("inf") else 0.0,
            "in_avoid_zone":                   int(in_avoid_zone),
            "in_aggreg_zone":                  int(in_aggreg_zone),
            "chem_repulsion_level":            round(chem_level, 4),
            # Passthrough tracker
            "area_px":                         raw.get("area_px", 0),
            "axial_pos":                       raw.get("axial_pos", 0.0),
            "axial_speed":                     raw.get("axial_speed", 0.0),
        }

    # ------------------------------------------------------------------ #
    # Résumé de session
    # ------------------------------------------------------------------ #

    def summary(self) -> dict:
        """
        Retourne le résumé global de la session.
        Nomenclature EthoVision XT + métriques comportementales.
        À appeler en fin d'expérience.

        Returns:
            dict avec toutes les métriques agrégées
        """
        total_s = self.frame_count * self.dt
        det     = max(self._photo_dist_count, 1)   # frames avec détection

        return {
            # Identification session
            "total_frames":                        self.frame_count,
            "total_duration_s":                    round(total_s, 3),
            # --- Mobilité EthoVision ---
            "movedCenter_pointTotal_mm":           round(self.total_distance_mm, 4),
            "velocity_mean_mm_s":                  round(
                self.total_distance_mm / total_s if total_s > 0 else 0.0, 4),
            "movement_moving_duration_s":          round(self.duration_moving_s, 3),
            "movement_not_moving_duration_s":      round(self.duration_stopped_s, 3),
            "mobility_immobile_frequency":         self._mob_counts[STATE_IMMOBILE],
            "mobility_immobile_duration_s":        round(self._mob_durations[STATE_IMMOBILE], 3),
            "mobility_mobile_frequency":           self._mob_counts[STATE_MOBILE],
            "mobility_mobile_duration_s":          round(self._mob_durations[STATE_MOBILE], 3),
            "mobility_highly_mobile_frequency":    self._mob_counts[STATE_HIGH_MOBILE],
            "mobility_highly_mobile_duration_s":   round(self._mob_durations[STATE_HIGH_MOBILE], 3),
            # --- Thigmotactisme ---
            "thigmotaxis_pct_time_near_wall":      round(
                100.0 * self._near_wall_frames / max(self.frame_count, 1), 2),
            # --- Phototactisme ---
            "photo_pct_time_fleeing":              round(
                100.0 * self._flee_frames / max(self.frame_count, 1), 2),
            "photo_mean_dist_mm":                  round(
                self._photo_dist_sum / max(self._photo_dist_count, 1), 4),
            "photo_latency_s":                     round(self._photo_latency_s, 3)
                                                   if self._photo_latency_s is not None else None,
            # --- Chimiotactisme ---
            "chemo_pct_time_approaching":          round(
                100.0 * self._approach_frames / max(self.frame_count, 1), 2),
            "chemo_pct_time_in_zone":              round(
                100.0 * self._in_zone_frames / max(self.frame_count, 1), 2),
            "chemo_latency_s":                     round(self._chemo_latency_s, 3)
                                                   if self._chemo_latency_s is not None else None,
            "chemo_mean_dist_mm":                  round(
                self._chemo_dist_sum / max(self._chemo_dist_count, 1), 4),
            # --- Interactions inter-individus ---
            "social_pct_time_avoiding":            round(
                100.0 * self._avoid_frames / max(self.frame_count, 1), 2),
            "social_pct_time_aggregating":         round(
                100.0 * self._aggreg_frames / max(self.frame_count, 1), 2),
            "social_mean_nn_mm":                   round(
                self._nn_sum / max(self._nn_count, 1), 4),
            "social_contact_events":               self._contact_events,
        }

    def reset(self):
        """Réinitialise tous les accumulateurs (changement de puits ou planaire)."""
        self.__init__(
            self.px_per_mm, self.fps,
            self.thresh_immobile, self.thresh_mobile, self.beh,
        )

    @staticmethod
    def _empty_record(ts: float) -> dict:
        """Enregistrement vide (planaire non détecté)."""
        return {"timestamp": ts, "detected": False}


# ---------------------------------------------------------------------------
# Paramètres expérimentaux
# ---------------------------------------------------------------------------

class ExperimentParams:
    """
    Conteneur des paramètres d'une expérience.
    Instanciable depuis un dict, un fichier CSV ou un modèle Django.
    """

    REQUIRED = {"experiment", "well", "px_per_mm", "fps"}

    DEFAULTS = {
        "well_radius_mm":         8.0,
        "thresh_immobile":        THRESH_IMMOBILE_DEFAULT,
        "thresh_mobile":          THRESH_MOBILE_DEFAULT,
        "planarian_count":        1,
        "tube_axis":              "vertical",
        "min_area_px":            20,
        "max_area_ratio":         0.10,
        **BEHAVIOUR_DEFAULTS,
    }

    def __init__(self, data: dict):
        missing = self.REQUIRED - set(data.keys())
        if missing:
            raise ValueError(f"Paramètres manquants : {missing}")
        merged = {**self.DEFAULTS, **data}
        for k, v in merged.items():
            setattr(self, k, self._cast(k, v))

    @staticmethod
    def _cast(key: str, value):
        """Cast automatique des valeurs CSV (toutes en string) vers le bon type."""
        float_keys = {
            "px_per_mm", "fps", "well_radius_mm", "thresh_immobile", "thresh_mobile",
            "photo_strength", "photo_x", "photo_y", "photo_flee_angle_deg",
            "chemo_strength", "chemo_x", "chemo_y", "chemo_radius_mm",
            "chemo_approach_angle_deg", "thigmotaxis_wall_dist_mm",
            "avoid_radius_mm", "aggreg_radius_mm", "max_area_ratio",
        }
        int_keys = {"planarian_count", "min_area_px"}
        if key in float_keys:
            return float(value)
        if key in int_keys:
            return int(value)
        if isinstance(value, str) and value.lower() in ("true", "false"):
            return value.lower() == "true"
        return value

    @classmethod
    def from_csv_row(cls, row: dict) -> "ExperimentParams":
        """Instancie depuis une ligne de csv.DictReader."""
        return cls(row)

    @classmethod
    def from_csv_file(cls, filepath: str) -> list:
        """Charge toutes les expériences d'un fichier CSV."""
        results = []
        with open(filepath, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                try:
                    results.append(cls.from_csv_row(row))
                except ValueError as e:
                    logger.warning(f"Ligne ignorée : {e} — {row}")
        return results

    def to_dict(self) -> dict:
        """Sérialise en dict."""
        return {k: getattr(self, k)
                for k in {**self.DEFAULTS, **{r: None for r in self.REQUIRED}}}

    def build_metrics(self) -> EthoVisionMetrics:
        """Construit l'instance EthoVisionMetrics pour ces paramètres."""
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

    Labels : experiment | well | planarian | record_type (frame|summary)
    """

    def __init__(
        self,
        url:    str = "http://localhost:8383",
        token:  str = "",
        bucket: str = "planarian_metrics",
        quota_type=None, 
        quota_size=1000_000_000
    ):
        self.url          = url
        self.token        = token
        self.bucket_name  = bucket
        self.quota_type = quota_type
        self.quota_size = quota_size
        self.entry_name   = "metrics"
        self._client = None
        self._bucket = None
        

    async def _create_bucket(self):
        from reduct import Client, BucketSettings
        self._client = Client(self.url, api_token=self.token)
        settings = BucketSettings(
            quota_type=self.quota_type,
            quota_size=self.quota_size,
            exist_ok=True,
        )
        return await self._client.create_bucket(self.bucket_name, settings, exist_ok=True)


    async def connect(self):
        """Initialise la connexion et crée le bucket si nécessaire."""
        self._bucket = await self._create_bucket()
        logger.info(f"ReductStore connecté : {self.url} / {self.bucket_name}")
        
    async def store_metric(
        self,
        record:      dict,
        experiment:  str,
        well:        str,
        planarian:   int = 0,
        record_type: str = "frame",
        uuid:        str = "",
        ts_us:       Optional[int] = None,
    ):
        """
        Stocke un enregistrement dans ReductStore.

        Le timestamp est rendu unique par planaire en ajoutant l'index
        du planaire comme offset sub-microseconde — évite le 409 Conflict
        quand plusieurs planaires du même puits écrivent dans la même frame.
        """
        if self._bucket is None:
            await self.connect()
        # ts_us de base + offset planaire (0, 1, 2…) pour unicité garantie
        base_ts = ts_us or int(time.time() * 1_000_000)
        unique_ts = base_ts + planarian
        
        await self._bucket.write(
            entry_name   = "metrics",
            data         = json.dumps(record).encode("utf-8"),
            timestamp    = unique_ts,
            labels       = {
                "experiment":  experiment,
                "well":        well,
                "planarian":   str(planarian),
                "record_type": record_type,
                "uuid": uuid,
            },
            content_type = "application/json",
        )

    async def store_summary(self, summary: dict, experiment: str,
                            well: str, planarian: int = 0):
        """Stocke le résumé de fin de session."""
        await self.store_metric(summary, experiment, well, planarian, "summary")

    async def get_tracking_data(
        self,
        experiment:  str,
        well:        str,
        planarian:   int = 0,
        record_type: str = "metrics",
        start:       Optional[datetime] = None,
        stop:        Optional[datetime] = None,
    ) -> list:
        """Récupère les enregistrements filtrés par labels."""
        if self._bucket is None:
            await self.connect()
        kwargs = {"include": {
            "experiment": experiment, "well": well,
            "planarian": str(planarian), "record_type": record_type,
        }}
        if start:
            kwargs["start"] = int(start.timestamp() * 1_000_000)
        if stop:
            kwargs["stop"]  = int(stop.timestamp() * 1_000_000)
        records = []
        async for rec in self._bucket.query("metrics", **kwargs):
            try:
                records.append(json.loads(await rec.read_all()))
            except Exception as e:
                logger.warning(f"Entrée illisible ignorée : {e}")
        return records

    @staticmethod
    def _convert_timestamps(records: list) -> list:
        """
        Convertit le champ 'timestamp' (epoch float secondes) en ISO 8601 UTC
        dans chaque enregistrement.

        Args:
            records : liste de dicts issus de ReductStore

        Returns:
            nouvelle liste avec timestamp converti (originaux non modifiés)
        """
        converted = []
        for r in records:
            row = dict(r)
            ts  = row.get("timestamp")
            if ts is not None:
                try:
                    row["timestamp"] = (
                        datetime.fromtimestamp(float(ts), tz=timezone.utc)
                        .strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
                    )
                except (ValueError, TypeError, OSError):
                    pass
            converted.append(row)
        return converted

    @staticmethod
    def _build_filepath(output_dir: str, experiment: str,
                        well: str, planarian: int, record_type: str) -> str:
        """
        Construit le chemin du fichier CSV de sortie.
        Nom : <experiment>_<well>_planaire<NN>_<record_type>.csv

        Args:
            output_dir  : répertoire de sortie (créé si absent)
            experiment  : identifiant de l'expérience
            well        : identifiant du puits
            planarian   : index du planaire
            record_type : "frame" ou "summary"

        Returns:
            chemin absolu du fichier CSV
        """
        dirpath  = os.path.abspath(output_dir)
        os.makedirs(dirpath, exist_ok=True)
        filename = f"{experiment}_{well}_planaire{planarian:02d}_{record_type}.csv"
        return os.path.join(dirpath, filename)

    async def export_csv(
        self,
        experiment:  str,
        well:        str,
        planarian:   int = 0,
        record_type: str = "metrics",
        output_dir:  str = ".",
        start:       Optional[datetime] = None,
        stop:        Optional[datetime] = None,
    ) -> tuple:
        """
        Exporte les données depuis ReductStore vers un fichier CSV.
        Le répertoire de sortie est choisi via output_dir.
        Le champ timestamp est converti en ISO 8601 UTC.

        Args:
            experiment  : identifiant de l'expérience
            well        : identifiant du puits
            planarian   : index du planaire
            record_type : "frame" | "summary"
            output_dir  : répertoire de sortie (défaut : répertoire courant)
            start, stop : plage temporelle (datetime UTC, optionnel)

        Returns:
            tuple (filepath, nb_lignes)
        """
        records = await self.get_tracking_data(
            experiment, well, planarian, record_type, start, stop)
        if not records:
            logger.warning(f"Aucune donnée pour {experiment}/{well}/{planarian}")
            return "", 0

        records    = self._convert_timestamps(records)
        filepath   = self._build_filepath(output_dir, experiment, well,
                                          planarian, record_type)
        fieldnames = list(dict.fromkeys(k for r in records for k in r.keys()))

        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(records)

        logger.info(f"Export CSV : {len(records)} lignes → {filepath}")
        return filepath, len(records)

    async def export_csv_response(
        self,
        experiment:  str,
        well:        str,
        planarian:   int = 0,
        record_type: str = "metrics",
        start:       Optional[datetime] = None,
        stop:        Optional[datetime] = None,
    ) -> tuple:
        """
        Génère le contenu CSV en mémoire (pour réponse HTTP Django).
        Le champ timestamp est converti en ISO 8601 UTC.

        Returns:
            tuple (contenu_csv_str, nb_lignes)
        """
        records = await self.get_tracking_data(
            experiment, well, planarian, record_type, start, stop)
        if not records:
            return "", 0
        records    = self._convert_timestamps(records)
        fieldnames = list(dict.fromkeys(k for r in records for k in r.keys()))
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
        return out.getvalue(), len(records)

    async def close(self):
        """
        Ferme la connexion ReductStore.
        Note : reduct-py >= 1.x ne nécessite pas de fermeture explicite —
        la méthode est conservée pour compatibilité d'interface.
        """
        self._client = None
        self._bucket = None
        logger.info("ReductStore déconnecté")        
        
