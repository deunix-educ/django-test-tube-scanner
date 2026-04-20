"""
Implémentation de la capture vidéo à partir d'un fichier video via OpenCV (cv2).
Dépendance : opencv-python  (pip install opencv-python)

    OpenCV (cv2) avec import local pour éviter une dépendance globale
    Résolution configurable, qualité JPEG réglable à chaud, accès V4L2 par index
    get_resolution() pour lire la résolution effective appliquée par le pilote
"""
import os
os.environ['OPENCV_LOG_LEVEL']="0"
os.environ['OPENCV_FFMPEG_LOGLEVEL']="0"
import cv2

import logging
from typing import Optional
from .capture_interface import CaptureError, VideoCaptureInterface

logger = logging.getLogger(__name__)


class VideoFileCapture(VideoCaptureInterface):
    """
    Capture JPEG depuis une webcam USB/intégrée via OpenCV.

    Exemple d'utilisation ::

        cam = VideoFileCapture(video_file=0, fps=5)
        cam.set_frame_callback(lambda data, ts: print(f"{ts}: {len(data)} octets"))
        cam.start()
        time.sleep(10)
        cam.stop()
    """

    def __init__(
        self,
        video_file: str = None,
        fps: float = VideoCaptureInterface.DEFAULT_FPS,
        jpeg_quality: int = 85,
        width: Optional[int] = None,
        height: Optional[int] = None,
        video_lists = [],
        use_tracking: bool = False,
        px_per_mm: float = 2.1,
        display = None,
    ):
        """
        :param video_file:   fichier video
        :param fps:           Cadence cible en images par seconde
        :param jpeg_quality:  Qualité de compression JPEG [0-100]
        :param width:         Largeur souhaitée (None = valeur par défaut du pilote)
        :param height:        Hauteur souhaitée (None = valeur par défaut du pilote)
        """
        super().__init__(fps=fps, use_tracking=use_tracking, px_per_mm=px_per_mm, display=display)
        self._video_file: str = video_file
        self._jpeg_quality: int = jpeg_quality
        self._width: Optional[int] = width
        self._height: Optional[int] = height
        self._video_lists = video_lists
        
        self.ptf = 0
        self._cap = None                          # Instance cv2.VideoCapture

    def get_file(self):
        if self._video_lists:
            self._video_file = self._video_lists[self.ptf]
            self.ptf += 1
            if self.ptf >= len(self._video_lists):
                self.ptf = 0
        return self._video_file
            

    # ------------------------------------------------------------------
    # Implémentation des méthodes abstraites
    # ------------------------------------------------------------------

    def open(self) -> None:
        """Ouvre le flux V4L2 via OpenCV et configure la résolution."""
        self.get_file()

        self._cap = cv2.VideoCapture(self._video_file)

        if not self._cap.isOpened():
            raise CaptureError(
                f"Impossible d'ouvrir le fichier (index={self._video_file})"
            )

        # Application de la résolution demandée
        if self._width:
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        if self._height:
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)

        # Lecture de la résolution effectivement appliquée par le pilote
        actual_w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        logger.info(
            f"Fichier ouvert: index=%s résolution=%dx%d",
            self._video_file, actual_w, actual_h,
        )

    def close(self) -> None:
        """Libère le flux OpenCV."""
        if self._cap and self._cap.isOpened():
            self._cap.release()
            logger.info("Fichier fermé (index=%s)", self._video_file)
        self._cap = None

    def capture_frame(self) -> bytes:
        """
        Lit une trame brute depuis OpenCV et l'encode en JPEG.

        :return: Données JPEG brutes
        :raises CaptureError: Si la lecture ou l'encodage échoue
        """
        #import cv2
        #import numpy as np                        # noqa: F401 — utilisé implicitement par cv2
        
        if self._error_occured:
            self.close()
            self.open()
            self._error_occured = False
            

        if not self._cap or not self._cap.isOpened():
            raise CaptureError("Le fichier n'est pas ouvert")

        ret, frame = self._cap.read()
        if not ret or frame is None:
            raise CaptureError("Échec de lecture de la trame ou fin de fichier")

        # Encodage BGR → JPEG avec la qualité configurée
        encode_params = [cv2.IMWRITE_JPEG_QUALITY, self._jpeg_quality]
        success, buffer = cv2.imencode(".jpg", frame, encode_params)

        if not success:
            raise CaptureError("Échec d'encodage JPEG")

        return buffer.tobytes()

    def is_available(self) -> bool:
        """Retourne True si le flux OpenCV est ouvert et prêt."""
        return self._cap is not None and self._cap.isOpened()

    # ------------------------------------------------------------------
    # Accesseurs spécifiques à la webcam
    # ------------------------------------------------------------------

    @property
    def video_file(self) -> int:
        """Index du périphérique V4L2."""
        return self._video_file

    @property
    def jpeg_quality(self) -> int:
        """Qualité JPEG [0-100]."""
        return self._jpeg_quality

    @jpeg_quality.setter
    def jpeg_quality(self, value: int) -> None:
        if not 0 <= value <= 100:
            raise ValueError("La qualité JPEG doit être comprise entre 0 et 100")
        self._jpeg_quality = value

    def get_resolution(self) -> Optional[tuple[int, int]]:
        """
        Retourne la résolution effective du flux.

        :return: Tuple (largeur, hauteur) ou None si la webcam est fermée
        """
        if not self.is_available():
            return None

        w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        return (w, h)
