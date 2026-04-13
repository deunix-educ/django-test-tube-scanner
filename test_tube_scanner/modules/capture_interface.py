"""
Interface abstraite de capture vidéo.
Définit le contrat que toutes les implémentations doivent respecter.

    4 méthodes @abstractmethod à implémenter : open(), close(), capture_frame(), is_available()
        Boucle de capture dans un thread daemon avec compensation de latence pour tenir les 5 fps
        Callback set_frame_callback(fn) appelé à chaque frame avec (bytes, datetime)
        save_frame() avec horodatage, start()/stop(), gestionnaire de contexte (with)
        CaptureError exception dédiée
"""
import os
os.environ['OPENCV_LOG_LEVEL']="0"
os.environ['OPENCV_FFMPEG_LOGLEVEL']="0"
import cv2
import numpy as np

import abc
import time
import threading
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from .circular_crop import CircularCrop     # Evite l'import circulaire au runtime

logger = logging.getLogger(__name__)


class CaptureError(Exception):
    """Exception levée lors d'une erreur de capture."""
    pass


class VideoCaptureInterface(abc.ABC):
    """
    Interface abstraite pour la capture d'images vidéo en JPEG.

    Cadence cible : 5 images par seconde (configurable).
    Les sous-classes doivent implémenter les méthodes abstraites
    pour gérer le matériel spécifique.
    """

    # Cadence par défaut en images par seconde
    DEFAULT_FPS: float = 5.0

    def __init__(self, fps: float = DEFAULT_FPS):
        """
        Initialise l'interface de capture.

        :param fps: Cadence cible en images par seconde
        """
        self._fps: float = fps
        self._interval: float = 1.0 / fps       # Intervalle en secondes entre chaque capture
        self._running: bool = False              # Indique si la capture est en cours
        self._thread: Optional[threading.Thread] = None
        self._frame_count: int = 0               # Compteur total d'images capturées
        self._on_frame: Optional[Callable[[bytes, datetime], None]] = None  # Callback image
        self._circular_crop: Optional["CircularCrop"] = None  # Recadrage circulaire optionnel
        self._active_median = False

    # ------------------------------------------------------------------
    # Méthodes abstraites — obligatoires dans les sous-classes
    # ------------------------------------------------------------------

    @abc.abstractmethod
    def open(self) -> None:
        """
        Ouvre et initialise le périphérique de capture.
        Doit lever CaptureError si le périphérique n'est pas disponible.
        """

    @abc.abstractmethod
    def close(self) -> None:
        """
        Libère le périphérique de capture et toutes les ressources associées.
        """

    @abc.abstractmethod
    def capture_frame(self) -> bytes:
        """
        Capture une seule image et la retourne en JPEG brut.

        :return: Données JPEG de l'image sous forme de bytes
        :raises CaptureError: Si la capture échoue
        """

    @abc.abstractmethod
    def is_available(self) -> bool:
        """
        Vérifie si le périphérique est prêt à capturer.

        :return: True si le périphérique est opérationnel
        """

    # ------------------------------------------------------------------
    # Méthodes concrètes communes à toutes les implémentations
    # ------------------------------------------------------------------

    @property
    def fps(self) -> float:
        """Cadence actuelle en images par seconde."""
        return self._fps

    @fps.setter
    def fps(self, value: float) -> None:
        """Modifie la cadence de capture à la volée."""
        if value <= 0:
            raise ValueError("La cadence doit être un nombre positif")
        self._fps = value
        self._interval = 1.0 / value
        logger.debug("Cadence mise à jour : %.1f fps (intervalle %.3f s)", value, self._interval)

    @property
    def frame_count(self) -> int:
        """Nombre total d'images capturées depuis le démarrage."""
        return self._frame_count

    def set_frame_callback(self, callback: Callable[[bytes, datetime], None]) -> None:
        """
        Définit la fonction appelée à chaque nouvelle image capturée.

        :param callback: Fonction(jpeg_bytes, timestamp) appelée pour chaque frame
        """
        self._on_frame = callback

    def start(self) -> None:
        """
        Démarre la capture en continu dans un thread dédié.
        Appelle open() si le périphérique n'est pas encore disponible.
        """
        if self._running:
            logger.warning("La capture est déjà en cours")
            return

        if not self.is_available():
            logger.info("Ouverture du périphérique avant démarrage")
            self.open()

        self._running = True
        self._frame_count = 0
        self._thread = threading.Thread(
            target=self._capture_loop,
            name=f"{self.__class__.__name__}-capture",
            daemon=True,                          # Thread démon : s'arrête avec le processus principal
        )
        self._thread.start()
        logger.info("%s : capture démarrée à %.1f fps", self.__class__.__name__, self._fps)

    def stop(self) -> None:
        """
        Arrête la capture et attend la fin du thread.
        Appelle close() pour libérer les ressources.
        """
        if not self._running:
            return

        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)        # Attente max 5 secondes
        self.close()
        logger.info(
            "%s : capture arrêtée — %d images capturées",
            self.__class__.__name__,
            self._frame_count,
        )

    def set_circular_crop(self, crop: Optional["CircularCrop"]) -> None:
        """
        Active ou désactive le recadrage circulaire appliqué à chaque frame.

        Lorsqu'un CircularCrop est défini, chaque appel à capture_frame()
        passe automatiquement par process_frame() avant d'être transmis
        au callback ou sauvegardé.

        :param crop: Instance CircularCrop configurée, ou None pour désactiver
        """
        self._circular_crop = crop
        if crop is not None:
            logger.info(
                "%s : recadrage circulaire activé (R=%d, stratégie=%s)",
                self.__class__.__name__, crop.radius, crop.strategy.name,
            )
        else:
            logger.info("%s : recadrage circulaire désactivé", self.__class__.__name__)

    def process_frame(self, jpeg_bytes: bytes) -> bytes:
        """
        Applique le post-traitement configuré sur une image brute.

        Actuellement : recadrage circulaire si un CircularCrop est défini.
        Peut être surchargé dans une sous-classe pour des traitements spécifiques.

        :param jpeg_bytes: Image JPEG brute issue du capteur
        :return:           Image traitée (JPEG ou PNG selon la stratégie)
        """
        if self._circular_crop is not None:
            return self._circular_crop.process(jpeg_bytes)
        return jpeg_bytes

    def save_frame(self, jpeg_bytes: bytes, directory: str = ".", prefix: str = "frame") -> Path:
        """
        Enregistre une image JPEG sur le disque avec un horodatage.

        :param jpeg_bytes: Données brutes JPEG
        :param directory: Dossier de destination
        :param prefix: Préfixe du nom de fichier
        :return: Chemin du fichier créé
        """
        dest = Path(directory)
        dest.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filepath = dest / f"{prefix}_{timestamp}.jpg"
        filepath.write_bytes(jpeg_bytes)
        logger.debug("Image sauvegardée : %s (%d octets)", filepath, len(jpeg_bytes))
        return filepath

    def __enter__(self) -> "VideoCaptureInterface":
        """Permet l'utilisation avec le gestionnaire de contexte 'with'."""
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Ferme proprement le périphérique à la sortie du bloc 'with'."""
        self.close()

    def __repr__(self) -> str:
        status = "actif" if self._running else "arrêté"
        return f"<{self.__class__.__name__} fps={self._fps} status={status}>"

    # ------------------------------------------------------------------
    # tracer médianes
    # ------------------------------------------------------------------
    def set_median(self, is_median=False):
        """
        Active ou désactive les médianes
        """
        self._active_median = is_median

    def display_median(self, jpeg):
        if self._active_median:
            nparr = np.frombuffer(jpeg, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            height, width = frame.shape[:2]
            center_x = width // 2
            center_y = height // 2

            cv2.line(frame, (center_x, 0), (center_x, height), (0, 255, 0), 1)
            cv2.line(frame, (0, center_y), (width, center_y), (0, 255, 0), 1)
            cv2.circle(frame, (center_x, center_y), 2, (0, 0, 255), -1)

            cv2.putText(frame, f"Num: {self._frame_count}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

            _, buffer = cv2.imencode('.jpg', frame)
            jpeg_bytes = buffer.tobytes()
            return jpeg_bytes
        return jpeg



    # ------------------------------------------------------------------
    # Boucle interne de capture (privée)
    # ------------------------------------------------------------------

    def _capture_loop(self) -> None:
        """
        Boucle principale de capture tournant dans le thread dédié.
        Respecte la cadence cible et appelle le callback si défini.
        """

        while self._running:
            loop_start = time.monotonic()

            try:
                jpeg = self.capture_frame()
                jpeg = self.display_median(jpeg)
                jpeg = self.process_frame(jpeg)  # Recadrage circulaire si configuré

                self._frame_count += 1

                ts = datetime.now(timezone.utc)

                if self._on_frame:
                    try:
                        self._on_frame(jpeg, ts)
                    except Exception as cb_err:  # noqa: BLE001
                        logger.error("Erreur dans le callback image : %s", cb_err)

            except CaptureError as err:
                logger.error("Échec de capture (#%d) : %s", self._frame_count, err)

            # Compensation du temps d'exécution pour tenir la cadence
            elapsed = time.monotonic() - loop_start
            sleep_time = self._interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
            else:
                logger.debug(
                    "Cadence non tenue : %.3f s de retard (traitement=%.3f s)",
                    -sleep_time,
                    elapsed,
                )
