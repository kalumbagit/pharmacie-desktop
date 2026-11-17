"""Filigrane (logo en transparence) pour les PDF générés avec ReportLab.

Deux usages :
- documents Platypus (factures A4...) : `doc.build(story, **watermark_callbacks(logo))` ;
- documents dessinés au canvas (reçu ticket) : `draw_watermark(pdf, largeur, hauteur, logo)`
  à appeler AVANT le contenu, pour que le logo reste en arrière-plan.

La transparence est « cuite » dans l'image (canal alpha multiplié) : le rendu ne dépend donc
ni du lecteur PDF ni des états graphiques ReportLab. Un logo absent ou illisible n'empêche
jamais de produire le document : le filigrane est simplement omis.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError
from reportlab.lib.utils import ImageReader

logger = logging.getLogger(__name__)

DEFAULT_OPACITY = 0.10  # 0 = invisible, 1 = opaque
DEFAULT_PAGE_RATIO = 0.60  # le logo occupe au plus 60 % de la largeur / de la hauteur
MAX_PIXELS = 900  # on réduit les grands logos : le PDF reste léger


@lru_cache(maxsize=8)
def _faded_logo(path: str, mtime_ns: int, opacity: float) -> tuple[ImageReader, int, int] | None:
    """Charge le logo, applique la transparence. Mis en cache (clé : chemin + date du fichier)."""
    try:
        with Image.open(path) as source:
            image = source.convert("RGBA")
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        logger.warning("Logo illisible (%s) : filigrane ignoré. %s", path, exc)
        return None
    image.thumbnail((MAX_PIXELS, MAX_PIXELS), Image.Resampling.LANCZOS)
    alpha = image.getchannel("A").point(lambda value: int(value * opacity))
    image.putalpha(alpha)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return ImageReader(buffer), image.width, image.height


def draw_watermark(
    canvas: Any,
    page_width: float,
    page_height: float,
    logo_path: Path | str | None,
    *,
    opacity: float = DEFAULT_OPACITY,
    page_ratio: float = DEFAULT_PAGE_RATIO,
) -> bool:
    """Dessine le logo centré sur la page. Retourne True si le filigrane a été posé."""
    if not logo_path:
        return False
    path = Path(logo_path)
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        logger.warning("Logo introuvable (%s) : filigrane ignoré.", path)
        return False
    faded = _faded_logo(str(path), mtime, round(min(max(opacity, 0.0), 1.0), 3))
    if faded is None:
        return False
    reader, px_w, px_h = faded
    scale = min(page_width * page_ratio / px_w, page_height * page_ratio / px_h)
    width, height = px_w * scale, px_h * scale
    canvas.saveState()
    canvas.drawImage(
        reader,
        (page_width - width) / 2,
        (page_height - height) / 2,
        width,
        height,
        mask="auto",
        preserveAspectRatio=True,
    )
    canvas.restoreState()
    return True


def watermark_callbacks(
    logo_path: Path | str | None,
    *,
    opacity: float = DEFAULT_OPACITY,
    page_ratio: float = DEFAULT_PAGE_RATIO,
) -> dict[str, Callable[[Any, Any], None]]:
    """Arguments à passer à `SimpleDocTemplate.build(story, **watermark_callbacks(logo))`.

    Le filigrane est posé au début de chaque page, donc derrière le contenu."""

    def on_page(canvas: Any, doc: Any) -> None:
        width, height = doc.pagesize
        draw_watermark(canvas, width, height, logo_path, opacity=opacity, page_ratio=page_ratio)

    return {"onFirstPage": on_page, "onLaterPages": on_page}