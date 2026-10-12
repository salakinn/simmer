import json
import re
from urllib.parse import urlsplit, urljoin
from bs4 import BeautifulSoup
from pydantic import ValidationError
from .schemas import Ingredient, RecipeData, Step


class ExtractionError(Exception):
    pass


def plain(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("name") or value.get("text") or value.get("@value")
    if isinstance(value, list):
        value = ", ".join(filter(None, (plain(x) for x in value)))
    if value is None:
        return None
    text = BeautifulSoup(str(value), "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).strip() or None


def duration(value) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return max(0, int(value))
    match = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", str(value), re.I)
    if match:
        days, hours, minutes, seconds = (int(x or 0) for x in match.groups())
        return days * 1440 + hours * 60 + minutes + (1 if seconds else 0)
    return None


def strings(value) -> list[str]:
    if value is None:
        return []
    parts = value if isinstance(value, list) else str(value).split(",")
    return [text for x in parts if (text := plain(x))]


def ingredient(value) -> Ingredient:
    text = plain(value) or ""
    match = re.match(r"^([\d½¼¾⅓⅔⅛⅜⅝⅞]+(?:[.,/\s-][\d½¼¾⅓⅔⅛⅜⅝⅞]+)?)\s+(?:(g|kg|ml|l|EL|TL|Pck\.?|Stück|cups?|tbsp|tsp)\s+)?(.+)$", text, re.I)
    if match:
        return Ingredient(text=text, quantity=match.group(1), unit=match.group(2), name=match.group(3))
    return Ingredient(text=text, name=text)


def step_texts(value) -> list[str]:
    if isinstance(value, str):
        return [x for line in value.splitlines() if (x := plain(line))]
    if isinstance(value, dict):
        if "itemListElement" in value:
            return step_texts(value["itemListElement"])
        text = plain(value.get("text") or value.get("name"))
        return [text] if text else []
    if isinstance(value, list):
        return [text for item in value for text in step_texts(item)]
    return []


def recipe_nodes(obj):
    if isinstance(obj, list):
        for item in obj:
            yield from recipe_nodes(item)
    elif isinstance(obj, dict):
        types = obj.get("@type", [])
        types = types if isinstance(types, list) else [types]
        if any(str(t).lower().split("/")[-1] == "recipe" for t in types):
            yield obj
        for key in ("@graph", "mainEntity", "itemListElement"):
            if key in obj:
                yield from recipe_nodes(obj[key])


def jsonld_recipe(html: str) -> dict | None:
    soup = BeautifulSoup(html, "html.parser")
    candidates = []
    for tag in soup.select('script[type="application/ld+json"]'):
        try:
            raw = json.loads(tag.string or tag.get_text())
            candidates.extend(recipe_nodes(raw))
        except (ValueError, TypeError):
            continue
    return max(candidates, key=lambda x: len(x.get("recipeIngredient", [])) + len(step_texts(x.get("recipeInstructions"))), default=None)


def scraper_data(html: str, url: str) -> dict:
    try:
        from recipe_scrapers import scrape_html
        scraper = scrape_html(html, org_url=url, supported_only=False)
        result = {}
        methods = {"title": "title", "description": "description", "author": "author", "servings": "yields", "prep_minutes": "prep_time", "cook_minutes": "cook_time", "total_minutes": "total_time", "image_url": "image", "ingredients": "ingredients", "steps": "instructions_list", "categories": "category", "tags": "keywords"}
        for key, method in methods.items():
            try:
                result[key] = getattr(scraper, method)()
            except (AttributeError, ValueError, TypeError, NotImplementedError):
                pass
        return result
    except Exception:
        return {}


def normalize(raw: dict, url: str, fallback: dict | None = None) -> RecipeData:
    fallback = fallback or {}
    def pick(key, alternate=None):
        for source in (raw, fallback):
            for name in (key, alternate):
                if name and source.get(name) not in (None, "", []):
                    return source[name]
        return None
    ingredients = pick("recipeIngredient", "ingredients") or []
    if isinstance(ingredients, str):
        ingredients = ingredients.splitlines()
    instructions = pick("recipeInstructions", "steps") or []
    if isinstance(instructions, str) and not instructions.strip():
        instructions = []
    image = pick("image", "image_url")
    if isinstance(image, list):
        image = image[0] if image else None
    if isinstance(image, dict):
        image = image.get("url") or image.get("contentUrl")
    author = pick("author")
    servings = pick("recipeYield", "servings")
    if isinstance(servings, list):
        servings = servings[0] if servings else None
    image_url = urljoin(url, plain(image)) if plain(image) else None
    if image_url and urlsplit(image_url).scheme.lower() not in {"http", "https"}:
        image_url = None
    try:
        return RecipeData(
            title=plain(pick("name", "title")) or "",
            description=plain(pick("description")),
            source_type="url",
            source_name=urlsplit(url).hostname,
            source_url=url,
            author=plain(author),
            servings=plain(servings),
            prep_minutes=duration(pick("prepTime", "prep_minutes")),
            cook_minutes=duration(pick("cookTime", "cook_minutes")),
            total_minutes=duration(pick("totalTime", "total_minutes")),
            image_url=image_url,
            categories=strings(pick("recipeCategory", "categories")),
            tags=strings(pick("keywords", "tags")),
            ingredients=[ingredient(x) for x in ingredients if plain(x)],
            steps=[Step(text=x) for x in step_texts(instructions)],
        )
    except ValidationError as exc:
        raise ExtractionError("Das Rezept enthält keinen vollständigen Titel, keine Zutaten oder keine Zubereitungsschritte.") from exc


def extract(html: str, url: str) -> RecipeData:
    raw = jsonld_recipe(html) or {}
    fallback = scraper_data(html, url)
    return normalize(raw, url, fallback)
