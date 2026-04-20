"""
Implémentation de la capture vidéo pour Raspberry Pi via PiCamera2.
Dépendance : picamera2  (sudo apt install python3-picamera2)
Compatible Pi 4 / Pi 5 avec le module caméra officiel (v2, v3, HQ).
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

    La résolution demandée (width, height) est approchée au mieux :
    libcamera sélectionne automatiquement le mode sensor dont la résolution
    native est la plus proche, puis redimensionne en ISP.
    Utiliser list_sensor_modes() pour connaître les modes disponibles.

    Exemple d'utilisation ::

        # Afficher les modes disponibles avant d'instancier
        PiCamera2Capture.list_sensor_modes()

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
        use_tracking: bool = False,
        px_per_mm: float = 2.1,
        display = None,

    ):
        """
        :param fps:              Cadence cible en images par seconde
        :param width:            Largeur souhaitée en pixels (approchée au mode sensor le plus proche)
        :param height:           Hauteur souhaitée en pixels (approchée au mode sensor le plus proche)
        :param jpeg_quality:     Qualité de compression JPEG [0-100]
        :param camera_index:     Index de la caméra (0 par défaut, utile sur Pi 5 dual-cam)
        :param use_video_config: True = VideoConfiguration (flux continu, basse latence)
                                 False = StillConfiguration (haute résolution, plus lent)
        """
        super().__init__(fps=fps, use_tracking=use_tracking, px_per_mm=px_per_mm, display=display)
        self._width: int = width
        self._height: int = height
        self._jpeg_quality: int = jpeg_quality
        self._camera_index: int = camera_index
        self._use_video_config: bool = use_video_config
        self._picam2 = None                       # Instance Picamera2
        self._effective_size: Optional[tuple[int, int]] = None  # Résolution réellement appliquée

    # ------------------------------------------------------------------
    # Méthode statique utilitaire — à appeler avant d'instancier
    # ------------------------------------------------------------------

    @staticmethod
    def list_sensor_modes(camera_index: int = 0) -> list[dict]:
        """
        Affiche et retourne tous les modes sensor disponibles pour la caméra.

        À appeler avant d'instancier PiCamera2Capture pour choisir
        une résolution compatible avec un mode sensor natif.

        :param camera_index: Index de la caméra à interroger
        :return:             Liste de dicts décrivant chaque mode sensor
        :raises CaptureError: Si picamera2 n'est pas disponible
        """
        try:
            from picamera2 import Picamera2
        except ImportError as exc:
            raise CaptureError(
                "picamera2 introuvable — installez-le avec : "
                "sudo apt install python3-picamera2"
            ) from exc

        picam2 = Picamera2(camera_index)
        try:
            # sensor_modes doit être interrogé avant configure()
            modes = picam2.sensor_modes
            print(f"\n=== Modes sensor disponibles (caméra index={camera_index}) ===")
            for i, mode in enumerate(modes):
                size   = mode.get("size", "?")
                fps    = mode.get("fps", "?")
                crop   = mode.get("crop_limits", "?")
                fmt    = mode.get("format", "?")
                print(
                    f"  [{i}] {size[0]}×{size[1]}px  "
                    f"fps_max={fps:.1f}  format={fmt}  crop={crop}"
                )
            print()
            return modes
        finally:
            picam2.close()

    # ------------------------------------------------------------------
    # Implémentation des méthodes abstraites
    # ------------------------------------------------------------------

    def open(self) -> None:
        """
        Initialise PiCamera2, sélectionne le mode sensor le plus adapté
        à la résolution demandée, configure le flux et démarre libcamera.

        Le mode sensor est choisi en minimisant la distance euclidienne
        entre la résolution native du mode et (width, height) demandés.
        """
        try:
            from picamera2 import Picamera2
        except ImportError as exc:
            raise CaptureError(
                "picamera2 introuvable — installez-le avec : "
                "sudo apt install python3-picamera2"
            ) from exc

        try:
            self._picam2 = Picamera2(self._camera_index)

            # Sélection du mode sensor le plus proche de la résolution demandée
            best_mode = self._select_best_sensor_mode(self._picam2)

            # Construction de la configuration avec le mode sensor forcé
            if self._use_video_config:
                config = self._picam2.create_video_configuration(
                    main={"size": (self._width, self._height), "format": "RGB888"},
                    raw=best_mode,                # Force le mode sensor natif
                )
                logger.debug("Configuration VideoConfiguration sélectionnée")
            else:
                config = self._picam2.create_still_configuration(
                    main={"size": (self._width, self._height), "format": "RGB888"},
                    raw=best_mode,
                )
                logger.debug("Configuration StillConfiguration sélectionnée")

            self._picam2.configure(config)
            self._picam2.start()

            # Lecture de la résolution effectivement appliquée par l'ISP
            actual = config["main"]["size"]
            self._effective_size = actual

            logger.info(
                "PiCamera2 ouverte : index=%d  demandé=%dx%d  effectif=%dx%d  "
                "mode_sensor=%dx%d  mode=%s",
                self._camera_index,
                self._width, self._height,
                actual[0], actual[1],
                best_mode["size"][0], best_mode["size"][1],
                "video" if self._use_video_config else "still",
            )

            # Avertissement si la résolution effective diffère de la demande
            if actual != (self._width, self._height):
                logger.warning(
                    "Résolution ajustée par libcamera : %dx%d → %dx%d. "
                    "Utilisez list_sensor_modes() pour connaître les tailles compatibles.",
                    self._width, self._height, actual[0], actual[1],
                )

        except Exception as exc:
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
                self._effective_size = None

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
        """Résolution de capture demandée (largeur, hauteur)."""
        return (self._width, self._height)

    @property
    def effective_resolution(self) -> Optional[tuple[int, int]]:
        """
        Résolution effectivement appliquée par l'ISP après ouverture.
        None si la caméra n'est pas encore ouverte.
        """
        return self._effective_size

    # ------------------------------------------------------------------
    # Helpers privés
    # ------------------------------------------------------------------

    def _select_best_sensor_mode(self, picam2) -> dict:
        """
        Choisit le mode sensor dont la résolution native est la plus proche
        de (width, height) en minimisant la distance euclidienne.

        :param picam2: Instance Picamera2 déjà créée mais pas encore configurée
        :return:       Dict du mode sensor sélectionné
        """
        modes = picam2.sensor_modes
        if not modes:
            raise CaptureError("Aucun mode sensor disponible")

        def distance(mode: dict) -> float:
            mw, mh = mode["size"]
            # Distance euclidienne normalisée entre la résolution du mode et la cible
            return ((mw - self._width) ** 2 + (mh - self._height) ** 2) ** 0.5

        best = min(modes, key=distance)
        logger.debug(
            "Mode sensor sélectionné : %dx%d (demandé : %dx%d)",
            best["size"][0], best["size"][1],
            self._width, self._height,
        )
        return best
