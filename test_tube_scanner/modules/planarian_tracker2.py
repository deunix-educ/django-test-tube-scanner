# modules/planarian_tracker.py
'''
Created on 16 avr. 2026

@author: denis
'''

import cv2
import logging
import numpy as np

logger = logging.getLogger(__name__)


class PlanarianTracker:
    """
    Détection et suivi d'une planaire dans un tube.
    Instancié une fois par caméra active, réutilisé frame à frame.
    Utilise la soustraction de fond MOG2 — léger sur Raspberry Pi 4.
    """

    def __init__(self, tube_axis: str = "vertical", min_area_px: int = 20):
        # Axe du tube : "vertical" (cy) ou "horizontal" (cx)
        self.tube_axis   = tube_axis
        self.min_area_px = min_area_px

        # Etat inter-frame
        self._prev_cx  = None
        self._prev_cy  = None
        self._prev_ts  = None

        # Soustracteur de fond adaptatif MOG2
        self._bg_sub = cv2.createBackgroundSubtractorMOG2(
            history      = 50,
            varThreshold = 25,
            detectShadows= False,
        )

    def reset(self):
        """
        Réinitialise l'état inter-frame — appeler lors du changement de puits.
        """
        self._prev_cx = None
        self._prev_cy = None
        self._prev_ts = None
        # Réinitialise le fond appris
        self._bg_sub  = cv2.createBackgroundSubtractorMOG2(
            history      = 50,
            varThreshold = 25,
            detectShadows= False,
        )
        
    def process(self, frame: np.ndarray, ts: float) -> tuple[np.ndarray, dict]:
        """
        Analyse une frame et dessine les contours détectés directement sur l'image.
        Retourne (frame_annotée, métriques).
        
            Contours fins    Vert (0,255,0)    Tous les contours valides détectés
            Contour épais    Cyan (255,255,0)    Planaire principale (plus grand contour)
            Croix + cercle    Rouge (0,0,255)    Centre de masse exact
            Texte    Blanc    Vitesse px/s + position axiale normalisée
        """
        result       = self._empty_result(ts)
        frame_out    = frame.copy()    # copie pour ne pas modifier l'original
    
        gray    = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        fg_mask = self._bg_sub.apply(gray)
    
        kernel  = np.ones((3, 3), np.uint8)
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN,  kernel)
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, kernel)
    
        contours, _ = cv2.findContours(
            fg_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
    
        if not contours:
            self._update_prev(None, None, ts)
            return frame_out, result
    
        # Filtre les contours significatifs
        valid_contours = [c for c in contours if cv2.contourArea(c) >= self.min_area_px]
    
        if not valid_contours:
            self._update_prev(None, None, ts)
            return frame_out, result
    
        # Dessine tous les contours valides en vert fin
        cv2.drawContours(frame_out, valid_contours, -1, (0, 255, 0), 1)
    
        # Plus grand contour = planaire principale
        largest = max(valid_contours, key=cv2.contourArea)
        area    = cv2.contourArea(largest)
    
        # Contour principal en cyan plus épais
        cv2.drawContours(frame_out, [largest], -1, (255, 255, 0), 2)
    
        M = cv2.moments(largest)
        if M["m00"] == 0:
            return frame_out, result
    
        cx = int(M["m10"] / M["m00"])
        cy = int(M["m01"] / M["m00"])
        h, w = frame.shape[:2]
    
        axial_pos   = (cy / h) if self.tube_axis == "vertical" else (cx / w)
        speed_px_s  = None
        axial_speed = None
    
        if self._prev_cx is not None and self._prev_ts is not None:
            dt = ts - self._prev_ts
            if dt > 0:
                dx          = cx - self._prev_cx
                dy          = cy - self._prev_cy
                speed_px_s  = float(np.sqrt(dx**2 + dy**2) / dt)
                axial_speed = float((dy / dt) if self.tube_axis == "vertical" else (dx / dt))
    
        # Croix sur le centre de masse
        cross_size = 8
        cv2.line(frame_out, (cx - cross_size, cy), (cx + cross_size, cy), (0, 0, 255), 1)
        cv2.line(frame_out, (cx, cy - cross_size), (cx, cy + cross_size), (0, 0, 255), 1)
    
        # Cercle centré sur la planaire
        cv2.circle(frame_out, (cx, cy), 12, (0, 0, 255), 1)
    
        # Texte vitesse + position axiale
        label = f"v={speed_px_s:.1f}px/s  ax={axial_pos:.2f}" if speed_px_s is not None else f"ax={axial_pos:.2f}"
        cv2.putText(
            frame_out, label,
            (max(cx - 60, 0), max(cy - 18, 12)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1, cv2.LINE_AA,
        )
    
        result.update({
            "detected"    : True,
            "cx"          : cx,
            "cy"          : cy,
            "area_px"     : int(area),
            "speed_px_s"  : round(speed_px_s,  3) if speed_px_s  is not None else 0.0,
            "axial_speed" : round(axial_speed,  3) if axial_speed is not None else 0.0,
            "axial_pos"   : round(axial_pos,    4),
        })
    
        self._update_prev(cx, cy, ts)
        return frame_out, result              
        
        
    # ------------------------------------------------------------------ #
    def _empty_result(self, ts: float) -> dict:
        return {
            "timestamp"  : ts,
            "detected"   : False,
            "cx"         : 0,
            "cy"         : 0,
            "area_px"    : 0,
            "speed_px_s" : 0.0,
            "axial_speed": 0.0,
            "axial_pos"  : 0.0,
        }

    def _update_prev(self, cx, cy, ts):
        self._prev_cx = cx
        self._prev_cy = cy
        self._prev_ts = ts
  
        