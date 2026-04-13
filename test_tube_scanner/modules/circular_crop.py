"""
Utilitaire de recadrage circulaire centré sur une image JPEG.

Trois stratégies disponibles :
  - MASK_BLACK  : image originale, pixels hors cercle mis à noir, sortie JPEG
  - CROP_PNG    : carré 2R×2R centré, canal alpha = masque circulaire, sortie PNG
  - CROP_JPEG   : carré 2R×2R centré sans transparence, sortie JPEG (le plus compact)

    Masque noir : image JPEG de taille originale, pixels hors cercle = noir → simple mais pas économe
    Crop circulaire + PNG : on crop au carré 2R×2R, on applique le masque alpha → PNG plus petit, transparence vraie, mais PNG > JPEG en taille
    Crop carré JPEG : on extrait juste le carré 2R×2R centré → JPEG compact, pas de transparence
"""

import io
import logging
from enum import Enum, auto
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


class CropStrategy(Enum):
    """Stratégie de recadrage circulaire."""
    MASK_BLACK  = auto()    # Masque noir — taille originale, sortie JPEG
    CROP_PNG    = auto()    # Carré cropé + alpha circulaire — sortie PNG
    CROP_JPEG   = auto()    # Carré cropé sans alpha — sortie JPEG (défaut recommandé)


