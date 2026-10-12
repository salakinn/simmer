import ipaddress
from pathlib import Path
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base, get_db
from app.extraction import ExtractionError, duration, extract, jsonld_recipe, normalize
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
    with patch('app.main.fetch', return_value=(HTML.encode(), URL, 'text/html')):
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
    text = ''.join(page.extract_text() for page in PdfReader(BytesIO(pdf.content)).pages)
    assert 'Mein Ofengemüse' in text
    assert 'Ofen stark vorheizen' in text
    assert client.delete(f'/api/recipes/{rid}').status_code == 204
    assert client.get(f'/api/recipes/{rid}').status_code == 404


def test_bad_import_and_validation(client):
    with patch('app.main.fetch', return_value=(b'<html></html>', URL, 'text/html')):
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
    text = '\n'.join(page.extract_text() for page in pages)
    assert 'Schritt 1:' in text
    assert 'Schritt 30:' in text


def test_pdf_with_stored_image():
    import base64
    from io import BytesIO
    from PIL import Image
    from app.pdf import render_pdf
    picture = Image.new('RGB', (32, 20), '#b96b42')
    buffer = BytesIO()
    picture.save(buffer, format='PNG')
    image_data = 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()
    pdf = render_pdf(extract(HTML, URL), image_data)
    assert pdf.startswith(b'%PDF-')
    assert len(pdf) > 10000


def test_scraper_fallback_normalizes_missing_jsonld():
    fallback = {'title':'Nudelsalat','ingredients':['200 g Nudeln'],'steps':['Nudeln kochen.'],'servings':'2'}
    with patch('app.extraction.scraper_data', return_value=fallback):
        recipe = extract('<html><body>Rezept ohne JSON-LD</body></html>', URL)
    assert recipe.title == 'Nudelsalat'
    assert recipe.ingredients[0].unit == 'g'
    assert recipe.steps[0].text == 'Nudeln kochen.'
