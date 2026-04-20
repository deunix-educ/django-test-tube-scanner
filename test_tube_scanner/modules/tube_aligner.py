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
        display = None,
    ):
        self.TUBE_DIAMETER_MM  = 16.0
        self.grbl_threshold_px = grbl_threshold_px
        self.dead_zone_px      = dead_zone_px
        self.debug             = debug
        self.display           = display     

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
        frame_out = frame.copy()
        
        gray    = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (15, 15), 3)
        
        # 3 configurations légèrement différentes — vote majoritaire
        # Fonctionne sur fond sombre ET fond clair
        configs = [
            dict(param1=50, param2=30, minRadius=int(min(w,h)*0.26), maxRadius=int(min(w,h)*0.36)),
            dict(param1=60, param2=30, minRadius=int(min(w,h)*0.26), maxRadius=int(min(w,h)*0.37)),
            dict(param1=50, param2=28, minRadius=int(min(w,h)*0.25), maxRadius=int(min(w,h)*0.365)),
        ]
        
        all_cx, all_cy, all_r = [], [], []
        for cfg in configs:
            circles = cv2.HoughCircles(
                blurred, 
                cv2.HOUGH_GRADIENT,
                dp=1.2, 
                minDist=min(w, h) // 2, 
                **cfg
            )
            if circles is not None:
                c    = np.round(circles[0]).astype(int)
                best = min(c, key=lambda c: np.sqrt((c[0]-cx_img)**2 + (c[1]-cy_img)**2))
                all_cx.append(int(best[0]))
                all_cy.append(int(best[1]))
                all_r.append(int(best[2]))
    
        if not all_cx:
            logger.warning("TubeAligner: aucun cercle détecté (%dx%d)", w, h)
            if self.debug:
                frame_out = self._draw_debug_no_detection(frame_out, cx_img, cy_img)
            result["frame_annotated"] = frame_out
            return result        

        # Moyenne des détections convergentes
        tx = int(np.mean(all_cx))
        ty = int(np.mean(all_cy))
        tr = int(np.mean(all_r))
        if tr > 0:
            self.px_per_mm = (2 * tr) / 16.0
    
        offset_x_px = tx - cx_img
        offset_y_px = ty - cy_img
        #offset_x_mm = offset_x_px / self.px_per_mm
        #offset_y_mm = offset_y_px /self. px_per_mm
        
        offset_x_mm = offset_y_px /self. px_per_mm  # (X CNC = Y image)
        offset_y_mm = -offset_x_px / self.px_per_mm # (Y CNC = -X image)
        
        dist_px     = float(np.sqrt(offset_x_px**2 + offset_y_px**2))
    
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
                votes=len(all_cx),          # ← affiche le nombre de configs ayant détecté
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
    
    
    def _detect_center_stable(
        self,
        capture_func,       # callable() → frame bytes
        n_samples: int = 5,
        delay_s: float = 0.3,
    ) -> tuple[float, float] | None:
        """
        Capture N frames et retourne le centre moyen du tube.
        Réduit l'erreur de détection d'un facteur √N.
    
        :param capture_func: callable sans argument → bytes JPEG
        :param n_samples:    nombre de captures à moyenner
        :param delay_s:      pause entre chaque capture
        :return:             (cx_mean, cy_mean) ou None si échec
        """
        import time
        centers = []
    
        for i in range(n_samples):
            if i > 0:
                time.sleep(delay_s)
    
            frame_bytes = capture_func()
            nparr = np.frombuffer(frame_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    
            if frame is None:
                continue
    
            detection = self.detect_tube(frame)
            if detection["detected"]:
                centers.append((detection["tube_cx"], detection["tube_cy"]))
                logger.debug(
                    "_detect_center_stable [%d/%d] : cx=%d cy=%d",
                    i+1, n_samples,
                    detection["tube_cx"], detection["tube_cy"],
                )
            else:
                logger.warning("_detect_center_stable [%d/%d] : tube non détecté", i+1, n_samples)
    
        if len(centers) < 3:
            logger.error("_detect_center_stable : seulement %d détections valides", len(centers))
            return None
    
        # Filtre les valeurs aberrantes (écart > 2 sigma)
        cx_arr = np.array([c[0] for c in centers], dtype=float)
        cy_arr = np.array([c[1] for c in centers], dtype=float)
    
        cx_mean, cx_std = np.mean(cx_arr), np.std(cx_arr)
        cy_mean, cy_std = np.mean(cy_arr), np.std(cy_arr)
    
        mask = (
            (np.abs(cx_arr - cx_mean) <= 2 * cx_std) &
            (np.abs(cy_arr - cy_mean) <= 2 * cy_std)
        )
        filtered = [(cx_arr[i], cy_arr[i]) for i in range(len(centers)) if mask[i]]
    
        if not filtered:
            filtered = centers   # fallback si tout est filtré
    
        cx_final = float(np.mean([c[0] for c in filtered]))
        cy_final = float(np.mean([c[1] for c in filtered]))
    
        logger.info(
            "_detect_center_stable : %d/%d valides  cx=%.1f±%.1f  cy=%.1f±%.1f",
            len(filtered), n_samples,
            cx_final, cx_std, cy_final, cy_std,
        )
        return cx_final, cy_final
    
    
     
    def calib_reset(self):
        pass

    # ------------------------------------------------------------------ #
    # Dessin debug
    # ------------------------------------------------------------------ #

    def _draw_debug(
        self, frame, cx_img, cy_img,
        tx, ty, tr,
        offset_x_px, offset_y_px,
        offset_x_mm, offset_y_mm,
        dist_px, action, votes: int = 3
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
            (f"Tube  cx={tx} cy={ty}  r={tr}px",              (0, 255, 180)),
            (f"Offset  dx={offset_x_px:+d}px  dy={offset_y_px:+d}px", color),
            (f"Offset  dx={offset_x_mm:+.3f}mm  dy={offset_y_mm:+.3f}mm", color),
            (f"Dist={dist_px:.1f}px   action={action.upper()}", color),
            (f"px/mm={self.px_per_mm:.4f}   votes={votes}/3",  (180, 180, 180)),  # ← votes
        ]        
        
        for i, (text, col) in enumerate(lines):
            cv2.putText(frame, text, (14, 30 + i * 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.48, col, 1, cv2.LINE_AA)

        # Légende zones
        cv2.putText(frame, "dead zone", (cx_img + self.dead_zone_px + 3, cy_img - 3),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 255, 100), 1)
        cv2.putText(frame, "GRBL threshold", (cx_img + self.grbl_threshold_px + 3, cy_img + 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 80, 255), 1)
        return frame

    def _draw_debug_no_detection(self, frame, cx_img, cy_img) -> np.ndarray:
        cv2.drawMarker(frame, (cx_img, cy_img),
                       (255, 255, 255), cv2.MARKER_CROSS, 24, 1, cv2.LINE_AA)
        cv2.putText(frame, "Tube non detecte", (14, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2, cv2.LINE_AA)
        return frame 
    
    
    