class CircularCrop:
    """
    Applique un recadrage circulaire centré sur une image fournie en bytes JPEG.

    Utilise uniquement NumPy + Pillow pour rester léger et compatible
    aussi bien sur PC que sur Raspberry Pi.

    Exemple ::

        crop = CircularCrop(radius=200, strategy=CropStrategy.CROP_JPEG, quality=80)
        result_bytes = crop.process(jpeg_bytes)
    """

    def __init__(
        self,
        radius: int,
        strategy: CropStrategy = CropStrategy.CROP_JPEG,
        jpeg_quality: int = 85,
        center: Optional[tuple[int, int]] = None,
    ):
        """
        :param radius:       Rayon du cercle de recadrage en pixels
        :param strategy:     Stratégie de sortie (voir CropStrategy)
        :param jpeg_quality: Qualité JPEG pour les sorties JPEG [0-100]
        :param center:       Centre du cercle (col, row) — None = centre de l'image
        """
        if radius <= 0:
            raise ValueError("Le rayon doit être un entier strictement positif")
        if not 0 <= jpeg_quality <= 100:
            raise ValueError("La qualité JPEG doit être comprise entre 0 et 100")

        self._radius        = radius
        self._strategy      = strategy
        self._jpeg_quality  = jpeg_quality
        self._center        = center            # None = calcul automatique au premier appel

        # Cache du masque pour éviter de le recalculer à chaque frame
        self._mask_cache: Optional[np.ndarray] = None
        self._mask_shape: Optional[tuple[int, int, int]] = None  # (H, W, strategy)

    # ------------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------------

    def process(self, jpeg_bytes: bytes) -> bytes:
        """
        Applique le recadrage circulaire sur une image JPEG.

        :param jpeg_bytes: Image source en bytes JPEG
        :return:           Image recadrée selon la stratégie choisie (JPEG ou PNG)
        :raises ValueError: Si les bytes ne sont pas une image valide
        """
        from PIL import Image

        # Décodage JPEG → tableau NumPy RGB
        img = Image.open(io.BytesIO(jpeg_bytes)).convert("RGB")
        arr = np.asarray(img, dtype=np.uint8)   # shape (H, W, 3)

        h, w = arr.shape[:2]
        cx, cy = self._resolve_center(w, h)

        if self._strategy == CropStrategy.MASK_BLACK:
            return self._apply_mask_black(arr, cx, cy)
        elif self._strategy == CropStrategy.CROP_PNG:
            return self._apply_crop_png(arr, cx, cy, w, h)
        else:                                    # CROP_JPEG par défaut
            return self._apply_crop_jpeg(arr, cx, cy, w, h)

    @property
    def radius(self) -> int:
        return self._radius

    @radius.setter
    def radius(self, value: int) -> None:
        """Modifie le rayon et invalide le cache du masque."""
        if value <= 0:
            raise ValueError("Le rayon doit être un entier strictement positif")
        self._radius = value
        self._invalidate_cache()

    @property
    def strategy(self) -> CropStrategy:
        return self._strategy

    @strategy.setter
    def strategy(self, value: CropStrategy) -> None:
        self._strategy = value
        self._invalidate_cache()

    @property
    def jpeg_quality(self) -> int:
        return self._jpeg_quality

    @jpeg_quality.setter
    def jpeg_quality(self, value: int) -> None:
        if not 0 <= value <= 100:
            raise ValueError("La qualité JPEG doit être comprise entre 0 et 100")
        self._jpeg_quality = value

    # ------------------------------------------------------------------
    # Stratégies internes
    # ------------------------------------------------------------------

    def _apply_mask_black(self, arr: np.ndarray, cx: int, cy: int) -> bytes:
        """
        Pixels hors cercle remplacés par du noir.
        Sortie : JPEG de la même taille que l'original.
        """
        from PIL import Image

        mask = self._get_circle_mask(arr.shape[:2], cx, cy)  # shape (H, W) bool
        result = arr.copy()
        result[~mask] = 0                        # Tout ce qui est hors cercle → noir RGB

        buf = io.BytesIO()
        Image.fromarray(result).save(buf, format="JPEG", quality=self._jpeg_quality)
        return buf.getvalue()

    def _apply_crop_png(self, arr: np.ndarray, cx: int, cy: int, w: int, h: int) -> bytes:
        """
        Crop carré 2R×2R centré + canal alpha circulaire.
        Sortie : PNG avec transparence (pixels hors cercle = transparent).
        """
        from PIL import Image

        x1, y1, x2, y2 = self._crop_box(cx, cy, w, h)
        cropped = arr[y1:y2, x1:x2]             # shape (2R, 2R, 3) ou moins si bord

        # Canal alpha : 255 dans le cercle, 0 à l'extérieur
        ch, cw = cropped.shape[:2]
        local_cx = cx - x1
        local_cy = cy - y1
        alpha_mask = self._get_circle_mask((ch, cw), local_cx, local_cy)
        alpha = np.where(alpha_mask, 255, 0).astype(np.uint8)

        rgba = np.dstack([cropped, alpha])       # shape (H, W, 4)

        buf = io.BytesIO()
        Image.fromarray(rgba, mode="RGBA").save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    def _apply_crop_jpeg(self, arr: np.ndarray, cx: int, cy: int, w: int, h: int) -> bytes:
        """
        Crop carré 2R×2R centré, pixels hors cercle mis à noir.
        Sortie : JPEG compact sans canal alpha (meilleur compromis taille/qualité).
        """
        from PIL import Image

        x1, y1, x2, y2 = self._crop_box(cx, cy, w, h)
        cropped = arr[y1:y2, x1:x2].copy()

        ch, cw = cropped.shape[:2]
        local_cx = cx - x1
        local_cy = cy - y1
        mask = self._get_circle_mask((ch, cw), local_cx, local_cy)
        cropped[~mask] = 0                       # Hors cercle → noir dans le crop

        buf = io.BytesIO()
        Image.fromarray(cropped).save(buf, format="JPEG", quality=self._jpeg_quality)
        return buf.getvalue()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_center(self, w: int, h: int) -> tuple[int, int]:
        """Retourne le centre configuré ou le centre géométrique de l'image."""
        if self._center is not None:
            return self._center
        return (w // 2, h // 2)

    def _crop_box(self, cx: int, cy: int, w: int, h: int) -> tuple[int, int, int, int]:
        """
        Calcule la boîte de crop 2R×2R clampée aux bords de l'image.

        :return: (x1, y1, x2, y2) en coordonnées image
        """
        r = self._radius
        x1 = max(cx - r, 0)
        y1 = max(cy - r, 0)
        x2 = min(cx + r, w)
        y2 = min(cy + r, h)
        return (x1, y1, x2, y2)

    def _get_circle_mask(self, shape: tuple[int, int], cx: int, cy: int) -> np.ndarray:
        """
        Construit (ou récupère du cache) le masque booléen circulaire.

        Le masque est recalculé uniquement si la taille ou le centre change.

        :param shape: (hauteur, largeur) du tableau cible
        :param cx:    Colonne du centre dans ce tableau
        :param cy:    Ligne du centre dans ce tableau
        :return:      Tableau bool shape (H, W) — True = dans le cercle
        """
        cache_key = (shape[0], shape[1], cx, cy, self._radius)

        if self._mask_cache is None or self._mask_shape != cache_key:
            h, w = shape
            # Coordonnées entières de chaque pixel via meshgrid
            ys, xs = np.ogrid[:h, :w]
            dist_sq = (xs - cx) ** 2 + (ys - cy) ** 2
            self._mask_cache = dist_sq <= self._radius ** 2
            self._mask_shape = cache_key
            logger.debug(
                "Masque circulaire recalculé : shape=%s centre=(%d,%d) R=%d",
                shape, cx, cy, self._radius,
            )

        return self._mask_cache

    def _invalidate_cache(self) -> None:
        """Invalide le cache du masque (après changement de rayon ou stratégie)."""
        self._mask_cache = None
        self._mask_shape = None
