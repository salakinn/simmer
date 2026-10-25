from io import BytesIO
from pathlib import Path

from pypdf import PdfReader

from app.extraction import extract
from app.pdf import render_pdf

URL = 'https://josemola.de/rezepte/roggenvollkorn-sauerteigbrot/'
HTML = Path('tests/fixtures/josemola.html').read_text()


def test_dough_groups_and_pdf():
    recipe = extract(HTML, URL)
    assert [(item.text, item.group) for item in recipe.ingredients] == [
        ('400 g Roggenvollkornmehl', 'Hauptteig'),
        ('240 g Wasser', 'Hauptteig'),
        ('40 g Goldsaft', 'Hauptteig'),
        ('17 g Salz', 'Hauptteig'),
        ('310 g Roggenvollkornmehl', 'Sauerteig'),
        ('310 g Wasser', 'Sauerteig'),
        ('80 g Anstellgut', 'Sauerteig'),
    ]
    pdf = PdfReader(BytesIO(render_pdf(recipe)))
    text = '\n'.join(page.extract_text() for page in pdf.pages)
    assert 'Hauptteig' in text
    assert 'Sauerteig' in text
    assert '400 g Roggenvollkornmehl' in text
    assert '310 g Roggenvollkornmehl' in text


def test_incomplete_visible_list_keeps_complete_jsonld():
    recipe = extract(HTML.replace('class="title"', 'class="missing"', 1), URL)
    assert len(recipe.ingredients) == 7
    assert recipe.ingredients[0].text == '400 g Roggenvollkornmehl'
