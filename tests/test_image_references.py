import base64
import json
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.extraction import extract
from app.importer import import_recipe_url


URL = "https://recipes.example/pancakes"
IMAGE = "https://images.example/pancakes.jpg"


def recipe_html(image, *nodes):
    recipe = {"@type": "Recipe", "name": "Pfannkuchen", "image": image,
              "recipeIngredient": ["200 g Mehl"], "recipeInstructions": ["Teig verrühren."]}
    return '<script type="application/ld+json">' + json.dumps({"@graph": [recipe, *nodes]}) + '</script>'


@pytest.mark.parametrize("image,nodes", [
    (IMAGE, []),
    ({"contentUrl": IMAGE}, []),
    ({"@id": URL + "#primaryimage"}, [{"@id": URL + "#primaryimage", "@type": "ImageObject", "url": IMAGE}]),
    ([{"@id": "#missing"}, {"@id": "#primaryimage"}], [{"@id": URL + "#primaryimage", "contentUrl": IMAGE}]),
])
def test_image_formats_and_graph_references(image, nodes):
    with patch('app.extraction.scraper_data', return_value={}):
        assert extract(recipe_html(image, *nodes), URL).image_url == IMAGE


def test_image_reference_in_separate_script():
    html = recipe_html({"@id": "#primaryimage"})
    html += '<script type="application/ld+json">' + json.dumps(
        {"@id": "#primaryimage", "@type": "ImageObject", "url": "/picture.jpg"}) + '</script>'
    with patch('app.extraction.scraper_data', return_value={}):
        assert extract(html, URL).image_url == "https://recipes.example/picture.jpg"


@pytest.mark.parametrize("nodes", [[], [
    {"@id": "#primaryimage", "@type": "ImageObject", "url": {"@id": "#other"}},
    {"@id": "#other", "url": {"@id": "#primaryimage"}},
]])
def test_unresolved_or_cyclic_image_reference_uses_scraper_fallback(nodes):
    html = recipe_html({"@id": "#primaryimage"}, *nodes)
    with patch('app.extraction.scraper_data', return_value={"image_url": IMAGE}):
        assert extract(html, URL).image_url == IMAGE
    with patch('app.extraction.scraper_data', return_value={}):
        assert extract(html, URL).image_url is None


def test_import_downloads_and_stores_referenced_image():
    html = recipe_html({"@id": "#primaryimage"}, {"@id": "#primaryimage", "url": IMAGE})
    image_bytes = b'referenced-image-bytes'
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db, patch('app.extraction.scraper_data', return_value={}), patch(
        'app.importer.fetch', side_effect=[(html.encode(), URL, 'text/html'), (image_bytes, IMAGE, 'image/jpeg')]
    ) as fetch:
        record = import_recipe_url(URL, db)
        assert record.image_url == IMAGE
        assert record.image_data == 'data:image/jpeg;base64,' + base64.b64encode(image_bytes).decode()
        assert fetch.call_args.args == (IMAGE,)
        assert fetch.call_args.kwargs['content_types'] == ('image/jpeg', 'image/png', 'image/webp')
    engine.dispose()
