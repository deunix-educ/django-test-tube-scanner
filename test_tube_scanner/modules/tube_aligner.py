'''
modules/tube_aligner.py
Created on 17 avr. 2026

@author: denis
'''

import cv2
import logging
import numpy as np

logger = logging.getLogger(__name__)


class TubeAligner:

    GRBL_THRESHOLD_PX = 20
    DEAD_ZONE_PX      = 5

    def __init__(
        self,
        grbl_threshold_px : int   = 20,
        dead_zone_px      : int   = 5,
        debug             : bool  = False,      # ← activable depuis la vue
        display = None,                         # display function 
    ):
        self.grbl_threshold_px = grbl_threshold_px
        self.dead_zone_px      = dead_zone_px
        self.debug             = debug
        self.display           = display
        self.TUBE_DIAMETER_MM  = 16.0


    def set_tube_diameter(self, tube_diameter: float = 16.0) -> None:
        self.TUBE_DIAMETER_MM  = tube_diameter

    # ------------------------------------------------------------------ #
    # Détection principale
    # ------------------------------------------------------------------ #

    def detect_tube(self, frame: np.ndarray, tube_diameter: float = None) -> dict:
        if tube_diameter is not None:
            self.set_tube_diameter(tube_diameter)
        
        h, w    = frame.shape[:2]
        cx_img  = w // 2
        cy_img  = h // 2

        result = {
            "detected"       : False,
            "tube_cx"        : None,
            "tube_cy"        : None,
            "tube_radius"    : None,
            "radius_mm"      : self.TUBE_DIAMETER_MM / 2,
            "offset_x_px"    : 0,
            "offset_y_px"    : 0,
            "offset_x_mm"    : 0.0,
            "offset_y_mm"    : 0.0,
            "px_per_mm"      : 0.0,
            "action"         : "none",
            "frame_annotated": None,
            "msg"            : None,
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
            msg = f"TubeAligner: aucun cercle détecté ({w}x{h})"
            result["msg"] =msg
            if self.debug:
                frame_out = self._draw_debug_no_detection(frame_out, cx_img, cy_img)
            result["frame_annotated"] = frame_out
            return result        

        # Moyenne des détections convergentes
        tx = int(np.mean(all_cx))
        ty = int(np.mean(all_cy))
        tr = int(np.mean(all_r))
        if tr > 0:
            self.px_per_mm = (2 * tr) / self.TUBE_DIAMETER_MM
    
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
            
        dx_mm , dy_mm = round(offset_x_mm, 3), round(offset_y_mm, 3)
        result.update({
            "detected"      : True,
            "tube_cx"       : tx,
            "tube_cy"       : ty,
            "tube_radius"   : tr,
            "radius_mm"     : self.TUBE_DIAMETER_MM / 2,
            "px_per_mm"     : self.px_per_mm,
            "offset_x_px"   : offset_x_px,
            "offset_y_px"   : offset_y_px,
            "offset_x_mm"   : dx_mm,
            "offset_y_mm"   : dy_mm,
            "action"        : action,
            "frame_annotated": frame_out,
            "msg"           : f"Correction CNC relative (dx={dx_mm:}, dy={dy_mm}), action: {action}"
        })
        return result
       
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
        cv2.circle(frame, (cx_img, cy_img), self.dead_zone_px, (0, 255, 100), 1, cv2.LINE_AA)
        # Rayon seuil GRBL en rouge pointillé (simulé par cercle fin)
        cv2.circle(frame, (cx_img, cy_img), self.grbl_threshold_px, (0, 80, 255), 1, cv2.LINE_AA)
        # Croix centre image
        cv2.drawMarker(frame, (cx_img, cy_img), (255, 255, 255), cv2.MARKER_CROSS, 24, 1, cv2.LINE_AA)
        # Centre tube
        cv2.circle(frame, (tx, ty), 5, color, -1, cv2.LINE_AA)

        # Vecteur offset centre image → centre tube
        if dist_px > self.dead_zone_px:
            cv2.arrowedLine(frame, (cx_img, cy_img), (tx, ty), color, 2, cv2.LINE_AA, tipLength=0.2)

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
        cv2.putText(frame, "dead zone", (cx_img + self.dead_zone_px + 3, cy_img - 3),  cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 255, 100), 1)
        cv2.putText(frame, "GRBL threshold", (cx_img + self.grbl_threshold_px + 3, cy_img + 6), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 80, 255), 1)
        return frame

    def _draw_debug_no_detection(self, frame, cx_img, cy_img) -> np.ndarray:
        cv2.drawMarker(frame, (cx_img, cy_img),
                       (255, 255, 255), cv2.MARKER_CROSS, 24, 1, cv2.LINE_AA)
        cv2.putText(frame, "Tube non detecte", (14, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2, cv2.LINE_AA)
        return frame 
    
    
    