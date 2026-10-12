import base64
import logging
from contextlib import asynccontextmanager
from urllib.parse import urljoin
from bs4 import UnicodeDammit
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session
from .config import settings
from .database import RecipeRecord, get_db, init_db
from .extraction import ExtractionError, extract, ingredient
from .fetcher import FetchError, fetch
from .pdf import render_pdf
from .schemas import ImportRequest, RecipeData, RecipeOut, RecipeUpdate

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("simmer")
logging.getLogger("weasyprint.progress").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Simmer", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"error": "validation_error", "detail": "Die Eingaben sind ungültig.", "fields": [{"field": ".".join(map(str, e["loc"])), "message": e["msg"]} for e in exc.errors()]})


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, dict) else {"error": "http_error", "detail": str(exc.detail)}
    return JSONResponse(status_code=exc.status_code, content=detail)


@app.exception_handler(FetchError)
async def fetch_error(request: Request, exc: FetchError):
    logger.warning("Import abgelehnt: %s", exc)
    return JSONResponse(status_code=400, content={"error": "fetch_error", "detail": str(exc)})


@app.exception_handler(ExtractionError)
async def extraction_error(request: Request, exc: ExtractionError):
    logger.info("Rezeptextraktion fehlgeschlagen: %s", exc)
    return JSONResponse(status_code=422, content={"error": "extraction_error", "detail": str(exc)})


def get_recipe(db: Session, recipe_id: int) -> RecipeRecord:
    recipe = db.get(RecipeRecord, recipe_id)
    if recipe is None:
        raise HTTPException(status_code=404, detail={"error": "not_found", "detail": "Rezept nicht gefunden."})
    return recipe


def as_output(record: RecipeRecord) -> RecipeOut:
    return RecipeOut.model_validate(record).model_copy(update={"has_image": bool(record.image_data)})


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/recipes/{recipe_id}", response_class=HTMLResponse)
def recipe_page(request: Request, recipe_id: int, db: Session = Depends(get_db)):
    get_recipe(db, recipe_id)
    return templates.TemplateResponse(request, "detail.html", {"recipe_id": recipe_id})


@app.post("/api/recipes/import", response_model=RecipeOut, status_code=201)
def import_recipe(body: ImportRequest, db: Session = Depends(get_db)):
    html_bytes, final_url, _ = fetch(str(body.url))
    html = UnicodeDammit(html_bytes, is_html=True).unicode_markup or html_bytes.decode("utf-8", "replace")
    data = extract(html, final_url)
    values = data.model_dump()
    image_data = None
    if data.image_url:
        try:
            image_url = urljoin(final_url, data.image_url)
            image_bytes, image_url, media_type = fetch(image_url, max_bytes=settings.max_image_bytes, content_types=("image/jpeg", "image/png", "image/webp"))
            values["image_url"] = image_url
            image_data = f"data:{media_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"
        except FetchError as exc:
            logger.info("Rezeptbild übersprungen: %s", exc)
    values["ingredients"] = [x.model_dump() for x in data.ingredients]
    values["steps"] = [x.model_dump() for x in data.steps]
    record = RecipeRecord(**values, image_data=image_data)
    db.add(record)
    db.commit()
    db.refresh(record)
    return as_output(record)


@app.get("/api/recipes", response_model=list[RecipeOut])
def list_recipes(db: Session = Depends(get_db)):
    records = db.scalars(select(RecipeRecord).order_by(RecipeRecord.created_at.desc(), RecipeRecord.id.desc())).all()
    return [as_output(record) for record in records]


@app.get("/api/recipes/{recipe_id}", response_model=RecipeOut)
def read_recipe(recipe_id: int, db: Session = Depends(get_db)):
    return as_output(get_recipe(db, recipe_id))


@app.put("/api/recipes/{recipe_id}", response_model=RecipeOut)
def update_recipe(recipe_id: int, body: RecipeUpdate, db: Session = Depends(get_db)):
    record = get_recipe(db, recipe_id)
    values = body.model_dump()
    values["ingredients"] = [(ingredient(x.text) if x.quantity is None and x.unit is None and x.name is None else x).model_dump() for x in body.ingredients]
    values["steps"] = [x.model_dump() for x in body.steps]
    old_image_url = record.image_url
    new_image_data = record.image_data
    if old_image_url != body.image_url:
        new_image_data = None
        if body.image_url:
            image_bytes, image_url, media_type = fetch(body.image_url, max_bytes=settings.max_image_bytes, content_types=("image/jpeg", "image/png", "image/webp"))
            values["image_url"] = image_url
            new_image_data = f"data:{media_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"
    for key, value in values.items():
        setattr(record, key, value)
    record.image_data = new_image_data
    record.version += 1
    db.commit()
    db.refresh(record)
    return as_output(record)


@app.delete("/api/recipes/{recipe_id}", status_code=204)
def delete_recipe(recipe_id: int, db: Session = Depends(get_db)):
    record = get_recipe(db, recipe_id)
    db.delete(record)
    db.commit()
    return Response(status_code=204)


@app.get("/api/recipes/{recipe_id}/pdf")
def recipe_pdf(recipe_id: int, db: Session = Depends(get_db)):
    record = get_recipe(db, recipe_id)
    try:
        pdf = render_pdf(record, image_data=record.image_data)
    except Exception:
        logger.exception("PDF-Rendering fehlgeschlagen für Rezept %s", recipe_id)
        raise HTTPException(status_code=500, detail={"error": "pdf_error", "detail": "Das PDF konnte nicht erstellt werden."})
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="simmer-rezept-{recipe_id}.pdf"'})


@app.get("/api/recipes/{recipe_id}/image")
def recipe_image(recipe_id: int, db: Session = Depends(get_db)):
    record = get_recipe(db, recipe_id)
    if not record.image_data:
        raise HTTPException(status_code=404, detail={"error": "not_found", "detail": "Bild nicht gefunden."})
    header, encoded = record.image_data.split(",", 1)
    media_type = header.removeprefix("data:").removesuffix(";base64")
    return Response(base64.b64decode(encoded), media_type=media_type, headers={"Cache-Control": "public, max-age=3600"})
