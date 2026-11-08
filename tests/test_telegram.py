from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.database import Base, RecipeRecord, TelegramPdfRequest, TelegramUpdate
from app.telegram_bot import TelegramAPI, allowed_user_ids, deliver_reply, handle_update, message_urls

HTML = Path("tests/fixtures/recipe.html").read_bytes()
URL = "https://recipes.example/ofengemuese"


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/telegram.db")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        yield session
    engine.dispose()


def update(update_id=1, user_id=123, text=URL, chat_type="private"):
    return {"update_id": update_id, "message": {"from": {"id": user_id}, "chat": {"id": user_id, "type": chat_type}, "text": text}}


def test_telegram_import_and_duplicate_update(db):
    with patch("app.importer.fetch", return_value=(HTML, URL, "text/html")):
        first = handle_update(update(), db, {123})
        second = handle_update(update(), db, {123})
    assert first.update_id == second.update_id
    assert first.reply_text.startswith("✅ Gespeichert: Ofengemüse")
    assert "/pdf 1" in first.reply_text
    assert db.scalar(select(func.count()).select_from(RecipeRecord)) == 1
    assert db.scalar(select(func.count()).select_from(TelegramUpdate)) == 1


def test_only_allowed_private_users_can_import(db):
    assert handle_update(update(user_id=456), db, {123}) is None
    assert handle_update(update(chat_type="group"), db, {123}) is None
    assert db.scalar(select(func.count()).select_from(RecipeRecord)) == 0


def test_id_and_import_error(db):
    identity = handle_update(update(text="/id", user_id=456), db, set())
    assert identity.reply_text == "Deine Telegram-Nutzer-ID: 456"
    with patch("app.importer.fetch", return_value=(b"<html></html>", URL, "text/html")):
        error = handle_update(update(update_id=2), db, {123})
    assert error.reply_text.startswith("Import fehlgeschlagen:")
    assert db.scalar(select(func.count()).select_from(RecipeRecord)) == 0


def test_link_extraction_and_configuration():
    assert message_urls({"text": "Hier: https://example.com/rezept."}) == ["https://example.com/rezept"]
    assert message_urls({"text": "Rezept", "entities": [{"type": "text_link", "url": URL}]}) == [URL]
    assert allowed_user_ids("123, 456") == {123, 456}
    assert allowed_user_ids("") == set()
    with pytest.raises(ValueError):
        allowed_user_ids("abc")


def test_pdf_command_sends_saved_recipe_once(db):
    with patch("app.importer.fetch", return_value=(HTML, URL, "text/html")):
        handle_update(update(), db, {123})
    request = handle_update(update(update_id=2, text="/pdf 1"), db, {123})
    assert db.get(TelegramPdfRequest, 2).recipe_id == 1

    class FakeAPI:
        def __init__(self):
            self.documents = []
            self.messages = []
        def send_document(self, *args):
            self.documents.append(args)
        def send_message(self, *args):
            self.messages.append(args)

    api = FakeAPI()
    deliver_reply(request, db, api)
    deliver_reply(handle_update(update(update_id=2, text="/pdf 1"), db, {123}), db, api)
    assert len(api.documents) == 1
    chat_id, filename, pdf, caption = api.documents[0]
    assert chat_id == 123
    assert filename == "simmer-rezept-1.pdf"
    assert pdf.startswith(b"%PDF-")
    assert "Ofengemüse" in caption
    assert api.messages == []


def test_pdf_command_errors_and_access(db):
    assert handle_update(update(text="/pdf 1", user_id=456), db, {123}) is None
    missing = handle_update(update(update_id=2, text="/pdf 123"), db, {123})
    assert "nicht gefunden" in missing.reply_text
    assert db.get(TelegramPdfRequest, 2) is None
    invalid = handle_update(update(update_id=3, text="/pdf"), db, {123})
    assert "/pdf 123" in invalid.reply_text


def test_telegram_document_upload_is_multipart():
    import httpx

    api = TelegramAPI("test-token")
    response = httpx.Response(200, json={"ok": True}, request=httpx.Request("POST", "https://api.telegram.org/bottest-token/sendDocument"))
    with patch.object(api.client, "post", return_value=response) as post:
        api.send_document(123, "recipe.pdf", b"%PDF-test", "Rezept")
    api.close()
    assert post.call_args.args[0].endswith("/sendDocument")
    assert post.call_args.kwargs["data"] == {"chat_id": "123", "caption": "Rezept"}
    assert post.call_args.kwargs["files"]["document"] == ("recipe.pdf", b"%PDF-test", "application/pdf")
