#!../.venv/bin/python
"""
Planaria random movement simulation - top view
Espace circulaire de 16mm de diamètre, 500x500px
Supporte plusieurs planaires avec paramètres configurables via arguments CLI.
Export CSV par planaire compatible EthoVision XT.

Comportements simulés :
    - Thigmotactisme  : attraction vers la paroi (--thigmotaxis)
    - Phototactisme   : fuite de la lumière (--photo-mode, --photo-strength)
    - Chimiotactisme  : attraction vers une source de nourriture (--chemo-strength)
    - Inter-individus : évitement de contact, agrégation, répulsion chimique

Usage:
    python3 planaire_sim.py [options]

Exemples:
    python3 planaire_sim.py --count 5 --thigmotaxis 0.4
    python3 planaire_sim.py --count 5 --photo-mode fixed --photo-x 0.2 --photo-y 0.2 --photo-strength 0.6
    python3 planaire_sim.py --count 5 --chemo-x 0.7 --chemo-y 0.5 --chemo-strength 0.5
    python3 planaire_sim.py --count 5 --avoid-strength 0.6 --aggreg-strength 0.2
"""
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'home.settings')

import csv
import cv2
try:
    from planarian_metrics import EthoVisionMetrics
    HAS_METRICS = True
except ImportError:
    HAS_METRICS = False
import numpy as np
import math
import random
import argparse
import re

from django.conf import settings

CSV_DIR = str(settings.MEDIA_ROOT / "simulation" / "planarian_sim_csv")
VIDEO_PATH = str(settings.MEDIA_ROOT / "simulation" / "planarian_simulation.mp4")

# ---------------------------------------------------------------------------
# Noms CSS courants → BGR
# ---------------------------------------------------------------------------
CSS_COLORS = {
    "white":       (255, 255, 255), "black":       (  0,   0,   0),
    "red":         (  0,   0, 255), "green":       (  0, 128,   0),
    "blue":        (255,   0,   0), "yellow":      (  0, 255, 255),
    "cyan":        (255, 255,   0), "magenta":     (255,   0, 255),
    "orange":      (  0, 165, 255), "pink":        (203, 192, 255),
    "purple":      (128,   0, 128), "brown":       ( 42,  42, 165),
    "gray":        (128, 128, 128), "grey":        (128, 128, 128),
    "lightgray":   (211, 211, 211), "darkgray":    (169, 169, 169),
    "beige":       (220, 245, 245), "ivory":       (240, 255, 255),
    "khaki":       (140, 230, 240), "olive":       (  0, 128, 128),
    "teal":        (128, 128,   0), "navy":        (128,   0,   0),
    "coral":       ( 80, 127, 255), "salmon":      (114, 128, 250),
    "tan":         (140, 180, 210), "wheat":       (179, 222, 245),
    "linen":       (230, 240, 250), "lavender":    (250, 230, 230),
    "transparent": (  0,   0,   0),
}


def parse_color(value):
    """
    Convertit une couleur CLI en tuple BGR pour OpenCV.
    Formats : "#RRGGBB" | "R G B" (RGB) | nom CSS.
    """
    if isinstance(value, list):
        value = " ".join(str(v) for v in value)
    value = value.strip()

    hex_match = re.fullmatch(r"#?([0-9A-Fa-f]{6})", value)
    if hex_match:
        h = hex_match.group(1)
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return (b, g, r)

    rgb_match = re.fullmatch(r"(\d+)\s+(\d+)\s+(\d+)", value)
    if rgb_match:
        r, g, b = int(rgb_match.group(1)), int(rgb_match.group(2)), int(rgb_match.group(3))
        for v in (r, g, b):
            if not 0 <= v <= 255:
                raise argparse.ArgumentTypeError(f"Valeur RGB hors plage [0-255] : {v}")
        return (b, g, r)

    key = value.lower().replace(" ", "").replace("-", "")
    if key in CSS_COLORS:
        return CSS_COLORS[key]

    raise argparse.ArgumentTypeError(
        f"Couleur non reconnue : '{value}'. "
        f"Formats : #RRGGBB | R G B | nom CSS (beige, tan, white…)"
    )


class ColorAction(argparse.Action):
    """Action argparse pour les couleurs — accepte hex, RGB ou nom CSS."""
    def __call__(self, parser, namespace, values, option_string=None):
        try:
            setattr(namespace, self.dest, parse_color(values))
        except argparse.ArgumentTypeError as e:
            parser.error(str(e))


# ---------------------------------------------------------------------------
# Parsing des arguments CLI
# ---------------------------------------------------------------------------

