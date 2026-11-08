"""Private-chat Telegram importer using the Bot API's long polling."""
import logging
import re
import time

import httpx
from pydantic import ValidationError
from sqlalchemy.orm import Session

from .config import settings
from .database import RecipeRecord, SessionLocal, TelegramPdfRequest, TelegramUpdate, init_db
from .extraction import ExtractionError
from .fetcher import FetchError
from .importer import import_recipe_url
from .pdf import render_pdf
from .schemas import ImportRequest

logger = logging.getLogger("simmer.telegram")
URL_PATTERN = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)
PDF_COMMAND = re.compile(r"^/pdf(?:@\w+)?\s+(\d+)\s*$", re.IGNORECASE)
MAX_DOCUMENT_BYTES = 50_000_000


def allowed_user_ids(value: str) -> set[int]:
    try:
        ids = {int(part.strip()) for part in value.split(",") if part.strip()}
    except ValueError as exc:
        raise ValueError("TELEGRAM_ALLOWED_USER_IDS muss Telegram-Nutzer-IDs enthalten, durch Kommas getrennt.") from exc
    if any(user_id <= 0 for user_id in ids):
        raise ValueError("TELEGRAM_ALLOWED_USER_IDS darf nur positive Telegram-Nutzer-IDs enthalten.")
    return ids


def message_urls(message: dict) -> list[str]:
    text = message.get("text") or message.get("caption") or ""
    urls = [match.group().rstrip(".,;:!?)]}\"") for match in URL_PATTERN.finditer(text)]
    for entity in message.get("entities", []) + message.get("caption_entities", []):
        if entity.get("type") == "text_link" and entity.get("url"):
            urls.append(entity["url"])
    return list(dict.fromkeys(urls))


def handle_update(update: dict, db: Session, allowed_ids: set[int]) -> TelegramUpdate | None:
    message = update.get("message")
    if not isinstance(message, dict):
        return None
    chat = message.get("chat") or {}
    sender = message.get("from") or {}
    if chat.get("type") != "private":
        return None
    update_id = update.get("update_id")
    chat_id = chat.get("id")
    if not isinstance(update_id, int) or not isinstance(chat_id, int):
        return None
    text = (message.get("text") or "").strip()
    if text == "/id":
        existing = db.get(TelegramUpdate, update_id)
        if existing:
            return existing
        reply = f"Deine Telegram-Nutzer-ID: {sender.get('id')}"
        result = TelegramUpdate(update_id=update_id, chat_id=chat_id, reply_text=reply)
        db.add(result)
        db.commit()
        return result
    if sender.get("id") not in allowed_ids:
        return None
    existing = db.get(TelegramUpdate, update_id)
    if existing:
        return existing
    urls = message_urls(message)
    if text.startswith("/start"):
        reply = "Schick mir einen öffentlichen Rezeptlink. Mit /pdf <Rezept-ID> bekommst du ein gespeichertes Rezept als PDF."
    elif text.lower().startswith("/pdf"):
        match = PDF_COMMAND.fullmatch(text)
        if not match:
            reply = "Bitte gib die Rezept-ID an, zum Beispiel /pdf 123."
        else:
            recipe_id = int(match.group(1))
            recipe = db.get(RecipeRecord, recipe_id)
            if recipe is None:
                reply = f"Rezept #{recipe_id} wurde nicht gefunden."
            else:
                reply = f"{recipe.title} (Rezept #{recipe.id})"
                db.add(TelegramPdfRequest(update_id=update_id, recipe_id=recipe_id))
    elif len(urls) != 1:
        reply = "Bitte schick genau einen öffentlichen HTTP- oder HTTPS-Rezeptlink."
    else:
        try:
            url = str(ImportRequest.model_validate({"url": urls[0]}).url)
            recipe = import_recipe_url(url, db)
            reply = f"✅ Gespeichert: {recipe.title} (Rezept #{recipe.id}). Sende /pdf {recipe.id} für das PDF."
        except (ValidationError, FetchError, ExtractionError) as exc:
            db.rollback()
            reply = f"Import fehlgeschlagen: {exc}"

    result = TelegramUpdate(update_id=update_id, chat_id=chat_id, reply_text=reply)
    db.add(result)
    db.commit()
    return result


class TelegramAPI:
    def __init__(self, token: str):
        self.base_url = f"https://api.telegram.org/bot{token}/"
        self.client = httpx.Client(timeout=httpx.Timeout(35.0, connect=10.0))

    def close(self):
        self.client.close()

    def call(self, method: str, payload: dict, *, files: dict | None = None) -> dict:
        try:
            if files is None:
                response = self.client.post(self.base_url + method, json=payload)
            else:
                response = self.client.post(self.base_url + method, data=payload, files=files)
            response.raise_for_status()
            body = response.json()
            if not body.get("ok"):
                raise ValueError("Telegram hat die Anfrage abgelehnt.")
            return body
        except (httpx.HTTPError, ValueError) as exc:
            # HTTP exception strings may contain the token-bearing request URL.
            raise RuntimeError(f"Telegram-API-Fehler bei {method} ({type(exc).__name__}).") from None

    def get_updates(self, offset: int | None) -> list[dict]:
        payload = {"timeout": 25, "allowed_updates": ["message"]}
        if offset is not None:
            payload["offset"] = offset
        return self.call("getUpdates", payload)["result"]

    def send_message(self, chat_id: int, text: str):
        self.call("sendMessage", {"chat_id": chat_id, "text": text})

    def send_document(self, chat_id: int, filename: str, pdf: bytes, caption: str):
        self.call(
            "sendDocument",
            {"chat_id": str(chat_id), "caption": caption},
            files={"document": (filename, pdf, "application/pdf")},
        )


def deliver_reply(result: TelegramUpdate, db: Session, api: TelegramAPI):
    if result.reply_sent:
        return
    pdf_request = db.get(TelegramPdfRequest, result.update_id)
    if pdf_request is None:
        api.send_message(result.chat_id, result.reply_text)
    else:
        recipe = db.get(RecipeRecord, pdf_request.recipe_id)
        if recipe is None:
            api.send_message(result.chat_id, "Das Rezept wurde inzwischen gelöscht.")
        else:
            try:
                pdf = render_pdf(recipe, image_data=recipe.image_data)
            except Exception:
                logger.exception("PDF-Rendering fehlgeschlagen für Rezept %s", recipe.id)
                api.send_message(result.chat_id, "Das PDF konnte nicht erstellt werden.")
            else:
                if len(pdf) > MAX_DOCUMENT_BYTES:
                    api.send_message(result.chat_id, "Das PDF ist für Telegram zu groß.")
                else:
                    api.send_document(result.chat_id, f"simmer-rezept-{recipe.id}.pdf", pdf, result.reply_text)
    result.reply_sent = True
    db.commit()


def run():
    if not settings.telegram_bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN fehlt.")
    allowed_ids = allowed_user_ids(settings.telegram_allowed_user_ids)
    init_db()
    api = TelegramAPI(settings.telegram_bot_token)
    offset = None
    logger.info("Telegram-Import gestartet für %d freigegebene Nutzer.", len(allowed_ids))
    try:
        while True:
            try:
                for update in api.get_updates(offset):
                    with SessionLocal() as db:
                        result = handle_update(update, db, allowed_ids)
                        if result:
                            deliver_reply(result, db, api)
                    offset = update["update_id"] + 1
            except (RuntimeError, httpx.HTTPError) as exc:
                logger.warning("Telegram vorübergehend nicht erreichbar: %s", type(exc).__name__)
                time.sleep(5)
    finally:
        api.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        run()
    except KeyboardInterrupt:
        pass
