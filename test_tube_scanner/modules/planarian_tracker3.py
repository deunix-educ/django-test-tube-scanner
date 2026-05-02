"""
modules/planarian_tracker.py

Détection et suivi multi-individus de planaires dans un tube.
Supporte de 1 à MAX_PLANARIANS planaires par tube.

Etat inter-frame indépendant par individu : position, timestamp, compteur de perte (lost), flag active. 
Quand un individu n'est pas détecté pendant MAX_LOST_FRAMES (5) frames consécutives, il est marqué perdu et son slot se libère.

Algorithme hongrois (scipy.optimize.linear_sum_assignment) dans _hungarian_assign() 
  — construit une matrice de coût distance euclidienne entre les slots actifs et les nouvelles détections, puis trouve l'association de coût minimal. 
Une association est rejetée si la distance dépasse MAX_ASSOC_DIST_PX (80px) 
  — évite les sauts aberrants entre planaires proches.


Stratégie :
    - Soustraction de fond MOG2 (léger sur Raspberry Pi 4)
    - Détection de tous les contours valides (surface >= min_area_px)
    - Association frame-à-frame par distance euclidienne minimale
      via algorithme hongrois (scipy.optimize.linear_sum_assignment)
    - Un état inter-frame indépendant par individu (PlanarianState)
    - Retourne une liste de résultats, un par individu suivi: champ planarian_id (index 0-based).

Created on 25 avr. 2026
@author: denis
"""

import cv2
import logging
import numpy as np
logger = logging.getLogger(__name__)

from scipy.optimize import linear_sum_assignment    # @UnresolvedImport

# Nombre maximum de planaires suivis simultanément par tube
MAX_PLANARIANS = 10

# Distance maximale en pixels entre deux positions consécutives
# pour qu'une association soit acceptée (évite les sauts aberrants)
MAX_ASSOC_DIST_PX = 80

# Couleurs d'annotation par individu (BGR)
# Cycle automatique si plus de planaires que de couleurs
INDIVIDUAL_COLORS = [
    (255, 255,   0),  # cyan
    (  0, 165, 255),  # orange
    (255,   0, 255),  # magenta
    (  0, 255, 255),  # jaune
    (128,   0, 255),  # violet
    (  0, 255, 128),  # vert clair
    (255, 128,   0),  # bleu clair
    (  0, 128, 255),  # orange foncé
    (128, 255,   0),  # vert-jaune
    (255,   0, 128),  # rose
]



# Couleur du contour principal (individu le plus grand)
COLOR_LARGEST  = (255, 255,   0)   # cyan
COLOR_OTHER    = (  0, 255,   0)   # vert
COLOR_CENTER   = (  0,   0, 255)   # rouge


# ---------------------------------------------------------------------------
# État inter-frame d'un individu
# ---------------------------------------------------------------------------

