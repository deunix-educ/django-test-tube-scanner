"""
Implémentation de la capture vidéo pour Raspberry Pi via PiCamera2.
Dépendance : picamera2  (sudo apt install python3-picamera2)
Compatible Pi 4 / Pi 5 avec le module caméra officiel.
"""

import io
import logging
from typing import Optional

from .capture_interface import CaptureError, VideoCaptureInterface

logger = logging.getLogger(__name__)


class PiCamera2Capture(VideoCaptureInterface):
    """
    Capture JPEG depuis la caméra officielle Raspberry Pi via PiCamera2.

    Utilise le pipeline libcamera pour la capture basse latence.
    Supporte les modules Camera Module v1, v2, v3 et HQ Camera.

    Exemple d'utilisation ::

        cam = PiCamera2Capture(fps=5, width=1280, height=720)
        cam.set_frame_callback(lambda data, ts: print(f"{ts}: {len(data)} octets"))
        cam.start()
        time.sleep(10)
        cam.stop()
    """

    def __init__(
        self,
        fps: float = VideoCaptureInterface.DEFAULT_FPS,
        width: int = 1280,
        height: int = 720,
        jpeg_quality: int = 85,
        camera_index: int = 0,
        use_video_config: bool = True,
    ):
        """
        :param fps:              Cadence cible en images par seconde
        :param width:            Largeur du flux de capture en pixels
        :param height:           Hauteur du flux de capture en pixels
        :param jpeg_quality:     Qualité de compression JPEG [0-100]
        :param camera_index:     Index de la caméra (0 par défaut, utile sur Pi 5 dual-cam)
        :param use_video_config: True = configuration VideoConfiguration (flux continu)
                                 False = StillConfiguration (haute résolution, plus lent)
        """
        super().__init__(fps=fps)
        self._width: int = width
        self._height: int = height
        self._jpeg_quality: int = jpeg_quality
        self._camera_index: int = camera_index
        self._use_video_config: bool = use_video_config
        self._picam2 = None                       # Instance Picamera2

    # ------------------------------------------------------------------
    # Implémentation des méthodes abstraites
    # ------------------------------------------------------------------

    def open(self) -> None:
        """
        Initialise PiCamera2, configure le flux et démarre le pipeline libcamera.
        """
        try:
            from picamera2 import Picamera2       # Import local : disponible uniquement sur Pi
        except ImportError as exc:
            raise CaptureError(
                "picamera2 introuvable — installez-le avec : "
                "sudo apt install python3-picamera2"
            ) from exc

        try:
            self._picam2 = Picamera2(self._camera_index)

            # Choix de la configuration selon le mode sélectionné
            if self._use_video_config:
                config = self._picam2.create_video_configuration(
                    main={"size": (self._width, self._height), "format": "RGB888"},
                )
                logger.debug("Configuration VideoConfiguration sélectionnée")
            else:
                config = self._picam2.create_still_configuration(
                    main={"size": (self._width, self._height), "format": "RGB888"},
                )
                logger.debug("Configuration StillConfiguration sélectionnée")

            self._picam2.configure(config)
            self._picam2.start()

            logger.info(
                "PiCamera2 ouverte : index=%d résolution=%dx%d mode=%s",
                self._camera_index,
                self._width,
                self._height,
                "video" if self._use_video_config else "still",
            )

        except Exception as exc:
            # Nettoyage en cas d'échec partiel d'initialisation
            if self._picam2 is not None:
                try:
                    self._picam2.close()
                except Exception:                 # noqa: BLE001
                    pass
                self._picam2 = None
            raise CaptureError(f"Impossible d'ouvrir PiCamera2 : {exc}") from exc

    def close(self) -> None:
        """Arrête le pipeline libcamera et libère les ressources."""
        if self._picam2 is not None:
            try:
                self._picam2.stop()
                self._picam2.close()
                logger.info("PiCamera2 fermée (index=%d)", self._camera_index)
            except Exception as exc:              # noqa: BLE001
                logger.warning("Erreur lors de la fermeture de PiCamera2 : %s", exc)
            finally:
                self._picam2 = None

    def capture_frame(self) -> bytes:
        """
        Capture une image depuis le flux libcamera et l'encode en JPEG.

        Stratégie : capture_array() → tableau NumPy RGB → encodage Pillow.
        capture_file() ne supporte pas le paramètre quality ; on encode
        manuellement pour contrôler le taux de compression.

        :return: Données JPEG brutes
        :raises CaptureError: Si la capture ou l'encodage échoue
        """
        if self._picam2 is None:
            raise CaptureError("PiCamera2 n'est pas initialisée")

        try:
            from PIL import Image

            # Récupération du tableau RGB depuis le flux libcamera
            arr = self._picam2.capture_array("main")  # shape (H, W, 3) uint8

            # Encodage manuel en JPEG avec la qualité configurée
            buf = io.BytesIO()
            Image.fromarray(arr).save(buf, format="JPEG", quality=self._jpeg_quality)
            return buf.getvalue()

        except Exception as exc:
            raise CaptureError(f"Échec de capture PiCamera2 : {exc}") from exc

    def is_available(self) -> bool:
        """Retourne True si le pipeline libcamera est démarré."""
        return self._picam2 is not None

    # ------------------------------------------------------------------
    # Méthodes spécifiques à PiCamera2
    # ------------------------------------------------------------------

    def capture_high_res(self, width: int, height: int) -> bytes:
        """
        Capture une image haute résolution hors flux principal (photo ponctuelle).

        Utile pour déclencher une capture pleine résolution pendant un flux 5 fps.
        Utilise capture_request() + make_array() + encodage Pillow.

        :param width:  Largeur souhaitée en pixels (indicatif, dépend de la config active)
        :param height: Hauteur souhaitée en pixels
        :return:       Données JPEG brutes
        :raises CaptureError: Si PiCamera2 n'est pas initialisée
        """
        if self._picam2 is None:
            raise CaptureError("PiCamera2 n'est pas initialisée")

        try:
            from PIL import Image

            # Capture d'une requête unique depuis le flux actif
            request = self._picam2.capture_request()
            arr = request.make_array("main")      # shape (H, W, 3) uint8 RGB
            request.release()

            buf = io.BytesIO()
            Image.fromarray(arr).save(buf, format="JPEG", quality=self._jpeg_quality)
            return buf.getvalue()

        except Exception as exc:
            raise CaptureError(f"Échec de capture haute résolution : {exc}") from exc

    def set_controls(self, **kwargs) -> None:
        """
        Applique des contrôles libcamera directement (exposition, gain, balance des blancs…).

        Exemple ::

            cam.set_controls(ExposureTime=10000, AnalogueGain=2.0)

        :param kwargs: Contrôles libcamera valides pour le module connecté
        """
        if self._picam2 is None:
            raise CaptureError("PiCamera2 n'est pas initialisée")
        self._picam2.set_controls(kwargs)
        logger.debug("Contrôles appliqués : %s", kwargs)

    def get_camera_properties(self) -> dict:
        """
        Retourne les métadonnées du module caméra détecté.

        :return: Dictionnaire des propriétés (modèle, résolution max, etc.)
        """
        if self._picam2 is None:
            raise CaptureError("PiCamera2 n'est pas initialisée")
        return self._picam2.camera_properties

    @property
    def jpeg_quality(self) -> int:
        """Qualité JPEG [0-100]."""
        return self._jpeg_quality

    @jpeg_quality.setter
    def jpeg_quality(self, value: int) -> None:
        if not 0 <= value <= 100:
            raise ValueError("La qualité JPEG doit être comprise entre 0 et 100")
        self._jpeg_quality = value

    @property
    def resolution(self) -> tuple[int, int]:
        """Résolution de capture configurée (largeur, hauteur)."""
        return (self._width, self._height)