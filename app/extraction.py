import json
import re
from urllib.parse import urlsplit, urljoin
from bs4 import BeautifulSoup
from pydantic import ValidationError
from .schemas import Ingredient, RecipeData, Step
from .fetcher import fetch


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


def microdata_steps(html: str) -> list[str]:
    """Read all HowToStep nodes, not just the first text in a HowToSection."""
    soup = BeautifulSoup(html, "html.parser")
    steps = []
    for container in soup.select('[itemprop~="recipeInstructions"]'):
        # A nested instruction scope is already handled by its outer scope.
        if container.find_parent(attrs={"itemprop": "recipeInstructions"}):
            continue
        nodes = container.select('[itemtype$="/HowToStep"]')
        if not nodes:
            nodes = [container]
        for node in nodes:
            texts = node.select('[itemprop~="text"]')
            if not texts:
                texts = [node]
            fragments = []
            for text in texts:
                content = BeautifulSoup(str(text), "html.parser")
                for unwanted in content.select('script, style, meta'):
                    unwanted.decompose()
                for image in content.find_all("img"):
                    # Recipe sites use icons for essential machine settings.
                    # Rezeptwelt also supplies a neighbouring text equivalent.
                    label = image.find_next_sibling()
                    if label and "tmrc-custom-buttons-name" in label.get("class", []):
                        image.decompose()
                    else:
                        image.replace_with(image.get("alt") or image.get("title") or "")
                fragment = plain(content.get_text(" ", strip=True))
                if fragment:
                    fragments.append(fragment)
            if fragments:
                steps.append(" ".join(fragments))
    return steps


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
    host = (urlsplit(url).hostname or "").lower()
    if host in {"monsieur-cuisine.com", "www.monsieur-cuisine.com"}:
        recipe = monsieur_cuisine(html, url)
        if recipe is not None:
            return recipe
    raw = jsonld_recipe(html) or {}
    fallback = scraper_data(html, url)
    instructions = microdata_steps(html)
    existing = step_texts(raw.get("recipeInstructions") or fallback.get("steps"))
    if instructions and len(instructions) >= len(existing) and sum(map(len, instructions)) >= sum(map(len, existing)):
        raw["recipeInstructions"] = instructions
    recipe = normalize(raw, url, fallback)
    if host in {"josemola.de", "www.josemola.de"}:
        # JSON-LD flattens the dough groups; keep the visible ingredient blocks.
        ingredients = []
        for block in BeautifulSoup(html, "html.parser").select("section.ingredients .ingredients-blocks > .block"):
            heading = block.select_one("h3")
            group = plain(heading.get_text(" ", strip=True)) if heading else None
            for row in block.select("li"):
                amount = row.select_one(".amount")
                name = row.select_one(".title")
                if name and plain(name.get_text(" ", strip=True)):
                    text = " ".join(node.get_text(" ", strip=True) for node in (amount, name) if node)
                    ingredients.append(ingredient(text).model_copy(update={"group": group}))
        if len(ingredients) >= len(recipe.ingredients):
            recipe.ingredients = ingredients
    if host in {"chefkoch.de", "www.chefkoch.de"}:
        # JSON-LD flattens the groups. Read every visible ingredient table,
        # keeping repeated ingredients (e.g. flour in both dough and crumble).
        ingredients = []
        for table in BeautifulSoup(html, "html.parser").select("table.ds-ingredients-table"):
            group = plain(table.select_one("h3").get_text()) if table.select_one("h3") else None
            for row in table.select("tbody tr"):
                cells = row.find_all("td", recursive=False)
                if len(cells) == 2:
                    text = plain(" ".join(cell.get_text(" ", strip=True) for cell in cells))
                    if text:
                        ingredients.append(ingredient(text).model_copy(update={"group": group}))
        if len(ingredients) >= len(recipe.ingredients):
            recipe.ingredients = ingredients
    return recipe


def monsieur_cuisine(html: str, url: str) -> RecipeData | None:
    for script in BeautifulSoup(html, "html.parser").find_all("script"):
        text = script.string or script.get_text()
        match = re.search(r"\bwindow\.siteConfig\s*=\s*", text)
        if not match:
            continue
        try:
            config, _ = json.JSONDecoder().raw_decode(text[match.end():])
        except ValueError:
            continue
        if not isinstance(config, dict):
            continue
        recipe_id = config.get("recipeId")
        if type(recipe_id) is not int or recipe_id <= 0:
            continue
        # Fixed public endpoint; never trust an API URL supplied by the page.
        language = urlsplit(url).path.split("/")[1]
        locales = {"de": "de-DE", "en": "en-GB", "fr": "fr-FR", "es": "es-ES", "it": "it-IT", "pt-pt": "pt-PT"}
        data, _, _ = fetch(
            f"https://mc-api.tecpal.com/api/v2/recipes/{recipe_id}",
            content_types=("application/json",),
            headers={"Accept-Language": locales.get(language, language), "device-type": "web"},
        )
        try:
            raw = json.loads(data)["data"]["recipe"]
            servings = raw["servingSizes"]
            serving = next((s for s in servings if s["id"] == raw.get("defaultServingSizeId")), servings[0])
            items = serving["ingredients"]
            if any(not plain(item.get("name")) for item in items):
                raise ValueError("Missing ingredient names")
            texts = [" ".join(str(item[key]) for key in ("amount", "unit", "name") if item.get(key) not in (None, "")) for item in items]
            recipe = normalize({
                "name": raw.get("name"), "description": raw.get("description"),
                "author": raw.get("author"), "image": (raw.get("thumbnail") or {}).get("landscape"),
                "recipeYield": " ".join(str(serving[k]) for k in ("amount", "servingUnit") if serving.get(k) is not None),
                "prep_minutes": serving.get("preparationDuration"), "total_minutes": serving.get("duration"),
                "recipeCategory": raw.get("categories"), "keywords": raw.get("tags"),
                "recipeIngredient": texts,
                # Full prose includes device settings and tips, unlike step titles.
                "recipeInstructions": serving.get("instruction"),
            }, url)
            groups = {g["id"]: plain(g.get("name")) for g in serving.get("ingredientGroups", [])}
            for item, source in zip(recipe.ingredients, items):
                item.group = groups.get(source.get("ingredientGroupId"))
            return recipe
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ExtractionError("Die Monsieur-Cuisine-Rezeptdaten sind unvollständig oder ungültig.") from exc
    return None