class PlanarianState:
    """
    Mémorise la position et le timestamp de la dernière détection
    pour un planaire individuel.

    Un PlanarianState par slot (index 0 à max_planarians-1).
    Quand un slot n'est pas associé à un contour sur plusieurs frames
    consécutives, il est marqué comme perdu (lost).
    """

    # Nombre de frames sans détection avant de considérer l'individu perdu
    MAX_LOST_FRAMES = 5

    def __init__(self, idx: int):
        """
        Args:
            idx : index de l'individu (0-based)
        """
        self.idx        = idx
        self.cx         = None
        self.cy         = None
        self.ts         = None
        self.lost       = 0     # compteur de frames sans détection
        self.active     = False # vrai si l'individu a été détecté au moins une fois

    def update(self, cx: int, cy: int, ts: float):
        """
        Met à jour la position suite à une association réussie.

        Args:
            cx, cy : position du centre de masse en pixels
            ts     : timestamp de la frame
        """
        self.cx     = cx
        self.cy     = cy
        self.ts     = ts
        self.lost   = 0
        self.active = True

    def mark_lost(self):
        """Incrémente le compteur de perte — appelé quand aucun contour n'est associé."""
        self.lost += 1

    @property
    def is_lost(self) -> bool:
        """Retourne True si l'individu est considéré perdu (trop de frames sans détection)."""
        return self.lost >= self.MAX_LOST_FRAMES

    def compute_speed(self, cx: int, cy: int, ts: float, tube_axis: str) -> tuple:
        """
        Calcule la vitesse instantanée depuis la position précédente.

        Args:
            cx, cy    : position courante en pixels
            ts        : timestamp courant
            tube_axis : "vertical" ou "horizontal"

        Returns:
            tuple (speed_px_s, axial_speed) ou (0.0, 0.0) si état vide
        """
        if self.cx is None or self.ts is None:
            return 0.0, 0.0

        dt = ts - self.ts
        if dt <= 0:
            return 0.0, 0.0

        dx          = cx - self.cx
        dy          = cy - self.cy
        speed_px_s  = float(np.sqrt(dx**2 + dy**2) / dt)
        axial_speed = float((dy / dt) if tube_axis == "vertical" else (dx / dt))

        return speed_px_s, axial_speed

    def reset(self):
        """Réinitialise l'état de cet individu."""
        self.cx     = None
        self.cy     = None
        self.ts     = None
        self.lost   = 0
        self.active = False


# ---------------------------------------------------------------------------
# Tracker multi-individus
# ---------------------------------------------------------------------------

