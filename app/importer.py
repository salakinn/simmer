"""Shared URL import used by the web API and the Telegram bot."""
import base64
import logging
from urllib.parse import urljoin

from bs4 import UnicodeDammit
from sqlalchemy.orm import Session

from .config import settings
from .database import RecipeRecord
from .extraction import extract
from .fetcher import FetchError, fetch
from .schemas import RecipePreview

logger = logging.getLogger("simmer")


def preview_recipe_url(url: str) -> RecipePreview:
    """Extract a recipe and its image without writing to the database."""
    html_bytes, final_url, _ = fetch(url)
    html = UnicodeDammit(html_bytes, is_html=True).unicode_markup or html_bytes.decode("utf-8", "replace")
    data = extract(html, final_url)
    values = data.model_dump()
    image_data = None
    if data.image_url:
        try:
            image_url = urljoin(final_url, data.image_url)
            image_bytes, image_url, media_type = fetch(
                image_url,
                max_bytes=settings.max_image_bytes,
                content_types=("image/jpeg", "image/png", "image/webp"),
            )
            values["image_url"] = image_url
            image_data = f"data:{media_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"
        except FetchError as exc:
            logger.info("Rezeptbild übersprungen: %s", exc)
    return RecipePreview(**values, image_upload=image_data)


def import_recipe_url(url: str, db: Session) -> RecipeRecord:
    """Add an imported recipe to the session; the caller commits the transaction."""
    preview = preview_recipe_url(url)
    record = RecipeRecord(**preview.model_dump(exclude={"image_upload"}), image_data=preview.image_upload)
    db.add(record)
    db.flush()
    return record
