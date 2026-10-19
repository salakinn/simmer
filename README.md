# Simmer v0.1

Simmer importiert Online-Rezepte in ein lokales Archiv. Die gespeicherten, normalisierten Daten lassen sich bearbeiten und als druckfreundliches A4-PDF herunterladen.

## Start mit Docker Compose

Voraussetzung: Docker mit Compose-Plugin und Zugriff auf den Docker-Daemon.

```bash
cp .env.example .env
docker compose up --build -d
```

Danach `http://127.0.0.1:8000` öffnen. Die SQLite-Datenbank liegt im persistenten Docker-Volume `simmer_data`. Stoppen mit `docker compose down`. `docker compose down -v` löscht auch das Datenbank-Volume.

Die Veröffentlichung ist standardmäßig auf `127.0.0.1:8000` beschränkt. Da v0.1 keine Anmeldung hat, Simmer nur lokal oder in einem vertrauenswürdigen Netzwerk betreiben.

## Start ohne Docker

Python 3.12+ und die Systembibliotheken für WeasyPrint (Pango, HarfBuzz, Fontconfig sowie eine Schrift wie DejaVu) werden benötigt.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Für den lokalen Start in `.env` `DATABASE_URL=sqlite:///./data/simmer.db` setzen. Anschließend:

```bash
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## Nutzung

1. Auf der Startseite eine öffentliche HTTP- oder HTTPS-Rezeptadresse einfügen.
2. Simmer liest bevorzugt Schema.org/JSON-LD und ergänzt fehlende Angaben nach Möglichkeit mit `recipe-scrapers`.
3. Das Rezept auf der Detailseite prüfen. Über **Rezept bearbeiten** alle Textfelder, Zeiten, Zutaten und Schritte korrigieren und speichern.
4. **PDF herunterladen** erzeugt die Ausgabe aus dem Datenbankeintrag. Die Quellseite wird dafür nicht erneut geladen.

Die manuelle Bearbeitung verwendet eine Zutat beziehungsweise einen Zubereitungsschritt pro Zeile. Die strukturierte API speichert Zutaten zusätzlich mit optionaler Menge, Einheit und Bezeichnung. Beim Bearbeiten in der Weboberfläche bleibt der vollständige Zutatentext erhalten; erkennbare Mengen und Einheiten werden beim Speichern erneut aufgeteilt.

Chefkoch-Zutatengruppen (z. B. Teig, Belag und Streusel) bleiben in der Ansicht und im PDF erhalten. Beim Bearbeiten markieren `[Gruppenname]` eine neue Gruppe und `[]` Zutaten ohne Gruppe; in der API heißt das optionale Zutatenfeld `group`. Öffentliche Monsieur-Cuisine-Rezepte werden über die Rezept-API der Seite importiert, ohne JavaScript im Browser auszuführen.

## API

Die interaktive API-Dokumentation ist unter `/docs` verfügbar.

| Methode | Pfad | Zweck |
| --- | --- | --- |
| POST | `/api/recipes/import` | Import mit `{"url":"https://..."}` |
| GET | `/api/recipes` | Alle Rezepte |
| GET | `/api/recipes/{id}` | Ein Rezept |
| PUT | `/api/recipes/{id}` | Rezeptdaten ersetzen |
| DELETE | `/api/recipes/{id}` | Rezept löschen |
| GET | `/api/recipes/{id}/pdf` | PDF herunterladen |

Antworten auf Validierungs- und Importfehler enthalten `error` und `detail`; bei ungültigen Eingabefeldern zusätzlich `fields`.

## Tests

```bash
.venv/bin/pytest -q
```

Alle Tests verwenden lokale HTML-Fixtures oder Mocks und benötigen keine externe Rezeptseite. Sie prüfen JSON-LD, Normalisierung, unvollständige Rezepte, URL- und DNS-Sperren, Redirect-Prüfung, CRUD und PDF-Inhalt.

## Architektur und Grenzen

`URL → sicherer Fetcher → JSON-LD/recipe-scrapers → Normalizer → RecipeRecord → SQLite → PDF-Renderer`

`source_type` und `version` sind Teil des einheitlichen Datenmodells. Extraktion und PDF-Renderer teilen sich nur dieses Modell, keinen quellspezifischen Code. Versionierung bedeutet in v0.1 einen Änderungszähler; frühere Fassungen werden noch nicht gespeichert.

- Viele Rezeptseiten liefern weder vollständige strukturierte Daten noch für `recipe-scrapers` erkennbare Angaben. Simmer meldet dann einen verständlichen Importfehler.
- JavaScript-gerenderte Seiten und Paywalls werden nicht unterstützt.
- Fehlende Angaben bleiben leer. Bildabruf ist optional; wenn er scheitert, bleibt das Rezept ohne lokal gespeichertes Bild. Bilder werden für das PDF ausschließlich aus den gespeicherten Bilddaten geladen. Externe Ressourcen sind beim PDF-Rendering gesperrt.
- Abrufe haben Zeit- und Größenlimits. Jeder Redirect und jedes DNS-Ergebnis wird geprüft; private, lokale, Link-local- und reservierte IPs sind gesperrt. HTTP/HTTPS auf Standardports ist erlaubt.
- Ohne Benutzerkonten ist jede Person mit Netzwerkzugriff auf die Anwendung auch zur Bearbeitung und Löschung berechtigt.
- Telegram, Sprachnachrichten, KI-Generierung, Einkaufslisten und Cloud-Synchronisierung sind nicht Bestandteil von v0.1.