def parse_args():
    """Définit et parse tous les arguments de la simulation."""
    parser = argparse.ArgumentParser(
        description="Simulation du déplacement aléatoire de planaires (vue de dessus)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    # --- Paramètres vidéo ---
    vg = parser.add_argument_group("Paramètres vidéo")
    vg.add_argument("--default_width", type=int,   default=500, help="Image: largeur par défaut px")
    vg.add_argument("--default_height", type=int,   default=500, help="Image: hauteur par défautpx")
    vg.add_argument("--default_diameter", type=float,  default=16.0, help="Diamètre tube par défaut mm")
    
    vg.add_argument("--fps",      type=int,   default=10,   help="Images par seconde")
    vg.add_argument("--duration", type=int,   default=10,   help="Durée en secondes")
    vg.add_argument("--output",   type=str,   default=VIDEO_PATH, help="Fichier vidéo de sortie")
    vg.add_argument("--seed",     type=int,   default=42,   help="Graine aléatoire")

    # --- Morphologie ---
    pg = parser.add_argument_group("Morphologie du planaire")
    pg.add_argument("--length",   type=float, default=1.0,  help="Longueur en mm")
    pg.add_argument("--width",    type=float, default=0.35,  help="Largeur max en mm")
    pg.add_argument("--count",    type=int,   default=1,    help="Nombre de planaires (1-20)")

    # --- Thigmotactisme ---
    bg = parser.add_argument_group(
        "Thigmotactisme",
        "Attraction vers la paroi circulaire (0=désactivé, 1=fort)"
    )
    bg.add_argument("--thigmotaxis", type=float, default=0.0,
                    help="Intensité (0.0-1.0, typique : 0.3-0.6)")

    # --- Phototactisme ---
    lg = parser.add_argument_group(
        "Phototactisme",
        "Les planaires fuient la lumière. "
        "Modes : fixed (source fixe x,y) | sine (source sinusoïdale) | radial (gradient depuis le centre)"
    )
    lg.add_argument("--photo-mode",     type=str,   default="none",
                    choices=["none", "fixed", "sine", "radial"],
                    help="Mode de source lumineuse")
    lg.add_argument("--photo-strength", type=float, default=0.5,
                    help="Intensité de la fuite (0.0-1.0)")
    lg.add_argument("--photo-x",        type=float, default=0.5,
                    help="Position X source fixe (fraction 0-1 de l'arène, 0=gauche)")
    lg.add_argument("--photo-y",        type=float, default=0.5,
                    help="Position Y source fixe (fraction 0-1 de l'arène, 0=haut)")
    lg.add_argument("--photo-sine-freq",type=float, default=0.1,
                    help="Fréquence du mouvement sinusoïdal de la source (Hz)")
    lg.add_argument("--photo-radius",   type=float, default=0.3,
                    help="Rayon du gradient radial (fraction du rayon de l'arène, mode radial)")

    # --- Chimiotactisme ---
    cg = parser.add_argument_group(
        "Chimiotactisme",
        "Attraction vers une source de nourriture (point unique dans l'arène)"
    )
    cg.add_argument("--chemo-strength", type=float, default=0.0,
                    help="Intensité de l'attraction chimique (0=désactivé, 1=fort)")
    cg.add_argument("--chemo-x",        type=float, default=0.7,
                    help="Position X de la nourriture (fraction 0-1)")
    cg.add_argument("--chemo-y",        type=float, default=0.7,
                    help="Position Y de la nourriture (fraction 0-1)")
    cg.add_argument("--chemo-radius",   type=float, default=2.0,
                    help="Rayon d'influence du chimiotactisme en mm")

    # --- Interactions inter-individus ---
    ig = parser.add_argument_group(
        "Interactions inter-individus",
        "Évitement de contact, agrégation et répulsion chimique entre planaires"
    )
    ig.add_argument("--avoid-strength",  type=float, default=0.0,
                    help="Force d'évitement de contact (0=désactivé, 1=fort)")
    ig.add_argument("--avoid-radius",    type=float, default=3.0,
                    help="Rayon d'évitement en mm")
    ig.add_argument("--aggreg-strength", type=float, default=0.0,
                    help="Force d'agrégation — attraction vers les congénères (0=désactivé)")
    ig.add_argument("--aggreg-radius",   type=float, default=6.0,
                    help="Rayon d'agrégation en mm (doit être > --avoid-radius)")
    ig.add_argument("--chem-repulsion",  type=float, default=0.0,
                    help="Répulsion chimique — fuite des traces laissées par les congénères (0=désactivé)")
    ig.add_argument("--chem-decay",      type=float, default=0.95,
                    help="Facteur de décroissance des traces chimiques par frame (0-1)")

    # --- Seuils de mobilité EthoVision ---
    mg = parser.add_argument_group("Seuils de mobilité (EthoVision XT)")
    mg.add_argument("--thresh-immobile", type=float, default=0.2,
                    help="Vitesse max état Immobile (mm/s)")
    mg.add_argument("--thresh-mobile",   type=float, default=1.5,
                    help="Vitesse max état Mobile (mm/s). Au-delà = Très mobile")

    # --- Export CSV ---
    eg = parser.add_argument_group("Export métriques")
    eg.add_argument("--csv-dir", type=str, default=CSV_DIR, help="Répertoire de sortie CSV")
    eg.add_argument("--no-csv",  action="store_true",  help="Désactiver l'export CSV")

    # --- Couleurs ---
    kg = parser.add_argument_group(
        "Couleurs",
        "Formats : #RRGGBB  |  R G B (RGB)  |  nom CSS (beige, tan, white…)"
    )
    kg.add_argument("--bg-color",     nargs='+', action=ColorAction,
                    default=(235, 235, 235), metavar="COULEUR",
                    help="Fond extérieur (vue dessous, lumière transmise) $EBEBEB")
    kg.add_argument("--arena-color",  nargs='+', action=ColorAction,
                    default=(250, 250, 250), metavar="COULEUR",
                    help="Intérieur arène — blanc éclairé par transmission $FAFAFA")
    kg.add_argument("--arena-border", nargs='+', action=ColorAction,
                    default=(140, 140, 140), metavar="COULEUR",
                    help="Bordure arène $8C8C8C — légèrement plus sombre que l'arène")
    kg.add_argument("--shadow-color", nargs='+', action=ColorAction,
                    default=(200, 200, 200), metavar="COULEUR",
                    help="Ombre portée — très légère sous lumière transmise $C8C8C8")
    kg.add_argument("--body-color",   nargs='+', action=ColorAction,
                    default=(165, 165, 165), metavar="COULEUR",
                    help="Corps — gris translucide moyen $A5A5A5")
    kg.add_argument("--body-dark",    nargs='+', action=ColorAction,
                    default=(55, 55, 55),    metavar="COULEUR",
                    help="Contour sombre net du corps $373737 — pour le contraste et la lisibilité")
    kg.add_argument("--body-light",   nargs='+', action=ColorAction,
                    default=(210, 210, 210), metavar="COULEUR",
                    help="Centre du corps — plus clair par transparence $D2D2D2")
    kg.add_argument("--head-color",   nargs='+', action=ColorAction,
                    default=(130, 130, 130), metavar="COULEUR",
                    help="Tête — légèrement plus sombre que le corps $828282 — pour la différencier du reste du corps")

    args = parser.parse_args()

    # Validations
    if args.count < 1 or args.count > 20:
        parser.error("--count doit être compris entre 1 et 20")
    if args.thresh_immobile >= args.thresh_mobile:
        parser.error("--thresh-immobile doit être < --thresh-mobile")
    if args.aggreg_radius <= args.avoid_radius:
        parser.error("--aggreg-radius doit être > --avoid-radius")

    return args


# ---------------------------------------------------------------------------
# Carte chimique partagée (traces de répulsion inter-individus)
# ---------------------------------------------------------------------------

class ChemicalMap:
    """
    Carte de concentration chimique en 2D simulant les traces de mucus
    laissées par les planaires (répulsion chimique inter-individus).

    Chaque planaire dépose une trace à sa position courante.
    La concentration décroît exponentiellement à chaque frame (decay).
    """

    def __init__(self, width, height, decay):
        """
        Args:
            width, height : dimensions en pixels de l'arène
            decay         : facteur de décroissance par frame (ex: 0.95)
        """
        self.map   = np.zeros((height, width), dtype=np.float32)
        self.decay = decay

    def deposit(self, x_px, y_px, radius_px=4, amount=1.0):
        """
        Dépose une trace chimique à la position (x_px, y_px).

        Args:
            x_px, y_px : position en pixels
            radius_px  : rayon de dépôt en pixels
            amount     : quantité déposée (0-1)
        """
        xi, yi = int(round(x_px)), int(round(y_px))
        cv2.circle(self.map, (xi, yi), radius_px, amount, -1)
        # Clamp à 1.0
        np.clip(self.map, 0.0, 1.0, out=self.map)

    def step(self):
        """Applique la décroissance temporelle (à appeler une fois par frame)."""
        self.map *= self.decay

    def gradient_at(self, x_px, y_px, radius_px=8):
        """
        Calcule le gradient de concentration autour du point (x_px, y_px).
        Retourne l'angle de montée du gradient (direction de concentration croissante)
        et l'intensité locale.

        Args:
            x_px, y_px : position en pixels
            radius_px  : rayon de lecture du gradient

        Returns:
            tuple (angle_rad, intensity) ou (None, 0) si hors carte
        """
        h, w = self.map.shape
        xi, yi = int(round(x_px)), int(round(y_px))

        # Lecture des concentrations dans les 4 directions cardinales
        def safe_get(x, y):
            """Accès sécurisé à la carte avec rebord à zéro."""
            if 0 <= x < w and 0 <= y < h:
                return float(self.map[y, x])
            return 0.0

        dx = safe_get(xi + radius_px, yi) - safe_get(xi - radius_px, yi)
        dy = safe_get(xi, yi + radius_px) - safe_get(xi, yi - radius_px)
        intensity = safe_get(xi, yi)

        if abs(dx) < 1e-6 and abs(dy) < 1e-6:
            return None, intensity

        return math.atan2(dy, dx), intensity


# ---------------------------------------------------------------------------
# Classe Tracker — métriques EthoVision par planaire
# ---------------------------------------------------------------------------

class Tracker:
    """
    Calcule et accumule les métriques de déplacement compatibles EthoVision XT.
    Une instance par planaire.
    """

    IMMOBILE    = "Immobile"
    MOBILE      = "Mobile"
    HIGH_MOBILE = "Highly mobile"

    def __init__(self, planaire_id, mm_to_px, fps, thresh_immobile, thresh_mobile,
                 arena_center, arena_radius_px):
        self.planaire_id     = planaire_id
        self.mm_to_px        = mm_to_px
        self.fps             = fps
        self.thresh_immobile = thresh_immobile
        self.thresh_mobile   = thresh_mobile
        self.arena_center    = arena_center
        self.arena_radius_px = arena_radius_px
        self.dt              = 1.0 / fps

        self.total_distance_mm  = 0.0
        self.duration_moving_s  = 0.0
        self.duration_stopped_s = 0.0

        self._mobility_counts    = {self.IMMOBILE: 0, self.MOBILE: 0, self.HIGH_MOBILE: 0}
        self._mobility_durations = {self.IMMOBILE: 0.0, self.MOBILE: 0.0, self.HIGH_MOBILE: 0.0}
        self._current_state      = None
        self._prev_x = None
        self._prev_y = None

        self.records = []

    def _px_to_mm(self, dist_px):
        """Convertit des pixels en millimètres."""
        return dist_px / self.mm_to_px

    def _classify_mobility(self, velocity_mm_s):
        """Classe la vitesse selon les seuils EthoVision."""
        if velocity_mm_s <= self.thresh_immobile:
            return self.IMMOBILE
        elif velocity_mm_s <= self.thresh_mobile:
            return self.MOBILE
        return self.HIGH_MOBILE

    def update(self, frame_idx, x_px, y_px):
        """
        Met à jour les métriques pour la frame courante.

        Args:
            frame_idx : index de la frame (0-based)
            x_px, y_px: position du centre du planaire en pixels
        """
        t_s = frame_idx * self.dt

        if self._prev_x is not None:
            dx_px         = x_px - self._prev_x
            dy_px         = y_px - self._prev_y
            dist_mm       = self._px_to_mm(math.sqrt(dx_px**2 + dy_px**2))
            velocity_mm_s = dist_mm / self.dt
        else:
            dist_mm       = 0.0
            velocity_mm_s = 0.0

        self.total_distance_mm += dist_mm
        is_moving = velocity_mm_s > self.thresh_immobile
        if is_moving:
            self.duration_moving_s  += self.dt
        else:
            self.duration_stopped_s += self.dt

        new_state = self._classify_mobility(velocity_mm_s)
        if new_state != self._current_state:
            self._mobility_counts[new_state] += 1
            self._current_state = new_state
        self._mobility_durations[new_state] += self.dt

        dx_arena       = x_px - self.arena_center[0]
        dy_arena       = y_px - self.arena_center[1]
        dist_center_px = math.sqrt(dx_arena**2 + dy_arena**2)
        dist_wall_mm   = self._px_to_mm(self.arena_radius_px - dist_center_px)

        self.records.append({
            "frame":               frame_idx,
            "time_s":              round(t_s, 3),
            "x_mm":                round(self._px_to_mm(x_px), 4),
            "y_mm":                round(self._px_to_mm(y_px), 4),
            "velocity_mm_s":       round(velocity_mm_s, 4),
            "distance_mm":         round(dist_mm, 4),
            "total_distance_mm":   round(self.total_distance_mm, 4),
            "moving":              int(is_moving),
            "duration_moving_s":   round(self.duration_moving_s, 3),
            "duration_stopped_s":  round(self.duration_stopped_s, 3),
            "mobility_state":      new_state,
            "dist_to_wall_mm":     round(dist_wall_mm, 4),
            "dist_to_center_mm":   round(self._px_to_mm(dist_center_px), 4),
        })

        self._prev_x = x_px
        self._prev_y = y_px

    def summary(self):
        """Retourne le dictionnaire de résumé global (nomenclature EthoVision)."""
        total_s = len(self.records) / self.fps
        return {
            "planaire_id":                       self.planaire_id,
            "total_duration_s":                  round(total_s, 3),
            "movedCenter_pointTotal_mm":          round(self.total_distance_mm, 4),
            "velocity_mean_mm_s":                round(
                self.total_distance_mm / total_s if total_s > 0 else 0.0, 4),
            "movement_moving_duration_s":         round(self.duration_moving_s, 3),
            "movement_not_moving_duration_s":     round(self.duration_stopped_s, 3),
            "mobility_immobile_frequency":        self._mobility_counts[self.IMMOBILE],
            "mobility_immobile_duration_s":       round(self._mobility_durations[self.IMMOBILE], 3),
            "mobility_mobile_frequency":          self._mobility_counts[self.MOBILE],
            "mobility_mobile_duration_s":         round(self._mobility_durations[self.MOBILE], 3),
            "mobility_highly_mobile_frequency":   self._mobility_counts[self.HIGH_MOBILE],
            "mobility_highly_mobile_duration_s":  round(self._mobility_durations[self.HIGH_MOBILE], 3),
            "thigmotaxis_pct_time_near_wall":     round(
                100.0 * sum(1 for r in self.records if r["dist_to_wall_mm"] < 1.0)
                / max(len(self.records), 1), 2),
        }

    def write_csv(self, csv_dir, output_stem):
        """
        Écrit les CSV frames et summary pour ce planaire.

        Args:
            csv_dir     : répertoire de sortie
            output_stem : nom de base du fichier vidéo (sans extension)
        """
        os.makedirs(csv_dir, exist_ok=True)
        base = f"{output_stem}_planaire_{self.planaire_id:02d}"

        frames_path = os.path.join(csv_dir, f"{base}_frames.csv")
        if self.records:
            with open(frames_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=list(self.records[0].keys()))
                writer.writeheader()
                writer.writerows(self.records)

        summary_path = os.path.join(csv_dir, f"{base}_summary.csv")
        s = self.summary()
        with open(summary_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(s.keys()))
            writer.writeheader()
            writer.writerow(s)

        print(f"  CSV [{self.planaire_id:02d}] → {frames_path}")
        print(f"  CSV [{self.planaire_id:02d}] → {summary_path}")


# ---------------------------------------------------------------------------
# Classe Planaire
# ---------------------------------------------------------------------------

class Planaire:
    """
    Simule le déplacement aléatoire d'un planaire dans une arène circulaire.

    Comportements intégrés :
        - Locomotion aléatoire avec ondulation
        - Thigmotactisme (paroi)
        - Phototactisme  (fuite lumière)
        - Chimiotactisme (attraction nourriture)
        - Interactions inter-individus (évitement, agrégation, répulsion chimique)
    """

    def __init__(self, planaire_id, cfg, arena_center, arena_radius_px,
                 mm_to_px, start_x=None, start_y=None):
        """
        Args:
            planaire_id     : identifiant numérique (0-based)
            cfg             : namespace argparse
            arena_center    : tuple (cx, cy) en pixels
            arena_radius_px : rayon de l'arène en pixels
            mm_to_px        : facteur de conversion mm → pixels
            start_x, start_y: position initiale en pixels (None = aléatoire)
        """
        self.planaire_id     = planaire_id
        self.cfg             = cfg
        self.arena_center    = arena_center
        self.arena_radius_px = arena_radius_px
        self.mm_to_px        = mm_to_px

        # --- Variation individuelle de morphologie (±20% longueur, ±25% largeur) ---
        self.length_px = max(20, int(cfg.planaire_length_px * random.uniform(0.80, 1.20)))
        self.width_px  = max(3,  int(cfg.planaire_width_px  * random.uniform(0.75, 1.25)))

        # --- Palette de couleur individuelle (5 familles naturalistes) ---
        # Palettes grises — vue de dessous, lumière transmise par le dessus.
        # Teinte uniforme gris moyen, seul le niveau de gris varie légèrement
        # entre individus pour les distinguer visuellement.
        PALETTES = [
            {"body": (165, 165, 165), "dark": (50,  50,  50),  "light": (210, 210, 210), "head": (130, 130, 130)},
            {"body": (150, 150, 150), "dark": (45,  45,  45),  "light": (200, 200, 200), "head": (118, 118, 118)},
            {"body": (178, 178, 178), "dark": (58,  58,  58),  "light": (218, 218, 218), "head": (142, 142, 142)},
            {"body": (158, 158, 158), "dark": (48,  48,  48),  "light": (205, 205, 205), "head": (125, 125, 125)},
            {"body": (172, 172, 172), "dark": (55,  55,  55),  "light": (215, 215, 215), "head": (138, 138, 138)},
        ]
        palette = PALETTES[random.randint(0, len(PALETTES) - 1)]

        def jitter(color, amount=5):
            """Variation individuelle minimale — teinte grise très uniforme."""
            v = random.randint(-amount, amount)
            return tuple(max(0, min(255, c + v)) for c in color)

        self.body_color   = jitter(palette["body"])
        self.body_dark    = jitter(palette["dark"],  3)
        self.body_light   = jitter(palette["light"], 3)
        self.head_color   = jitter(palette["head"],  3)
        self.shadow_color = tuple(cfg.shadow_color)

        # --- Sensibilités individuelles (variation ±30% autour des valeurs globales) ---
        def indiv(val):
            """Variation individuelle ±30% clampée à [0, 1]."""
            return max(0.0, min(1.0, val * random.uniform(0.70, 1.30)))

        self.thigmotaxis     = indiv(cfg.thigmotaxis)
        self.photo_strength  = indiv(cfg.photo_strength)
        self.chemo_strength  = indiv(cfg.chemo_strength)
        self.avoid_strength  = indiv(cfg.avoid_strength)
        self.aggreg_strength = indiv(cfg.aggreg_strength)
        self.chem_repulsion  = indiv(cfg.chem_repulsion)

        # --- Position initiale ---
        if start_x is not None and start_y is not None:
            self.x = float(start_x)
            self.y = float(start_y)
        else:
            a = random.uniform(0, 2 * math.pi)
            r = random.uniform(0, arena_radius_px * 0.5)
            self.x = arena_center[0] + r * math.cos(a)
            self.y = arena_center[1] + r * math.sin(a)

        # --- État cinématique ---
        self.angle          = random.uniform(0, 2 * math.pi)
        self.speed          = random.uniform(2.5, 5.0)
        self.wave_phase     = random.uniform(0, 2 * math.pi)
        self.wave_freq      = random.uniform(0.6, 1.0)
        self.wave_amp       = random.uniform(0.14, 0.22)
        self.turn_rate      = 0.0
        self.frames_to_turn = 0
        self.pause_frames   = 0

        # --- Historique de positions pour le rendu du corps courbé ---
        self.body_history = []
        self._init_body()

    def _init_body(self):
        """Initialise l'historique de positions du corps en ligne droite."""
        for i in range(self.length_px):
            self.body_history.append((
                self.x - i * math.cos(self.angle),
                self.y - i * math.sin(self.angle)
            ))

    # --- Utilitaire : déviation angulaire vers une cible ---
    @staticmethod
    def _steer_toward(current_angle, target_angle, weight):
        """
        Calcule la correction angulaire vers target_angle pondérée par weight.

        Args:
            current_angle : angle courant en radians
            target_angle  : angle cible en radians
            weight        : force de la déviation (0=aucune, 1=totale)

        Returns:
            correction angulaire en radians
        """
        diff = (target_angle - current_angle + math.pi) % (2 * math.pi) - math.pi
        return weight * diff

    @staticmethod
    def _steer_away(current_angle, threat_angle, weight):
        """
        Calcule la correction angulaire pour fuir threat_angle.

        Args:
            current_angle : angle courant en radians
            threat_angle  : angle vers la menace en radians
            weight        : force de la fuite (0=aucune, 1=totale)

        Returns:
            correction angulaire en radians
        """
        away_angle = threat_angle + math.pi
        diff = (away_angle - current_angle + math.pi) % (2 * math.pi) - math.pi
        return weight * diff

    def _photo_angle(self, frame_idx, photo_source_x, photo_source_y):
        """
        Calcule la correction angulaire due au phototactisme.
        Le planaire fuit la source lumineuse.

        Args:
            frame_idx                : frame courante (pour mode sine)
            photo_source_x, _y      : position de la source lumineuse en pixels

        Returns:
            correction angulaire en radians (0 si phototactisme désactivé)
        """
        if self.cfg.photo_mode == "none" or self.photo_strength == 0.0:
            return 0.0

        if self.cfg.photo_mode == "radial":
            # Gradient radial : fuite vers la périphérie de l'arène
            dx = self.x - self.arena_center[0]
            dy = self.y - self.arena_center[1]
            dist_c = math.sqrt(dx**2 + dy**2)
            if dist_c < 1.0:
                return 0.0
            # Intensité inversement proportionnelle à la distance au centre
            zone = self.arena_radius_px * self.cfg.photo_radius
            intensity = max(0.0, 1.0 - dist_c / zone) * self.photo_strength
            away_center = math.atan2(dy, dx)   # fuite vers la périphérie
            return self._steer_toward(self.angle, away_center, intensity)

        # Modes fixed et sine : fuite depuis la source ponctuelle
        dx = self.x - photo_source_x
        dy = self.y - photo_source_y
        dist = math.sqrt(dx**2 + dy**2)
        if dist < 1.0:
            return 0.0

        # Intensité inversement proportionnelle à la distance (décroissance linéaire)
        influence_radius = self.arena_radius_px * 1.2
        intensity = max(0.0, 1.0 - dist / influence_radius) * self.photo_strength
        toward_source = math.atan2(dy, dx)
        return self._steer_away(self.angle, toward_source - math.pi, intensity)

    def _chemo_angle(self, chemo_x_px, chemo_y_px):
        """
        Calcule la correction angulaire due au chimiotactisme.
        Le planaire est attiré vers la source de nourriture.

        Args:
            chemo_x_px, chemo_y_px : position de la nourriture en pixels

        Returns:
            correction angulaire en radians
        """
        if self.chemo_strength == 0.0:
            return 0.0

        dx = chemo_x_px - self.x
        dy = chemo_y_px - self.y
        dist = math.sqrt(dx**2 + dy**2)
        if dist < 1.0:
            return 0.0

        # Influence décroissante avec la distance (rayon paramétrable)
        influence_radius = self.cfg.chemo_radius * self.mm_to_px
        intensity = max(0.0, 1.0 - dist / influence_radius) * self.chemo_strength
        toward_food = math.atan2(dy, dx)
        return self._steer_toward(self.angle, toward_food, intensity)

    def _social_angle(self, others):
        """
        Calcule la correction angulaire due aux interactions inter-individus :
            - Évitement de contact (répulsion courte portée)
            - Agrégation (attraction longue portée)

        Args:
            others : liste de tuples (x, y) des positions des autres planaires

        Returns:
            correction angulaire en radians
        """
        if not others:
            return 0.0

        avoid_radius_px  = self.cfg.avoid_radius  * self.mm_to_px
        aggreg_radius_px = self.cfg.aggreg_radius * self.mm_to_px

        avoid_dx, avoid_dy   = 0.0, 0.0   # vecteur de répulsion cumulé
        aggreg_dx, aggreg_dy = 0.0, 0.0   # vecteur d'attraction cumulé
        n_avoid, n_aggreg    = 0, 0

        for ox, oy in others:
            dx   = self.x - ox
            dy   = self.y - oy
            dist = math.sqrt(dx**2 + dy**2)

            if dist < 1.0:
                continue

            if dist < avoid_radius_px:
                # Répulsion inversement proportionnelle à la distance
                force = (1.0 - dist / avoid_radius_px)
                avoid_dx += dx / dist * force
                avoid_dy += dy / dist * force
                n_avoid  += 1

            elif dist < aggreg_radius_px:
                # Attraction proportionnelle à la distance (plus fort si loin)
                force = (dist - avoid_radius_px) / (aggreg_radius_px - avoid_radius_px)
                aggreg_dx += -dx / dist * force
                aggreg_dy += -dy / dist * force
                n_aggreg  += 1

        correction = 0.0

        if n_avoid > 0 and self.avoid_strength > 0.0:
            avoid_angle = math.atan2(avoid_dy / n_avoid, avoid_dx / n_avoid)
            correction += self._steer_toward(self.angle, avoid_angle,
                                             self.avoid_strength * 0.8)

        if n_aggreg > 0 and self.aggreg_strength > 0.0:
            aggreg_angle = math.atan2(aggreg_dy / n_aggreg, aggreg_dx / n_aggreg)
            correction += self._steer_toward(self.angle, aggreg_angle,
                                             self.aggreg_strength * 0.4)

        return correction

    def _chem_repulsion_angle(self, chem_map):
        """
        Calcule la correction angulaire due à la répulsion chimique (traces de mucus).
        Le planaire fuit les zones de forte concentration chimique.

        Args:
            chem_map : instance ChemicalMap

        Returns:
            correction angulaire en radians
        """
        if self.chem_repulsion == 0.0 or chem_map is None:
            return 0.0

        grad_angle, intensity = chem_map.gradient_at(self.x, self.y)
        if grad_angle is None or intensity < 0.01:
            return 0.0

        # Fuite dans la direction opposée au gradient
        return self._steer_away(self.angle, grad_angle, self.chem_repulsion * intensity)

    def update(self, frame_idx, others_positions, chem_map, photo_source):
        """
        Met à jour la position et l'orientation du planaire pour une frame.

        Args:
            frame_idx       : index de la frame courante
            others_positions: liste de (x, y) des autres planaires
            chem_map        : instance ChemicalMap (ou None)
            photo_source    : tuple (x, y) de la source lumineuse en pixels
        """
        fps = self.cfg.fps

        # --- Gestion des pauses (immobilité momentanée) ---
        if self.pause_frames > 0:
            self.pause_frames -= 1
            self.wave_phase += self.wave_freq * (2 * math.pi / fps) * 0.3
            self.body_history.insert(0, (self.x, self.y))
            self.body_history.pop()
            if chem_map is not None:
                chem_map.deposit(self.x, self.y)
            return

        # --- Choix du prochain comportement locomoteur de base ---
        if self.frames_to_turn <= 0:
            r     = random.random()
            delta = 0.0
            if r < 0.05:
                self.pause_frames = random.randint(3, 8)
                return
            elif r < 0.35:
                delta               = random.uniform(-math.pi * 0.7, math.pi * 0.7)
                self.frames_to_turn = random.randint(6, 18)
                self.speed          = random.uniform(2.0, 5.5)
            else:
                delta               = random.uniform(-math.pi * 0.2, math.pi * 0.2)
                self.frames_to_turn = random.randint(3, 10)
                self.speed          = random.uniform(3.0, 6.0)
            self.turn_rate = delta / max(self.frames_to_turn, 1)

        if self.frames_to_turn > 0:
            self.angle += self.turn_rate
            self.frames_to_turn -= 1

        # --- Ondulation du corps ---
        self.wave_phase += self.wave_freq * (2 * math.pi / fps)
        effective_angle  = self.angle + self.wave_amp * math.sin(self.wave_phase)

        # --- Thigmotactisme ---
        if self.thigmotaxis > 0.0:
            dx_cur     = self.x - self.arena_center[0]
            dy_cur     = self.y - self.arena_center[1]
            dist_c     = math.sqrt(dx_cur**2 + dy_cur**2)
            zone_start = self.arena_radius_px * 0.60
            zone_end   = self.arena_radius_px * 0.90
            if dist_c > zone_start:
                influence     = min(1.0, (dist_c - zone_start) / (zone_end - zone_start))
                radial_angle  = math.atan2(dy_cur, dx_cur)
                tangent_angle = radial_angle + math.pi / 2
                diff = (tangent_angle - effective_angle + math.pi) % (2 * math.pi) - math.pi
                if diff > math.pi / 2 or diff < -math.pi / 2:
                    tangent_angle += math.pi
                effective_angle += influence * self.thigmotaxis * (
                    (tangent_angle - effective_angle + math.pi) % (2 * math.pi) - math.pi
                )

        # --- Accumulation des corrections comportementales ---
        photo_x, photo_y = photo_source
        chemo_x = self.arena_center[0] + (self.cfg.chemo_x - 0.5) * 2 * self.arena_radius_px
        chemo_y = self.arena_center[1] + (self.cfg.chemo_y - 0.5) * 2 * self.arena_radius_px

        effective_angle += self._photo_angle(frame_idx, photo_x, photo_y)
        effective_angle += self._chemo_angle(chemo_x, chemo_y)
        effective_angle += self._social_angle(others_positions)
        effective_angle += self._chem_repulsion_angle(chem_map)

        # --- Calcul de la nouvelle position ---
        new_x = self.x + self.speed * math.cos(effective_angle)
        new_y = self.y + self.speed * math.sin(effective_angle)

        # --- Rebond sur la paroi circulaire ---
        dx     = new_x - self.arena_center[0]
        dy     = new_y - self.arena_center[1]
        dist   = math.sqrt(dx**2 + dy**2)
        margin = self.length_px // 2

        if dist + margin > self.arena_radius_px:
            toward_center       = math.atan2(
                self.arena_center[1] - self.y, self.arena_center[0] - self.x)
            self.angle          = toward_center + random.uniform(-0.4, 0.4)
            self.frames_to_turn = 0
            new_x = self.x + self.speed * math.cos(self.angle)
            new_y = self.y + self.speed * math.sin(self.angle)
            dx2 = new_x - self.arena_center[0]
            dy2 = new_y - self.arena_center[1]
            if math.sqrt(dx2**2 + dy2**2) + margin > self.arena_radius_px:
                new_x, new_y = self.x, self.y

        self.x = new_x
        self.y = new_y

        # --- Dépôt de trace chimique ---
        if chem_map is not None:
            chem_map.deposit(self.x, self.y)

        # --- Mise à jour de l'historique ---
        self.body_history.insert(0, (self.x, self.y))
        if len(self.body_history) > self.length_px:
            self.body_history.pop()

    def _body_width_at(self, t):
        """
        Profil de largeur le long du corps (t ∈ [0,1], 0=tête, 1=queue).

        Args:
            t : position normalisée le long du corps

        Returns:
            largeur en pixels (float)
        """
        w = self.width_px
        if t < 0.12:
            return w * (t / 0.12) * 0.6
        elif t < 0.25:
            return w * (0.6 + 0.4 * ((t - 0.12) / 0.13))
        elif t < 0.6:
            return w * (1.0 - 0.15 * abs((t - 0.4) / 0.35))
        else:
            return w * (1.0 - t) / 0.4 * 0.85

    def draw(self, frame):
        """
        Dessine le planaire sur la frame OpenCV (BGR).

        Args:
            frame : image numpy (H, W, 3) sur laquelle dessiner
        """
        n = len(self.body_history)
        if n < 2:
            return

        # --- Vue de dessous, lumière transmise par le dessus ---
        # Couche 1 : ombre très légère (décalée 1px) — lumière quasi-uniforme
        for i in range(n - 1):
            t  = i / max(n - 1, 1)
            w  = max(1, int(self._body_width_at(t)))
            p1 = (int(self.body_history[i][0])   + 1,
                  int(self.body_history[i][1])   + 1)
            p2 = (int(self.body_history[i+1][0]) + 1,
                  int(self.body_history[i+1][1]) + 1)
            cv2.line(frame, p1, p2, self.shadow_color, w)

        # Couche 2 : corps gris uniforme (teinte de base, sans gradient)
        for i in range(n - 1):
            t  = i / max(n - 1, 1)
            w  = max(1, int(self._body_width_at(t)))
            p1 = (int(self.body_history[i][0]),   int(self.body_history[i][1]))
            p2 = (int(self.body_history[i+1][0]), int(self.body_history[i+1][1]))
            cv2.line(frame, p1, p2, self.body_color, w)

        # Couche 3 : contour sombre net (liseré caractéristique vue de dessous)
        # Dessiné en 2 passes : largeur w+2 (contour) puis w-2 (remplissage corps)
        for i in range(n - 1):
            t  = i / max(n - 1, 1)
            w  = max(1, int(self._body_width_at(t)))
            p1 = (int(self.body_history[i][0]),   int(self.body_history[i][1]))
            p2 = (int(self.body_history[i+1][0]), int(self.body_history[i+1][1]))
            cv2.line(frame, p1, p2, self.body_dark,  w + 2)  # contour
            cv2.line(frame, p1, p2, self.body_color, max(1, w - 1))  # remplissage

        # Couche 4 : centre clair — lumière transmise au travers du corps
        for i in range(n - 1):
            t = i / max(n - 1, 1)
            if 0.10 < t < 0.90:
                w  = max(1, int(self._body_width_at(t) * 0.35))
                p1 = (int(self.body_history[i][0]),   int(self.body_history[i][1]))
                p2 = (int(self.body_history[i+1][0]), int(self.body_history[i+1][1]))
                cv2.line(frame, p1, p2, self.body_light, w)

        head       = self.body_history[0]
        neck       = self.body_history[min(3, n - 1)]
        head_angle = math.atan2(head[1] - neck[1], head[0] - neck[0])
        tip = (int(head[0] + math.cos(head_angle) * self.width_px * 0.5),
               int(head[1] + math.sin(head_angle) * self.width_px * 0.5))
        lw = self.width_px * 0.45
        left_ear  = (int(head[0] + math.cos(head_angle + 1.8) * lw),
                     int(head[1] + math.sin(head_angle + 1.8) * lw))
        right_ear = (int(head[0] + math.cos(head_angle - 1.8) * lw),
                     int(head[1] + math.sin(head_angle - 1.8) * lw))
        pts = np.array([tip, left_ear, right_ear], dtype=np.int32)
        # Contour sombre net puis remplissage gris uniforme
        cv2.fillPoly(frame,   [pts], self.body_dark)
        # Remplissage légèrement rétréci pour laisser le contour visible
        inner_tip = (
            int(head[0] + math.cos(head_angle) * (self.width_px * 0.3)),
            int(head[1] + math.sin(head_angle) * (self.width_px * 0.3))
        )
        ilw = lw * 0.6
        inner_l = (int(head[0] + math.cos(head_angle + 1.8) * ilw),
                   int(head[1] + math.sin(head_angle + 1.8) * ilw))
        inner_r = (int(head[0] + math.cos(head_angle - 1.8) * ilw),
                   int(head[1] + math.sin(head_angle - 1.8) * ilw))
        pts_inner = np.array([inner_tip, inner_l, inner_r], dtype=np.int32)
        cv2.fillPoly(frame, [pts_inner], self.body_color)

        # Yeux (photorécepteurs) : points sombres nets
        eye_d = lw * 0.55
        for side in [1.3, -1.3]:
            ex = int(head[0] + math.cos(head_angle + side) * eye_d * 0.65)
            ey = int(head[1] + math.sin(head_angle + side) * eye_d * 0.65)
            cv2.circle(frame, (ex, ey), max(1, self.width_px // 6), self.body_dark, -1)


# ---------------------------------------------------------------------------
# Rendu de l'arène et des stimuli
# ---------------------------------------------------------------------------

def draw_arena(frame, cfg, width, height, arena_center, arena_radius_px, mm_to_px):
    """
    Dessine l'arène circulaire (boîte de Pétri vue de dessus).

    Args:
        frame           : image numpy à modifier en place
        cfg             : namespace argparse
        width, height   : dimensions en pixels
        arena_center    : tuple (cx, cy)
        arena_radius_px : rayon en pixels
        mm_to_px        : facteur mm → pixels
    """
    bg_color     = (int(cfg.bg_color[0]),     int(cfg.bg_color[1]),     int(cfg.bg_color[2]))
    arena_color  = (int(cfg.arena_color[0]),  int(cfg.arena_color[1]),  int(cfg.arena_color[2]))
    arena_border = (int(cfg.arena_border[0]), int(cfg.arena_border[1]), int(cfg.arena_border[2]))

    frame[:, :, 0] = bg_color[0]
    frame[:, :, 1] = bg_color[1]
    frame[:, :, 2] = bg_color[2]

    cv2.circle(frame, arena_center, arena_radius_px, arena_color, -1)

    for r_off, alpha in [(0, 80), (1, 50), (2, 30)]:
        overlay = frame.copy()
        cv2.circle(overlay, arena_center, arena_radius_px + r_off, (245, 243, 238), 3)
        cv2.addWeighted(overlay, alpha / 255.0, frame, 1 - alpha / 255.0, 0, frame)

    cv2.circle(frame, arena_center, arena_radius_px, arena_border, 2)
    cv2.circle(frame, arena_center, arena_radius_px + 4, (200, 198, 192), 1)

    bar_len = int(mm_to_px)
    bx, by  = width - 40, height - 25
    cv2.line(frame, (bx - bar_len, by), (bx, by), (100, 100, 100), 1)
    cv2.line(frame, (bx - bar_len, by - 3), (bx - bar_len, by + 3), (100, 100, 100), 1)
    cv2.line(frame, (bx, by - 3), (bx, by + 3), (100, 100, 100), 1)
    cv2.putText(frame, "1mm", (bx - bar_len - 5, by - 6),
                cv2.FONT_HERSHEY_SIMPLEX, 0.3, (80, 80, 80), 1, cv2.LINE_AA)
    cv2.putText(frame, "o 16mm", (arena_center[0] - 28, height - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.3, (120, 118, 112), 1, cv2.LINE_AA)


def draw_stimuli(frame, cfg, arena_center, arena_radius_px, mm_to_px,
                 photo_source, chem_map):
    """
    Superpose les indicateurs visuels des stimuli actifs sur la frame.

    Args:
        frame           : image numpy BGR
        cfg             : namespace argparse
        arena_center    : tuple (cx, cy)
        arena_radius_px : rayon de l'arène en pixels
        mm_to_px        : facteur mm → pixels
        photo_source    : tuple (x, y) source lumineuse en pixels
        chem_map        : instance ChemicalMap (ou None)
    """
    # --- Carte chimique (traces de mucus en rouge très transparent) ---
    if chem_map is not None and cfg.chem_repulsion > 0.0:
        heat = (chem_map.map * 80).astype(np.uint8)
        overlay = frame.copy()
        overlay[:, :, 2] = np.clip(overlay[:, :, 2].astype(np.int16) + heat, 0, 255).astype(np.uint8)
        cv2.addWeighted(overlay, 0.3, frame, 0.7, 0, frame)

    # --- Source de nourriture (chimiotactisme) ---
    if cfg.chemo_strength > 0.0:
        cx = int(arena_center[0] + (cfg.chemo_x - 0.5) * 2 * arena_radius_px)
        cy = int(arena_center[1] + (cfg.chemo_y - 0.5) * 2 * arena_radius_px)
        # Halo vert dégradé
        for r, alpha in [(int(cfg.chemo_radius * mm_to_px), 30), (6, 80), (3, 180)]:
            overlay = frame.copy()
            cv2.circle(overlay, (cx, cy), r, (0, 180, 60), -1)
            cv2.addWeighted(overlay, alpha / 255.0, frame, 1 - alpha / 255.0, 0, frame)
        cv2.circle(frame, (cx, cy), 3, (0, 200, 80), -1)

    # --- Source lumineuse (phototactisme) ---
    if cfg.photo_mode != "none" and cfg.photo_strength > 0.0:
        px_src, py_src = int(photo_source[0]), int(photo_source[1])
        if cfg.photo_mode == "radial":
            # Gradient radial depuis le centre : cercle central jaune
            r_zone = int(arena_radius_px * cfg.photo_radius)
            overlay = frame.copy()
            cv2.circle(overlay, arena_center, r_zone, (0, 220, 255), -1)
            cv2.addWeighted(overlay, 0.12, frame, 0.88, 0, frame)
            cv2.circle(frame, arena_center, 5, (0, 200, 255), -1)
        else:
            # Source ponctuelle : halo jaune
            for r, alpha in [(30, 20), (12, 50), (5, 140)]:
                overlay = frame.copy()
                cv2.circle(overlay, (px_src, py_src), r, (0, 220, 255), -1)
                cv2.addWeighted(overlay, alpha / 255.0, frame, 1 - alpha / 255.0, 0, frame)
            cv2.circle(frame, (px_src, py_src), 4, (0, 200, 255), -1)


def compute_photo_source(cfg, frame_idx, arena_center, arena_radius_px):
    """
    Calcule la position de la source lumineuse pour la frame courante.

    Args:
        cfg             : namespace argparse
        frame_idx       : index de la frame courante
        arena_center    : tuple (cx, cy) en pixels
        arena_radius_px : rayon de l'arène en pixels

    Returns:
        tuple (x, y) en pixels
    """
    if cfg.photo_mode == "fixed":
        x = arena_center[0] + (cfg.photo_x - 0.5) * 2 * arena_radius_px
        y = arena_center[1] + (cfg.photo_y - 0.5) * 2 * arena_radius_px
        return (x, y)

    elif cfg.photo_mode == "sine":
        t   = frame_idx * cfg.photo_sine_freq * 2 * math.pi / cfg.fps
        x   = arena_center[0] + math.cos(t) * arena_radius_px * 0.6
        y   = arena_center[1] + math.sin(t * 0.7) * arena_radius_px * 0.6
        return (x, y)

    else:
        # Radial ou none : source au centre (utilisé pour le dessin uniquement)
        return (float(arena_center[0]), float(arena_center[1]))


# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------

def spawn_positions(count, arena_center, arena_radius_px, min_dist):
    """
    Génère `count` positions bien séparées à l'intérieur de l'arène.

    Args:
        count           : nombre de positions à générer
        arena_center    : tuple (cx, cy)
        arena_radius_px : rayon en pixels
        min_dist        : distance minimale entre deux planaires en pixels

    Returns:
        liste de tuples (x, y)
    """
    positions = []
    for _ in range(count):
        placed = False
        for _ in range(1000):
            a = random.uniform(0, 2 * math.pi)
            r = random.uniform(0, arena_radius_px * 0.6)
            x = arena_center[0] + r * math.cos(a)
            y = arena_center[1] + r * math.sin(a)
            if all(math.sqrt((x - px)**2 + (y - py)**2) >= min_dist for px, py in positions):
                positions.append((x, y))
                placed = True
                break
        if not placed:
            positions.append((float(arena_center[0]), float(arena_center[1])))
    return positions


# ---------------------------------------------------------------------------
# Point d'entrée principal
# ---------------------------------------------------------------------------

def main():
    args = parse_args()

    random.seed(args.seed)
    np.random.seed(args.seed)

    # --- Constantes dérivées ---
    WIDTH, HEIGHT   = 500, 500
    TOTAL_FRAMES    = args.fps * args.duration
    MM_TO_PX        = 420 / 16.0                # ~26.25 px/mm
    ARENA_RADIUS_PX = int(8 * MM_TO_PX)
    ARENA_CENTER    = (WIDTH // 2, HEIGHT // 2)

    args.planaire_length_px = int(args.length * MM_TO_PX)
    args.planaire_width_px  = max(4, int(args.width * MM_TO_PX))

    # --- Positions initiales espacées ---
    min_distance = args.planaire_length_px * 1.5
    positions    = spawn_positions(args.count, ARENA_CENTER, ARENA_RADIUS_PX, min_distance)

    # --- Instanciation planaires + trackers ---
    planaires = []
    trackers  = []
    for i, pos in enumerate(positions):
        p = Planaire(i, args, ARENA_CENTER, ARENA_RADIUS_PX, MM_TO_PX,
                     start_x=pos[0], start_y=pos[1])
        t = Tracker(i, MM_TO_PX, args.fps, args.thresh_immobile, args.thresh_mobile,
                    ARENA_CENTER, ARENA_RADIUS_PX)
        planaires.append(p)
        trackers.append(t)

    # --- Carte chimique partagée ---
    chem_map = ChemicalMap(WIDTH, HEIGHT, args.chem_decay) if args.chem_repulsion > 0.0 else None

    # --- Métriques comportementales (une instance par planaire) ---
    behaviour = {
        "thigmotaxis_wall_dist_mm":  1.0,
        "photo_mode":                args.photo_mode,
        "photo_strength":            args.photo_strength,
        "photo_x":                   args.photo_x,
        "photo_y":                   args.photo_y,
        "photo_flee_angle_deg":      90.0,
        "chemo_strength":            args.chemo_strength,
        "chemo_x":                   args.chemo_x,
        "chemo_y":                   args.chemo_y,
        "chemo_radius_mm":           args.chemo_radius,
        "chemo_approach_angle_deg":  90.0,
        "avoid_radius_mm":           args.avoid_radius,
        "aggreg_radius_mm":          args.aggreg_radius,
    }
    metrics_list = []
    if HAS_METRICS:
        for _ in planaires:
            metrics_list.append(EthoVisionMetrics(
                px_per_mm       = MM_TO_PX,
                fps             = args.fps,
                thresh_immobile = args.thresh_immobile,
                thresh_mobile   = args.thresh_mobile,
                behaviour       = behaviour,
            ))

    # --- Arène de base ---
    arena_base = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    draw_arena(arena_base, args, WIDTH, HEIGHT, ARENA_CENTER, ARENA_RADIUS_PX, MM_TO_PX)

    # --- Encodeur vidéo ---
    output_path = args.output
    if not output_path.endswith(".mp4"):
        output_path += ".mp4"
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out    = cv2.VideoWriter(output_path, fourcc, args.fps, (WIDTH, HEIGHT))

    print(f"Simulation : {args.count} planaire(s), {TOTAL_FRAMES} frames ({args.duration}s à {args.fps} fps)")
    print(f"Morphologie     : {args.length}mm × {args.width}mm")
    print(f"Thigmotactisme  : {args.thigmotaxis}")
    print(f"Phototactisme   : mode={args.photo_mode}  force={args.photo_strength}")
    print(f"Chimiotactisme  : force={args.chemo_strength}  pos=({args.chemo_x:.2f},{args.chemo_y:.2f})")
    print(f"Évitement       : force={args.avoid_strength}  rayon={args.avoid_radius}mm")
    print(f"Agrégation      : force={args.aggreg_strength}  rayon={args.aggreg_radius}mm")
    print(f"Répulsion chim. : force={args.chem_repulsion}  decay={args.chem_decay}")
    print(f"Sortie vidéo    : {output_path}")

    # --- Boucle de rendu ---
    for frame_idx in range(TOTAL_FRAMES):
        frame = arena_base.copy()

        # Calcul de la position de la source lumineuse pour cette frame
        photo_source = compute_photo_source(args, frame_idx, ARENA_CENTER, ARENA_RADIUS_PX)

        # Positions courantes de tous les planaires (pour interactions inter-individus)
        all_positions = [(p.x, p.y) for p in planaires]

        # Mise à jour cinématique + tracking
        for i, (p, t) in enumerate(zip(planaires, trackers)):
            others = [pos for j, pos in enumerate(all_positions) if j != i]
            p.update(frame_idx, others, chem_map, photo_source)
            t.update(frame_idx, p.x, p.y)

        # Métriques comportementales frame par frame
        if HAS_METRICS and metrics_list:
            for i, (p, m) in enumerate(zip(planaires, metrics_list)):
                others_mm = [
                    ((q.x - ARENA_CENTER[0]) / MM_TO_PX,
                     (q.y - ARENA_CENTER[1]) / MM_TO_PX)
                    for j, q in enumerate(planaires) if j != i
                ]
                chem_level = 0.0
                if chem_map is not None:
                    _, chem_level = chem_map.gradient_at(p.x, p.y)
                raw_sim = {
                    'detected':   True,
                    'timestamp':  frame_idx / args.fps,
                    'cx':         int(p.x),
                    'cy':         int(p.y),
                    'speed_px_s': p.speed * args.fps,
                    'area_px':    p.length_px * p.width_px,
                    'axial_pos':  (p.y - ARENA_CENTER[1]) / max(ARENA_RADIUS_PX, 1),
                    'axial_speed': 0.0,
                }
                m.update(
                    raw_sim,
                    well_radius_mm  = 8.0,
                    arena_center_px = ARENA_CENTER,
                    photo_source_px = (int(photo_source[0]), int(photo_source[1]))
                                      if args.photo_mode != 'none' else None,
                    others_pos_mm   = others_mm,
                    chem_level      = float(chem_level),
                )

        # Décroissance de la carte chimique
        if chem_map is not None:
            chem_map.step()

        # Dessin des stimuli puis des planaires
        draw_stimuli(frame, args, ARENA_CENTER, ARENA_RADIUS_PX, MM_TO_PX,
                     photo_source, chem_map)
        for p in planaires:
            p.draw(frame)

        # Timecode et compteur
        t_sec = frame_idx / args.fps
        cv2.putText(frame, f"{t_sec:.1f}s", (8, 16),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, (140, 138, 132), 1, cv2.LINE_AA)
        cv2.putText(frame, f"n={args.count}", (8, HEIGHT - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.3, (140, 138, 132), 1, cv2.LINE_AA)

        out.write(frame)
        if frame_idx % args.fps == 0:
            print(f"  {t_sec:.0f}s / {args.duration}s")

    out.release()
    print(f"Terminé → {output_path}")

    # --- Export CSV ---
    if not args.no_csv:
        output_stem = os.path.splitext(os.path.basename(output_path))[0]
        print(f"Export CSV → {args.csv_dir}/")
        for t in trackers:
            t.write_csv(args.csv_dir, output_stem)
            s = t.summary()
            print(f"    [{t.planaire_id:02d}] dist={s['movedCenter_pointTotal_mm']:.2f}mm  "
                  f"v={s['velocity_mean_mm_s']:.2f}mm/s  "
                  f"imm={s['mobility_immobile_duration_s']:.1f}s  "
                  f"mob={s['mobility_mobile_duration_s']:.1f}s  "
                  f"hmob={s['mobility_highly_mobile_duration_s']:.1f}s  "
                  f"paroi={s['thigmotaxis_pct_time_near_wall']:.1f}%")

    # --- Export CSV métriques comportementales ---
    if HAS_METRICS and metrics_list and not args.no_csv:
        output_stem = os.path.splitext(os.path.basename(output_path))[0]
        os.makedirs(args.csv_dir, exist_ok=True)
        print(f"Export CSV comportemental → {args.csv_dir}/")
        for i, m in enumerate(metrics_list):
            s = m.summary()
            path = os.path.join(
                args.csv_dir, f"{output_stem}_planaire_{i:02d}_behaviour_summary.csv"
            )
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=list(s.keys()))
                writer.writeheader()
                writer.writerow(s)
            print(f"    [{i:02d}] photo={s['photo_pct_time_fleeing']:.1f}%  "
                  f"chemo_zone={s['chemo_pct_time_in_zone']:.1f}%  "
                  f"evit={s['social_pct_time_avoiding']:.1f}%  "
                  f"contacts={s['social_contact_events']}  → {path}")


if __name__ == "__main__":
    main()
