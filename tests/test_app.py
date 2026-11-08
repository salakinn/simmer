import ipaddress
from pathlib import Path
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base, get_db
from app.extraction import ExtractionError, duration, extract, jsonld_recipe, microdata_steps, normalize
from app.fetcher import FetchError, fetch, resolve_public_ip, validate_url
from app.main import app

HTML = Path('tests/fixtures/recipe.html').read_text()
URL = 'https://recipes.example/ofengemuese'


@pytest.fixture
def client(tmp_path):
    engine = create_engine(f'sqlite:///{tmp_path}/test.db', connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    def override():
        with Session() as db:
            yield db
    app.dependency_overrides[get_db] = override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    engine.dispose()


def test_jsonld_and_normalization():
    raw = jsonld_recipe(HTML)
    assert raw['name'] == 'Ofengemüse'
    recipe = extract(HTML, URL)
    assert recipe.title == 'Ofengemüse'
    assert recipe.prep_minutes == 15
    assert recipe.total_minutes == 50
    assert recipe.ingredients[0].quantity == '500'
    assert recipe.ingredients[0].unit == 'g'
    assert [s.text for s in recipe.steps] == ['Ofen auf 200 Grad vorheizen.', 'Gemüse schneiden.', '35 Minuten backen.']
    assert recipe.tags == ['vegetarisch', 'einfach']


def test_incomplete_recipe():
    with pytest.raises(ExtractionError):
        normalize({'name':'Ohne Inhalt'}, URL)
    assert duration('PT1H30M') == 90
    assert duration('unbekannt') is None


def test_link_preview_is_not_saved_until_reviewed(client):
    with patch('app.importer.fetch', return_value=(HTML.encode(), URL, 'text/html')):
        response = client.post('/api/recipes/preview', json={'url': URL})
        second = client.post('/api/recipes/preview', json={'url': URL})
    assert response.status_code == second.status_code == 200
    draft = response.json()
    assert 'id' not in draft
    assert draft['title'] == 'Ofengemüse'
    assert draft['source_url'] == URL
    assert client.get('/api/recipes').json() == []
    draft['title'] = 'Mein geprüftes Gemüse'
    draft['servings'] = '4'
    draft['ingredients'][0] = {'text': '750 g Kartoffeln', 'group': 'Gemüse'}
    draft['steps'][0]['text'] = 'Ofen auf 180 Grad vorheizen.'
    with patch('app.main.fetch') as fetch_mock:
        saved = client.post('/api/recipes', json=draft)
        fetch_mock.assert_not_called()
    assert saved.status_code == 201, saved.text
    recipe = saved.json()
    assert recipe['title'] == 'Mein geprüftes Gemüse'
    assert recipe['source_type'] == 'url'
    assert recipe['source_url'] == URL
    assert recipe['servings'] == '4'
    assert recipe['ingredients'][0]['quantity'] == '750'
    assert recipe['ingredients'][0]['group'] == 'Gemüse'
    assert recipe['steps'][0]['text'] == 'Ofen auf 180 Grad vorheizen.'
    assert len(client.get('/api/recipes').json()) == 1


def test_preview_image_can_be_saved_or_removed_without_refetch(client):
    import base64
    import json
    from io import BytesIO
    from PIL import Image
    buffer = BytesIO()
    Image.new('RGB', (24, 24), '#a75739').save(buffer, format='PNG')
    image_bytes = buffer.getvalue()
    raw = {'@type': 'Recipe', 'name': 'Suppe', 'recipeIngredient': ['1 l Wasser'],
           'recipeInstructions': ['Kochen.'], 'image': 'https://recipes.example/suppe.png'}
    html = '<script type="application/ld+json">' + json.dumps(raw) + '</script>'
    with patch('app.importer.fetch', side_effect=[(html.encode(), URL, 'text/html'),
                                               (image_bytes, raw['image'], 'image/png')]):
        preview = client.post('/api/recipes/preview', json={'url': URL})
    assert preview.status_code == 200, preview.text
    draft = preview.json()
    assert draft['image_upload'] == 'data:image/png;base64,' + base64.b64encode(image_bytes).decode()
    assert client.get('/api/recipes').json() == []
    with patch('app.main.fetch') as fetch_mock:
        saved = client.post('/api/recipes', json=draft)
        fetch_mock.assert_not_called()
    assert saved.status_code == 201
    assert saved.json()['has_image'] is True
    assert client.get(f"/api/recipes/{saved.json()['id']}/image").content == image_bytes
    draft['image_upload'] = None
    draft['remove_image'] = True
    with patch('app.main.fetch') as fetch_mock:
        without_image = client.post('/api/recipes', json=draft)
        fetch_mock.assert_not_called()
    assert without_image.status_code == 201
    assert without_image.json()['has_image'] is False
    assert without_image.json()['image_url'] is None


def test_failed_preview_does_not_create_recipe(client):
    with patch('app.importer.fetch', return_value=(b'<html></html>', URL, 'text/html')):
        response = client.post('/api/recipes/preview', json={'url': URL})
    assert response.status_code == 422
    assert client.post('/api/recipes/preview', json={'url': 'file:///etc/passwd'}).status_code == 422
    assert client.get('/api/recipes').json() == []


def test_manual_recipe_creation(client):
    assert client.get('/recipes/new').status_code == 200
    assert 'data-new-recipe="true"' in client.get('/recipes/new').text
    assert '/recipes/new' in client.get('/').text
    with patch('app.main.fetch') as fetch_mock:
        response = client.post('/api/recipes', json={
            'title': '  Omas Pfannkuchen  ', 'servings': '2', 'prep_minutes': 10,
            'ingredients': [{'text': '250 g Mehl', 'group': 'Teig'}, {'text': '2 Eier', 'group': 'Teig'}],
            'steps': [{'text': 'Alles verrühren.'}, {'text': 'In der Pfanne backen.'}],
        })
        fetch_mock.assert_not_called()
    assert response.status_code == 201, response.text
    recipe = response.json()
    assert recipe['title'] == 'Omas Pfannkuchen'
    assert recipe['source_type'] == 'manual'
    assert recipe['source_url'] is None
    assert recipe['version'] == 1
    assert recipe['ingredients'][0] == {'text': '250 g Mehl', 'quantity': '250', 'unit': 'g', 'name': 'Mehl', 'group': 'Teig'}
    assert client.get(f"/api/recipes/{recipe['id']}").json() == recipe
    assert client.get('/api/recipes').json() == [recipe]
    assert client.get(f"/recipes/{recipe['id']}").status_code == 200
    assert client.get(f"/api/recipes/{recipe['id']}/pdf").content.startswith(b'%PDF-')


@pytest.mark.parametrize('changes', [
    {'title': '   '}, {'ingredients': []}, {'steps': []},
    {'prep_minutes': -1}, {'source_url': 'file:///tmp/recipe'},
])
def test_invalid_manual_recipe_is_not_saved(client, changes):
    body = {'title': 'Suppe', 'ingredients': [{'text': '1 l Wasser'}], 'steps': [{'text': 'Kochen.'}], **changes}
    assert client.post('/api/recipes', json=body).status_code == 422
    assert client.get('/api/recipes').json() == []


def test_uploaded_recipe_image_create_update_remove(client):
    import base64
    from io import BytesIO
    from PIL import Image
    buffer = BytesIO()
    Image.new('RGB', (32, 24), '#a75739').save(buffer, format='PNG')
    data = buffer.getvalue()
    upload = 'data:image/png;base64,' + base64.b64encode(data).decode()
    body = {'title': 'Suppe mit Bild', 'ingredients': [{'text': '1 l Wasser'}], 'steps': [{'text': 'Kochen.'}], 'image_upload': upload}
    response = client.post('/api/recipes', json=body)
    assert response.status_code == 201, response.text
    recipe = response.json()
    assert recipe['has_image'] is True
    assert recipe['image_url'] is None
    assert 'image_upload' not in recipe
    path = f"/api/recipes/{recipe['id']}"
    image = client.get(path + '/image')
    assert image.headers['content-type'] == 'image/png'
    assert image.content == data
    assert client.get(path + '/pdf').content.startswith(b'%PDF-')
    # Normal text edits preserve the uploaded image.
    recipe['title'] = 'Suppe umbenannt'
    assert client.put(path, json=recipe).json()['has_image'] is True
    assert client.get(path + '/image').content == data
    assert client.put(path, json={**recipe, 'remove_image': True}).json()['has_image'] is False
    assert client.get(path + '/image').status_code == 404
    assert client.put(path, json={**recipe, 'image_upload': upload}).json()['has_image'] is True


@pytest.mark.parametrize('upload', [
    'data:image/svg+xml;base64,PHN2Zz4=',
    'data:image/png;base64,invalid!',
    'data:image/png;base64,bm90IGFuIGltYWdl',
])
def test_invalid_image_does_not_save_recipe(client, upload):
    body = {'title': 'Suppe', 'ingredients': [{'text': 'Wasser'}], 'steps': [{'text': 'Kochen.'}], 'image_upload': upload}
    assert client.post('/api/recipes', json=body).status_code == 422
    assert client.get('/api/recipes').json() == []


def test_image_size_limit(client):
    from app.config import settings
    body = {'title': 'Suppe', 'ingredients': [{'text': 'Wasser'}], 'steps': [{'text': 'Kochen.'}], 'image_upload': 'data:image/png;base64,' + 'A' * 200}
    with patch.object(settings, 'max_image_bytes', 16):
        response = client.post('/api/recipes', json=body)
    assert response.status_code == 422
    assert 'zu groß' in response.json()['detail']
    assert client.get('/api/recipes').json() == []


@pytest.mark.parametrize('url', ['file:///etc/passwd','http://localhost/a','http://127.0.0.1/a','https://169.254.169.254/latest','http://user:pass@example.org/','https://example.org:8443/'])
def test_url_blocked(url):
    with pytest.raises(FetchError):
        scheme, host, port = validate_url(url)
        resolve_public_ip(host, port)


def test_dns_private_and_mixed():
    with patch('socket.getaddrinfo', return_value=[(2,1,6,'',('8.8.8.8',80)),(2,1,6,'',('10.0.0.1',80))]):
        with pytest.raises(FetchError):
            resolve_public_ip('example.org',80)


def test_redirect_revalidated():
    class Response:
        status=302
        def getheader(self,key,default=None): return 'http://127.0.0.1/admin' if key=='Location' else default
    class Connection:
        def __init__(self,*args): pass
        def request(self,*args,**kwargs): pass
        def getresponse(self): return Response()
        def close(self): pass
    with patch('app.fetcher.resolve_public_ip', return_value='8.8.8.8'), patch('app.fetcher.SafeHTTPSConnection',Connection):
        with pytest.raises(FetchError): fetch('https://example.org/test')


def test_crud_import_pdf(client):
    with patch('app.importer.fetch', return_value=(HTML.encode(), URL, 'text/html')):
        response = client.post('/api/recipes/import', json={'url':URL})
    assert response.status_code == 201, response.text
    recipe = response.json()
    rid = recipe['id']
    assert client.get('/api/recipes').json()[0]['id'] == rid
    assert client.get(f'/api/recipes/{rid}').json()['title'] == 'Ofengemüse'
    recipe['title'] = 'Mein Ofengemüse'
    recipe['steps'][0]['text'] = 'Ofen stark vorheizen.'
    updated = client.put(f'/api/recipes/{rid}', json=recipe)
    assert updated.status_code == 200, updated.text
    assert updated.json()['version'] == 2
    pdf = client.get(f'/api/recipes/{rid}/pdf')
    assert pdf.status_code == 200, pdf.text
    assert pdf.content.startswith(b'%PDF-')
    from pypdf import PdfReader
    from io import BytesIO
    pages = PdfReader(BytesIO(pdf.content)).pages
    assert len(pages) == 2
    assert 'Zutaten' in pages[0].extract_text()
    assert 'Zubereitung' not in pages[0].extract_text()
    assert 'Zubereitung' in pages[1].extract_text()
    text = ''.join(page.extract_text() for page in pages)
    assert 'Mein Ofengemüse' in text
    assert 'Ofen stark vorheizen' in text
    assert client.delete(f'/api/recipes/{rid}').status_code == 204
    assert client.get(f'/api/recipes/{rid}').status_code == 404


def test_bad_import_and_validation(client):
    with patch('app.importer.fetch', return_value=(b'<html></html>', URL, 'text/html')):
        response=client.post('/api/recipes/import',json={'url':URL})
    assert response.status_code==422
    assert response.json()['error']=='extraction_error'
    response=client.post('/api/recipes/import',json={'url':'file:///etc/passwd'})
    assert response.status_code==422
    assert response.json()['error']=='validation_error'


def test_pdf_long_recipe_keeps_every_step():
    from app.pdf import render_pdf
    from pypdf import PdfReader
    from io import BytesIO
    recipe = extract(HTML, URL)
    recipe.steps = [type(recipe.steps[0])(text=f'Schritt {i}: ' + 'Gemüse sorgfältig vorbereiten und würzen. '*12) for i in range(1, 31)]
    pdf = render_pdf(recipe)
    pages = PdfReader(BytesIO(pdf)).pages
    assert len(pages) >= 2
    assert 'Zubereitung' not in pages[0].extract_text()
    assert 'Zubereitung' in pages[1].extract_text()
    text = '\n'.join(page.extract_text() for page in pages)
    assert 'Schritt 1:' in text
    assert 'Schritt 30:' in text


def test_pdf_many_ingredients_stay_with_description():
    from app.pdf import render_pdf
    from pypdf import PdfReader
    from io import BytesIO
    recipe = extract(HTML, URL)
    recipe.ingredients = [type(recipe.ingredients[0])(text=f'Zutat {i}: Gemüse und Kräuter') for i in range(1, 51)]
    pages = PdfReader(BytesIO(render_pdf(recipe))).pages
    assert len(pages) == 2
    first = pages[0].extract_text()
    assert 'Zutat 1:' in first
    assert 'Zutat 50:' in first
    assert 'Zubereitung' not in first
    assert 'Zubereitung' in pages[1].extract_text()


def test_pdf_with_stored_image():
    import base64
    from io import BytesIO
    from PIL import Image
    from app.pdf import render_pdf
    picture = Image.new('RGB', (1170, 780), '#b96b42')
    buffer = BytesIO()
    picture.save(buffer, format='PNG')
    image_data = 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()
    recipe = extract(HTML, URL)
    recipe.title = 'Spaghettikürbis mit Schinken und Käse'
    recipe.description = ('Kürbis mal anders – dieses einfache Spaghettikürbis-Rezept schmeckt '
                          'mit der cremigen, käsigen Füllung nach echtem Soulfood! '
                          'Ich liebe das ausgewogene Ofengericht.')
    recipe.ingredients = [type(recipe.ingredients[0])(text=text) for text in (
        '1 Spaghettikürbis, mittelgroß (ca. 1 kg)',
        '150 g Französischer Kräuterfrischkäse (oder andere Sorte wie z. B. Tomate, Paprika)',
        '100 g Kochschinken', '50 g Bergkäse (z. B. Gruyère oder Appenzeller)',
        '5 g Sonnenblumenkerne', '1/4 TL Salz', '1 Msp. Pfeffer',
        '1 Msp. Muskatnuss (frisch gerieben)',
    )]
    pdf = render_pdf(recipe, image_data)
    assert pdf.startswith(b'%PDF-')
    assert len(pdf) > 10000
    from pypdf import PdfReader
    pages = PdfReader(BytesIO(pdf)).pages
    assert 'Zutaten' in pages[0].extract_text()
    assert '1 Msp. Muskatnuss (frisch gerieben)' in pages[0].extract_text()
    assert 'Zubereitung' not in pages[0].extract_text()
    assert 'Zubereitung' in pages[1].extract_text()


def test_scraper_fallback_normalizes_missing_jsonld():
    fallback = {'title':'Nudelsalat','ingredients':['200 g Nudeln'],'steps':['Nudeln kochen.'],'servings':'2'}
    with patch('app.extraction.scraper_data', return_value=fallback):
        recipe = extract('<html><body>Rezept ohne JSON-LD</body></html>', URL)
    assert recipe.title == 'Nudelsalat'
    assert recipe.ingredients[0].unit == 'g'
    assert recipe.steps[0].text == 'Nudeln kochen.'


MC_URL = 'https://www.monsieur-cuisine.com/de/recipe/bayerische-creme-2'
MC_HTML = '<script>window.siteConfig = {"recipeId":225846,"ajaxUrl":"http://127.0.0.1/evil"};</script>'


def test_monsieur_cuisine_api():
    payload = Path('tests/fixtures/monsieur-cuisine.json').read_bytes()
    with patch('app.extraction.fetch', return_value=(payload, MC_URL, 'application/json')) as request:
        recipe = extract(MC_HTML, MC_URL)
    request.assert_called_once_with('https://mc-api.tecpal.com/api/v2/recipes/225846', content_types=('application/json',), headers={'Accept-Language':'de-DE', 'device-type':'web'})
    assert recipe.title == 'Bayerische Creme'
    assert len(recipe.ingredients) == 6
    assert recipe.ingredients[0].name == 'Blattgelatine, weiß'
    assert recipe.total_minutes == 322
    assert recipe.servings == '4 Portionen'
    assert '20 Sekunden/Stufe 10' in recipe.steps[1].text
    assert recipe.steps[-1].text == 'Dazu passt Aprikosenpüree.'


@pytest.mark.parametrize('html', ['<script>window.siteConfig = broken;</script>', '<script>window.siteConfig = {"recipeId":"../../evil"};</script>'])
def test_monsieur_cuisine_invalid_config(html):
    with patch('app.extraction.fetch') as request, pytest.raises(ExtractionError):
        extract(html, MC_URL)
    request.assert_not_called()


def test_other_hosts_do_not_trigger_monsieur_cuisine():
    with patch('app.extraction.fetch') as request, pytest.raises(ExtractionError):
        extract(MC_HTML, 'https://monsieur-cuisine.com.evil.example/recipe')
    request.assert_not_called()


def test_chefkoch_groups_survive_crud_and_pdf(client):
    import json
    from io import BytesIO
    from pypdf import PdfReader
    url = 'https://www.chefkoch.de/rezepte/2204031353338061/Apfelkuchen-mit-Streuseln.html'
    groups = [('Zutaten für den Teig:', [('125 g', 'Butter'), ('250 g', 'Mehl')]), ('Zutaten für den Belag:', [('1.5 kg', 'Äpfel')]), ('Zutaten für die Streusel:', [('150 g', 'Butter'), ('250 g', 'Mehl')])]
    raw = {'@type':'Recipe','name':'Apfelkuchen','recipeIngredient':['125 g Butter','250 g Mehl'],'recipeInstructions':['Backen.']}
    html = '<script type="application/ld+json">' + json.dumps(raw) + '</script>'
    for group, items in groups:
        html += '<table class="ds-ingredients-table"><thead><tr><th><h3>' + group + '</h3></th></tr></thead><tbody>'
        html += ''.join(f'<tr><td>{amount}</td><td>{name}</td></tr>' for amount, name in items) + '</tbody></table>'
    with patch('app.importer.fetch', return_value=(html.encode(), url, 'text/html')):
        response = client.post('/api/recipes/import', json={'url':url})
    assert response.status_code == 201, response.text
    recipe = response.json()
    assert len(recipe['ingredients']) == 5
    assert [i['group'] for i in recipe['ingredients']] == [groups[0][0]]*2 + [groups[1][0]] + [groups[2][0]]*2
    rid = recipe['id']
    recipe['ingredients'] = [{'text':i['text'], 'group':i['group']} for i in recipe['ingredients']]
    updated = client.put(f'/api/recipes/{rid}', json=recipe)
    assert updated.status_code == 200
    assert updated.json()['ingredients'][3]['group'] == groups[2][0]
    assert client.get(f'/api/recipes/{rid}').json()['ingredients'][2]['name'] == 'Äpfel'
    pdf = client.get(f'/api/recipes/{rid}/pdf')
    assert pdf.status_code == 200
    text = '\n'.join(p.extract_text() for p in PdfReader(BytesIO(pdf.content)).pages)
    for group, _ in groups:
        assert group in text
    assert text.count('250 g Mehl') == 2


def test_rezeptwelt_all_steps_and_pdf(client):
    from io import BytesIO
    from pypdf import PdfReader
    html = Path('tests/fixtures/rezeptwelt.html').read_text()
    url = 'https://www.rezeptwelt.de/hauptgerichte-mit-gemuese-rezepte/kuerbislasagne/gqx3jkpj-b4734-092576-cfcd2-9hfik1n7'
    fallback = {'title':'Kürbislasagne', 'ingredients':['300 g Kürbis'], 'steps':['Zwiebel (geviertelt) und Kürbis5 Sek/Stufe 5 zerkleinern.']}
    with patch('app.extraction.scraper_data', return_value=fallback), patch('app.importer.fetch', return_value=(html.encode(), url, 'text/html')):
        response = client.post('/api/recipes/import', json={'url':url})
    assert response.status_code == 201, response.text
    recipe = response.json()
    steps = [step['text'] for step in recipe['steps']]
    assert len(steps) == 6
    assert 'Kürbis 5 Sek/Stufe 5' in steps[0]
    assert '2,50 Min./Varoma/Stufe 1' in steps[1]
    assert steps[1].count('Linkslauf') == 1
    assert '4 Min./100°C/Stufe 1' in steps[2]
    assert '2 Min./100°C/Stufe 1' in steps[3]
    assert 'geriebenen Käse' in steps[4]
    assert '200°C ca. 30 - 40 Minunten' in steps[5]
    assert 'Nicht Teil' not in ' '.join(steps)
    saved = client.get(f"/api/recipes/{recipe['id']}").json()
    assert saved['steps'] == recipe['steps']
    pdf = client.get(f"/api/recipes/{recipe['id']}/pdf")
    assert pdf.status_code == 200
    text = '\n'.join(p.extract_text() for p in PdfReader(BytesIO(pdf.content)).pages)
    assert 'Lasagneplatten' in text
    assert 'überbacken' in text


def test_microdata_does_not_replace_more_complete_jsonld():
    import json
    raw = {'@type':'Recipe', 'name':'Suppe', 'recipeIngredient':['300 g Kürbis'], 'recipeInstructions':['Gemüse vorbereiten.', 'Lange kochen und abschmecken.']}
    html = '<script type="application/ld+json">' + json.dumps(raw) + '</script><div itemprop="recipeInstructions"><span itemprop="text">Kochen.</span></div>'
    recipe = extract(html, URL)
    assert [s.text for s in recipe.steps] == raw['recipeInstructions']


def test_microdata_multiple_scopes_and_icon_only_setting():
    html = '<div itemprop="recipeInstructions" itemtype="https://schema.org/HowToStep"><span itemprop="text">Rühren <img alt="Linkslauf" src="/icon.png">.</span></div><div itemprop="recipeInstructions" itemtype="https://schema.org/HowToStep"><span itemprop="text">Backen.</span></div>'
    assert microdata_steps(html) == ['Rühren Linkslauf .', 'Backen.']


def test_compact_pdf_ingredients_fit_first_page():
    import base64
    from io import BytesIO
    from PIL import Image
    from pypdf import PdfReader
    from app.pdf import render_pdf
    from app.schemas import Ingredient
    recipe = extract(HTML, URL)
    recipe.title = 'Kürbislasagne – einfach, lecker und vegetarisch'
    recipe.description = 'Ein leckeres Rezept mit Gemüse für die ganze Familie. ' * 3
    recipe.ingredients = [Ingredient(text=f'Zutat {i:02d}: 100 g frisches Gemüse', group=['Teig', 'Belag', 'Streusel'][(i-1)//8]) for i in range(1, 25)]
    image = Image.new('RGB', (800, 600), '#b96b42')
    buffer = BytesIO()
    image.save(buffer, format='PNG')
    image_data = 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()
    pdf = PdfReader(BytesIO(render_pdf(recipe, image_data)))
    first_page = pdf.pages[0].extract_text()
    assert 'Simmer / Rezept' not in first_page
    assert 'Quelle:' not in first_page
    assert 'Quelle:' in pdf.pages[-1].extract_text()
    assert recipe.title in ' '.join(first_page.split())
    for i in range(1, 25):
        assert f'Zutat {i:02d}:' in first_page
    for group in ['Teig', 'Belag', 'Streusel']:
        assert group in ''.join(first_page.split())
    text = '\n'.join(page.extract_text() for page in pdf.pages)
    for step in recipe.steps:
        assert step.text in text
