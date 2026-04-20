'''
Created on 17 avr. 2026

@author: denis
'''
# modules/tube_aligner.py

import cv2
import logging
import numpy as np

logger = logging.getLogger(__name__)


class TubeAligner:
    """
    Détecte le cercle du tube à essai dans une frame (vue par dessous,
    éclairage par dessus → cercle clair sur fond sombre).
    Calcule le décalage entre le centre du tube et le centre de l'image.
    Décide d'une correction GRBL (grand écart) ou d'un recadrage (petit écart).
    """

    # Seuil en pixels : au-delà → correction GRBL, en-dessous → recadrage
    GRBL_THRESHOLD_PX  = 20
    # Tolérance : en-dessous → pas de correction nécessaire
    DEAD_ZONE_PX       = 5

    def __init__(
        self,
        px_per_mm: float = 10.0,        # facteur d'échelle calibration (px/mm)
        grbl_threshold_px: int = 20,
        dead_zone_px: int = 5,
        debug: bool  = False,   # ← activable depuis la vue
    ):
        self.px_per_mm         = px_per_mm
        self.grbl_threshold_px = grbl_threshold_px
        self.dead_zone_px      = dead_zone_px

    def detect_tube(self, frame: np.ndarray) -> dict:
        """
        Détecte le cercle du tube et calcule le décalage par rapport au centre image.

        :param frame: Frame BGR (numpy array)
        :return:      dict avec cercle détecté, décalage px et mm, action recommandée
        """
        h, w = frame.shape[:2]
        cx_img = w // 2
        cy_img = h // 2

        result = {
            "detected"      : False,
            "tube_cx"       : None,
            "tube_cy"       : None,
            "tube_radius"   : None,
            "offset_x_px"   : None,
            "offset_y_px"   : None,
            "offset_x_mm"   : None,
            "offset_y_mm"   : None,
            "action"        : "none",   # "none" | "crop" | "grbl"
            "grbl_gcode"    : None,
            "frame_annotated": None,
        }

        # Prétraitement : niveaux de gris + flou
        gray    = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        #blurred = cv2.GaussianBlur(gray, (9, 9), 2)
        blurred = cv2.GaussianBlur(gray, (15, 15), 3)
        
        # param1 : seuil Canny haut, param2 : seuil accumulation (plus bas = plus permissif)
        min_radius = int(min(w, h) * 0.26)    # ~260px sur 1000px
        max_radius = int(min(w, h) * 0.36)    # ~360px sur 1000px — bord intérieur du verre

        circles = cv2.HoughCircles(
            blurred,
            cv2.HOUGH_GRADIENT,
            dp          = 1.2,
            minDist     = min(w, h) // 2,    # un seul tube attendu
            param1      = 50,
            param2      = 30,
            minRadius   = min_radius,
            maxRadius   = max_radius,
        )

        if circles is None:
            logger.warning("TubeAligner: aucun cercle détecté")
            result["frame_annotated"] = self._annotate(frame.copy(), cx_img, cy_img, None)
            return result

        circles = np.round(circles[0, :]).astype(int)

        # Prend le cercle le plus proche du centre image
        best = min(
            circles,
            key=lambda c: np.sqrt((c[0] - cx_img)**2 + (c[1] - cy_img)**2)
        )
        tx, ty, tr = int(best[0]), int(best[1]), int(best[2])

        # Décalage : positif = tube à droite/bas du centre image
        offset_x_px = tx - cx_img
        offset_y_px = ty - cy_img
        offset_x_mm = offset_x_px / self.px_per_mm
        offset_y_mm = offset_y_px / self.px_per_mm

        dist_px = np.sqrt(offset_x_px**2 + offset_y_px**2)

        # Décision d'action
        if dist_px <= self.dead_zone_px:
            action     = "none"
            grbl_gcode = None
        elif dist_px <= self.grbl_threshold_px:
            action     = "crop"
            grbl_gcode = None
        else:
            action = "grbl"
            # G91 = coordonnées relatives, G0 = déplacement rapide
            # Inversion du signe : si tube est à droite (+X image),
            # la CNC doit reculer (-X GRBL) pour recentrer
            #cmd = f"G53 G1 X{x:.2f} Y{y:.2f} F{feed}"
            
            grbl_gcode = (
                f"G91\n"
                f"G1 X{-offset_x_mm:.3f} Y{-offset_y_mm:.3f}\n"
                f"G90"
            )
            logger.info(
                "TubeAligner: décalage %.1fpx (%.2fmm, %.2fmm) → GRBL: %s",
                dist_px, offset_x_mm, offset_y_mm, grbl_gcode.replace('\n', ' | ')
            )

        result.update({
            "detected"       : True,
            "tube_cx"        : tx,
            "tube_cy"        : ty,
            "tube_radius"    : tr,
            "offset_x_px"   : offset_x_px,
            "offset_y_px"   : offset_y_px,
            "offset_x_mm"   : round(offset_x_mm, 3),
            "offset_y_mm"   : round(offset_y_mm, 3),
            "action"        : action,
            "grbl_gcode"    : None,
            "frame_annotated": self._annotate(
                frame.copy(), cx_img, cy_img, (tx, ty, tr), offset_x_px, offset_y_px
            ),
        })

        return result

    def crop_to_tube(self, frame: np.ndarray, detection: dict) -> np.ndarray:
        """
        Recadrage logiciel : recentre l'image sur le tube détecté.
        Utilisé quand action == "crop".
        """
        if not detection["detected"]:
            return frame

        tx = detection["tube_cx"]
        ty = detection["tube_cy"]
        tr = detection["tube_radius"]
        h, w = frame.shape[:2]

        # Fenêtre carrée autour du centre du tube
        half = tr
        x1 = max(tx - half, 0)
        y1 = max(ty - half, 0)
        x2 = min(tx + half, w)
        y2 = min(ty + half, h)

        cropped = frame[y1:y2, x1:x2]

        # Redimensionne à la taille originale pour ne pas changer le pipeline
        return cv2.resize(cropped, (w, h), interpolation=cv2.INTER_LINEAR)

    def _annotate(
        self,
        frame: np.ndarray,
        cx_img: int,
        cy_img: int,
        circle: tuple | None,
        offset_x: int = 0,
        offset_y: int = 0,
    ) -> np.ndarray:
        """
        Dessine le cercle détecté, le centre image et le vecteur de décalage.
        """
        # Croix centre image
        cv2.drawMarker(
            frame, (cx_img, cy_img),
            (0, 255, 0), cv2.MARKER_CROSS, 20, 1, cv2.LINE_AA
        )

        if circle is None:
            cv2.putText(frame, "Tube non detecte", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 1, cv2.LINE_AA)
            return frame

        tx, ty, tr = circle

        # Cercle du tube en cyan
        cv2.circle(frame, (tx, ty), tr, (255, 255, 0), 2, cv2.LINE_AA)

        # Centre du tube en rouge
        cv2.circle(frame, (tx, ty), 4, (0, 0, 255), -1, cv2.LINE_AA)

        # Vecteur décalage (centre image → centre tube)
        if abs(offset_x) > 2 or abs(offset_y) > 2:
            cv2.arrowedLine(
                frame,
                (cx_img, cy_img),
                (tx, ty),
                (0, 100, 255), 2, cv2.LINE_AA, tipLength=0.2
            )

        # Texte décalage
        dist = np.sqrt(offset_x**2 + offset_y**2)
        cv2.putText(
            frame,
            f"dx={offset_x:+d}px  dy={offset_y:+d}px  dist={dist:.1f}px",
            (10, 28),
            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            f"r={tr}px",
            (10, 48),
            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1, cv2.LINE_AA,
        )

        return frame
    
    