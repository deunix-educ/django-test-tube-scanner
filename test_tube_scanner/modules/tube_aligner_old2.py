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

    GRBL_THRESHOLD_PX = 20
    DEAD_ZONE_PX      = 5

    def __init__(
        self,
        px_per_mm         : float = 10.0,
        grbl_threshold_px : int   = 20,
        dead_zone_px      : int   = 5,
        debug             : bool  = False,   # ← activable depuis la vue
    ):
        self.px_per_mm         = px_per_mm
        self.grbl_threshold_px = grbl_threshold_px
        self.dead_zone_px      = dead_zone_px
        self.debug             = debug

        # Etat calibration
        self._calib_step     = 0            # 0=idle 1=point A enregistré
        self._calib_pos_A_px = None         # centre tube point A en px
        self._calib_mpos_A   = None         # position CNC point A en mm

    # ------------------------------------------------------------------ #
    # Détection principale
    # ------------------------------------------------------------------ #

    def detect_tube(self, frame: np.ndarray) -> dict:
        h, w    = frame.shape[:2]
        cx_img  = w // 2
        cy_img  = h // 2

        result = {
            "detected"       : False,
            "tube_cx"        : None,
            "tube_cy"        : None,
            "tube_radius"    : None,
            "offset_x_px"   : 0,
            "offset_y_px"   : 0,
            "offset_x_mm"   : 0.0,
            "offset_y_mm"   : 0.0,
            "action"         : "none",
            "frame_annotated": None,
        }

        gray    = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (15, 15), 3)

        circles = cv2.HoughCircles(
            blurred,
            cv2.HOUGH_GRADIENT,
            dp        = 1.2,
            minDist   = min(w, h) // 2,
            param1    = 50,
            param2    = 30,
            minRadius = int(min(w, h) * 0.26),
            maxRadius = int(min(w, h) * 0.36),
        )

        frame_out = frame.copy()

        if circles is None:
            logger.warning("TubeAligner: aucun cercle détecté")
            if self.debug:
                frame_out = self._draw_debug_no_detection(frame_out, cx_img, cy_img)
            result["frame_annotated"] = frame_out
            return result

        circles = np.round(circles[0, :]).astype(int)
        best    = min(circles, key=lambda c: np.sqrt((c[0]-cx_img)**2 + (c[1]-cy_img)**2))
        tx, ty, tr = int(best[0]), int(best[1]), int(best[2])

        offset_x_px = tx - cx_img
        offset_y_px = ty - cy_img
        offset_x_mm = offset_x_px / self.px_per_mm
        offset_y_mm = offset_y_px / self.px_per_mm
        dist_px     = np.sqrt(offset_x_px**2 + offset_y_px**2)

        if dist_px <= self.dead_zone_px:
            action = "none"
        elif dist_px <= self.grbl_threshold_px:
            action = "crop"
        else:
            action = "grbl"

        if self.debug:
            frame_out = self._draw_debug(
                frame_out, cx_img, cy_img,
                tx, ty, tr,
                offset_x_px, offset_y_px,
                offset_x_mm, offset_y_mm,
                dist_px, action,
            )


        result.update({
            "detected"      : True,
            "tube_cx"       : tx,
            "tube_cy"       : ty,
            "tube_radius"   : tr,
            "offset_x_px"   : offset_x_px,
            "offset_y_px"   : offset_y_px,
            "offset_x_mm"   : round(offset_x_mm, 3),
            "offset_y_mm"   : round(offset_y_mm, 3),
            "action"        : action,
            "frame_annotated": frame_out,
        })
        return result

    # ------------------------------------------------------------------ #
    # Calibration px/mm — 2 points
    # ------------------------------------------------------------------ #

    def calib_record_point_A(self, detection: dict, mpos: tuple) -> bool:
        """
        Enregistre le point A (position CNC + centre tube en px).
        Appeler quand la CNC est immobile sur le point A.

        :param detection: résultat de detect_tube()
        :param mpos:      (x_mm, y_mm) retourné par cnc.get_mpos()
        :return:          True si enregistré
        """
        if not detection["detected"]:
            logger.warning("calib_record_point_A: tube non détecté")
            return False

        self._calib_pos_A_px = (detection["tube_cx"], detection["tube_cy"])
        self._calib_mpos_A   = mpos
        self._calib_step     = 1
        logger.info("Calibration point A : px=%s  mpos=%s", self._calib_pos_A_px, mpos)
        return True

    def calib_record_point_B(self, detection: dict, mpos: tuple) -> dict | None:
        """
        Enregistre le point B et calcule px_per_mm.
        Appeler après déplacement CNC manuel d'une distance connue.

        :param detection: résultat de detect_tube()
        :param mpos:      (x_mm, y_mm) retourné par cnc.get_mpos()
        :return:          dict résultat calibration ou None si échec
        """
        if self._calib_step != 1:
            logger.warning("calib_record_point_B: point A non enregistré")
            return None

        if not detection["detected"]:
            logger.warning("calib_record_point_B: tube non détecté")
            return None

        pos_B_px = (detection["tube_cx"], detection["tube_cy"])
        mpos_B   = mpos

        # Déplacement en px
        dpx = np.sqrt(
            (pos_B_px[0] - self._calib_pos_A_px[0])**2 +
            (pos_B_px[1] - self._calib_pos_A_px[1])**2
        )
        # Déplacement en mm (distance euclidienne CNC)
        dmm = np.sqrt(
            (mpos_B[0] - self._calib_mpos_A[0])**2 +
            (mpos_B[1] - self._calib_mpos_A[1])**2
        )

        if dmm < 0.1 or dpx < 2:
            logger.warning("Déplacement trop faible : dpx=%.1f dmm=%.3f", dpx, dmm)
            return None

        px_per_mm_new = dpx / dmm
        self.px_per_mm = px_per_mm_new
        self._calib_step = 0

        result = {
            "px_per_mm"    : round(px_per_mm_new, 4),
            "mm_per_px"    : round(dmm / dpx, 6),
            "delta_px"     : round(dpx, 2),
            "delta_mm"     : round(dmm, 3),
            "point_A_px"   : self._calib_pos_A_px,
            "point_B_px"   : pos_B_px,
            "mpos_A"       : self._calib_mpos_A,
            "mpos_B"       : mpos_B,
        }
        logger.info("Calibration OK : %.4f px/mm  (%.6f mm/px)", px_per_mm_new, dmm/dpx)
        return result

    def calib_reset(self):
        self._calib_step     = 0
        self._calib_pos_A_px = None
        self._calib_mpos_A   = None

    # ------------------------------------------------------------------ #
    # Dessin debug
    # ------------------------------------------------------------------ #

    def _draw_debug(
        self, frame, cx_img, cy_img,
        tx, ty, tr,
        offset_x_px, offset_y_px,
        offset_x_mm, offset_y_mm,
        dist_px, action,
    ) -> np.ndarray:

        # Couleur selon action
        color = {
            "none" : (0, 255,   0),    # vert   — centré
            "crop" : (0, 200, 255),    # orange — recadrage
            "grbl" : (0,   0, 255),    # rouge  — correction CNC
        }.get(action, (200, 200, 200))

        # Cercle intérieur du tube
        cv2.circle(frame, (tx, ty), tr, color, 2, cv2.LINE_AA)

        # Rayon de zone morte (dead zone) en vert clair
        cv2.circle(frame, (cx_img, cy_img), self.dead_zone_px,
                   (0, 255, 100), 1, cv2.LINE_AA)

        # Rayon seuil GRBL en rouge pointillé (simulé par cercle fin)
        cv2.circle(frame, (cx_img, cy_img), self.grbl_threshold_px,
                   (0, 80, 255), 1, cv2.LINE_AA)

        # Croix centre image
        cv2.drawMarker(frame, (cx_img, cy_img),
                       (255, 255, 255), cv2.MARKER_CROSS, 24, 1, cv2.LINE_AA)

        # Centre tube
        cv2.circle(frame, (tx, ty), 5, color, -1, cv2.LINE_AA)

        # Vecteur offset centre image → centre tube
        if dist_px > self.dead_zone_px:
            cv2.arrowedLine(frame, (cx_img, cy_img), (tx, ty),
                            color, 2, cv2.LINE_AA, tipLength=0.2)

        # Panneau info — fond semi-transparent
        overlay = frame.copy()
        cv2.rectangle(overlay, (8, 8), (400, 130), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.45, frame, 0.55, 0, frame)

        lines = [
            (f"Tube  cx={tx} cy={ty}  r={tr}px",  (0, 255, 180)),
            (f"Offset  dx={offset_x_px:+d}px  dy={offset_y_px:+d}px",  color),
            (f"Offset  dx={offset_x_mm:+.3f}mm  dy={offset_y_mm:+.3f}mm", color),
            (f"Dist={dist_px:.1f}px   action={action.upper()}",  color),
            (f"px/mm={self.px_per_mm:.4f}",  (180, 180, 180)),
        ]
        for i, (text, col) in enumerate(lines):
            cv2.putText(frame, text, (14, 30 + i * 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.48, col, 1, cv2.LINE_AA)

        # Légende zones
        cv2.putText(frame, "dead zone", (cx_img + self.dead_zone_px + 3, cy_img - 3),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 255, 100), 1)
        cv2.putText(frame, "GRBL threshold", (cx_img + self.grbl_threshold_px + 3, cy_img - 3),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 80, 255), 1)

        # Indicateur calibration en cours
        if self._calib_step == 1:
            cv2.putText(frame, "CALIB — En attente point B",
                        (14, frame.shape[0] - 14),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 200, 255), 2, cv2.LINE_AA)

        return frame

    def _draw_debug_no_detection(self, frame, cx_img, cy_img) -> np.ndarray:
        cv2.drawMarker(frame, (cx_img, cy_img),
                       (255, 255, 255), cv2.MARKER_CROSS, 24, 1, cv2.LINE_AA)
        cv2.putText(frame, "Tube non detecte", (14, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2, cv2.LINE_AA)
        return frame 
    
    
    