class PlanarianTracker:
    """
    Détection et suivi multi-individus de planaires dans un tube.

    Instancié une fois par caméra active, réutilisé frame à frame.
    Utilise la soustraction de fond MOG2 — léger sur Raspberry Pi 4.
    Association frame-à-frame par algorithme hongrois (distance euclidienne).

    Usage :
        tracker = PlanarianTracker(tube_axis="vertical", max_planarians=3)
        while capturing:
            frame_out, results = tracker.process(frame, ts)
            # results : liste de dicts, un par individu détecté
            for r in results:
                metrics.update(r, planarian_id=r["planarian_id"])
    """

    def __init__(
        self,
        tube_axis:      str = "vertical",
        min_area_px:    int = 20,
        max_planarians: int = 1,
    ):
        """
        Args:
            tube_axis      : axe principal du tube — "vertical" (cy) ou "horizontal" (cx)
            min_area_px    : surface minimale d'un contour pour être considéré valide (px²)
            max_planarians : nombre maximum de planaires à suivre simultanément (1-10)
        """
        self.tube_axis      = tube_axis
        self.min_area_px    = min_area_px
        self.max_planarians = max(1, min(max_planarians, MAX_PLANARIANS))

        # Un état inter-frame par slot individu
        self._states = [PlanarianState(i) for i in range(self.max_planarians)]

        # Soustracteur de fond adaptatif MOG2
        self._bg_sub = self._make_bg_sub()

    @staticmethod
    def _make_bg_sub():
        """Crée et retourne un soustracteur de fond MOG2."""
        return cv2.createBackgroundSubtractorMOG2(
            history      = 50,
            varThreshold = 25,
            detectShadows= False,
        )

    def reset(self):
        """
        Réinitialise l'état inter-frame complet.
        À appeler lors du changement de puits.
        """
        for s in self._states:
            s.reset()
        self._bg_sub = self._make_bg_sub()

    # ------------------------------------------------------------------ #
    # Interface principale
    # ------------------------------------------------------------------ #

    def process(self, frame: np.ndarray, ts: float) -> tuple:
        """
        Analyse une frame, associe les contours aux individus connus,
        dessine les annotations et retourne les métriques.

        Args:
            frame : image BGR (numpy array)
            ts    : timestamp de la frame (float, secondes epoch)

        Returns:
            tuple (frame_annotée, results)

            frame_annotée : copie BGR avec contours, croix et textes
            results       : liste de dicts — un dict par planaire actif détecté.
                            Chaque dict contient :
                                planarian_id  int     index de l'individu (0-based)
                                detected      bool    True si détecté cette frame
                                cx, cy        int     centre de masse en pixels
                                area_px       int     surface du contour (px²)
                                speed_px_s    float   vitesse totale (px/s)
                                axial_speed   float   vitesse axiale (px/s)
                                axial_pos     float   position axiale normalisée (0-1)
                                timestamp     float   ts de la frame
        """
        frame_out = frame.copy()
        h, w      = frame.shape[:2]

        # --- Extraction du premier plan ---
        gray    = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        fg_mask = self._bg_sub.apply(gray)

        kernel  = np.ones((3, 3), np.uint8)
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN,  kernel)
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(
            fg_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        # Filtrage des contours significatifs, triés par surface décroissante
        valid = sorted(
            [c for c in contours if cv2.contourArea(c) >= self.min_area_px],
            key=cv2.contourArea,
            reverse=True,
        )

        # Limiter au nombre maximum de planaires attendus
        valid = valid[:self.max_planarians]

        # --- Calcul des centres de masse des contours détectés ---
        detections = []   # liste de (cx, cy, area, contour)
        for c in valid:
            M = cv2.moments(c)
            if M["m00"] == 0:
                continue
            cx   = int(M["m10"] / M["m00"])
            cy   = int(M["m01"] / M["m00"])
            area = cv2.contourArea(c)
            detections.append((cx, cy, int(area), c))

        # --- Association hongroise détections → slots individus ---
        assignments = self._hungarian_assign(detections)

        # --- Mise à jour des états et construction des résultats ---
        results = []

        for slot_idx, det_idx in assignments.items():
            state = self._states[slot_idx]

            if det_idx is None:
                # Aucune détection associée à ce slot
                state.mark_lost()
                if state.active and not state.is_lost:
                    # L'individu était suivi : on retourne un résultat "perdu"
                    results.append(self._lost_result(slot_idx, ts))
                continue

            cx, cy, area, contour = detections[det_idx]

            # Calcul de la vitesse depuis la position précédente
            speed_px_s, axial_speed = state.compute_speed(cx, cy, ts, self.tube_axis)

            axial_pos = (cy / h) if self.tube_axis == "vertical" else (cx / w)

            # Mise à jour de l'état
            state.update(cx, cy, ts)

            # Annotation visuelle
            color = INDIVIDUAL_COLORS[slot_idx % len(INDIVIDUAL_COLORS)]
            cv2.drawContours(frame_out, [contour], -1, color, 2)
            self._draw_center(frame_out, cx, cy, slot_idx, speed_px_s, axial_pos, color)

            results.append({
                "planarian_id": slot_idx,
                "detected":     True,
                "cx":           cx,
                "cy":           cy,
                "area_px":      area,
                "speed_px_s":   round(speed_px_s,  3),
                "axial_speed":  round(axial_speed,  3),
                "axial_pos":    round(axial_pos,    4),
                "timestamp":    ts,
            })

        # Marquer les slots non présents dans les assignments comme perdus
        assigned_slots = set(assignments.keys())
        for state in self._states:
            if state.idx not in assigned_slots:
                state.mark_lost()

        
        return frame_out, results

    # ------------------------------------------------------------------ #
    # Association hongroise
    # ------------------------------------------------------------------ #

    def _hungarian_assign(self, detections: list) -> dict:
        """
        Associe les détections courantes aux slots individus connus
        via l'algorithme hongrois (coût = distance euclidienne).

        Contrainte : une association n'est acceptée que si la distance
        est inférieure à MAX_ASSOC_DIST_PX (évite les sauts aberrants).

        Args:
            detections : liste de (cx, cy, area, contour)

        Returns:
            dict {slot_idx: det_idx | None}
            det_idx = None si aucune détection assignée à ce slot
        """
        n_slots = self.max_planarians
        n_dets  = len(detections)

        if n_dets == 0:
            # Aucune détection : tous les slots sont "perdus"
            return {i: None for i in range(n_slots)}

        # Slots actifs (déjà vus au moins une fois et non perdus)
        active_slots = [s for s in self._states if s.active and not s.is_lost]

        if not active_slots:
            # Première frame ou tous perdus : attribution séquentielle simple
            assignment = {}
            for i in range(n_slots):
                assignment[i] = i if i < n_dets else None
            return assignment

        # --- Construction de la matrice de coût (distance euclidienne) ---
        cost = np.full((len(active_slots), n_dets), fill_value=1e6)

        for si, state in enumerate(active_slots):
            for di, (cx, cy, _, _) in enumerate(detections):
                dist = np.sqrt((cx - state.cx)**2 + (cy - state.cy)**2)
                cost[si, di] = dist

        # --- Algorithme hongrois ---
        row_ind, col_ind = linear_sum_assignment(cost)

        # Construire le dict d'association
        assignment = {i: None for i in range(n_slots)}

        assigned_dets = set()
        for ri, ci in zip(row_ind, col_ind):
            if cost[ri, ci] <= MAX_ASSOC_DIST_PX:
                slot_idx = active_slots[ri].idx
                assignment[slot_idx] = ci
                assigned_dets.add(ci)

        # --- Nouvelles détections non assignées → slots inactifs libres ---
        free_slots = [s for s in self._states if not s.active or s.is_lost]
        new_dets   = [di for di in range(n_dets) if di not in assigned_dets]

        for state, det_idx in zip(free_slots, new_dets):
            assignment[state.idx] = det_idx

        return assignment

    # ------------------------------------------------------------------ #
    # Dessin des annotations
    # ------------------------------------------------------------------ #

    def _draw_center(
        self,
        frame:      np.ndarray,
        cx:         int,
        cy:         int,
        idx:        int,
        speed_px_s: float,
        axial_pos:  float,
        color:      tuple,
    ):
        """
        Dessine la croix, le cercle et le label de vitesse/position
        pour un individu.

        Args:
            frame      : image à annoter (en place)
            cx, cy     : centre de masse en pixels
            idx        : index de l'individu
            speed_px_s : vitesse en px/s
            axial_pos  : position axiale normalisée
            color      : couleur BGR de l'individu
        """
        cross = 8
        cv2.line(frame, (cx - cross, cy), (cx + cross, cy), COLOR_CENTER, 1)
        cv2.line(frame, (cx, cy - cross), (cx, cy + cross), COLOR_CENTER, 1)
        cv2.circle(frame, (cx, cy), 12, color, 1)

        # Badge numéro individu
        cv2.circle(frame, (cx + 14, cy - 14), 8, color, -1)
        cv2.putText(
            frame, str(idx),
            (cx + 10, cy - 10),
            cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 0), 1, cv2.LINE_AA,
        )

        # Texte vitesse + position axiale
        label = (
            f"#{idx} v={speed_px_s:.1f}px/s ax={axial_pos:.2f}"
            if speed_px_s > 0
            else f"#{idx} ax={axial_pos:.2f}"
        )
        cv2.putText(
            frame, label,
            (max(cx - 60, 0), max(cy - 22, 12)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 255), 1, cv2.LINE_AA,
        )

    # ------------------------------------------------------------------ #
    # Résultats vides / perdus
    # ------------------------------------------------------------------ #

    def _lost_result(self, planarian_id: int, ts: float) -> dict:
        """
        Retourne un résultat pour un individu temporairement non détecté.

        Args:
            planarian_id : index de l'individu
            ts           : timestamp de la frame courante

        Returns:
            dict avec detected=False et les dernières coordonnées connues
        """
        state = self._states[planarian_id]
        return {
            "planarian_id": planarian_id,
            "detected":     False,
            "cx":           state.cx or 0,
            "cy":           state.cy or 0,
            "area_px":      0,
            "speed_px_s":   0.0,
            "axial_speed":  0.0,
            "axial_pos":    0.0,
            "timestamp":    ts,
        }
