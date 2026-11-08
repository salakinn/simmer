# Simmer v0.2.0

Simmer importiert Online-Rezepte in ein lokales Archiv. Die gespeicherten, normalisierten Daten lassen sich bearbeiten und als druckfreundliches A4-PDF herunterladen.

Neu in v0.2.0: eigene Rezepte manuell erfassen, Bilder per Drag-and-drop hinzufügen,
mobile Aktualisierung durch Herunterziehen und ein plattformunabhängiger Hintergrundprozess
mit automatischen GitHub-Updates. Details stehen in [CHANGELOG.md](CHANGELOG.md).

## Start mit Docker Compose

Voraussetzung: Docker mit Compose-Plugin und Zugriff auf den Docker-Daemon.

```bash
cp .env.example .env
docker compose up --build -d
```

Danach `http://127.0.0.1:8001/` öffnen. Die SQLite-Datenbank liegt im persistenten Docker-Volume `simmer_data`. Stoppen mit `docker compose down`. `docker compose down -v` löscht auch das Datenbank-Volume. Der lokale Port kann mit `SIMMER_PORT` in `.env` geändert werden.

Die Veröffentlichung ist standardmäßig auf `127.0.0.1:8001` beschränkt. Da Simmer keine Anmeldung hat, Simmer nur lokal oder in einem vertrauenswürdigen Netzwerk betreiben.

## Telegram-Bot (optional)

Der Bot nimmt Rezeptlinks in privaten Chats entgegen und legt die Rezepte im selben lokalen Archiv ab. Simmer bleibt dabei auf `127.0.0.1:8001` beschränkt; der Bot ruft neue Nachrichten ausgehend bei Telegram ab. Für den Bot ist kein öffentlicher Webhook nötig.

1. Mit [@BotFather](https://t.me/BotFather) einen Bot erstellen und dessen Token als `TELEGRAM_BOT_TOKEN` in `.env` eintragen. Den Token geheim halten.
2. Den Bot starten: `docker compose --profile telegram up --build -d`.
3. Dem Bot im privaten Chat `/id` senden. Er antwortet mit deiner numerischen Telegram-Nutzer-ID.
4. Diese ID als `TELEGRAM_ALLOWED_USER_IDS=123456789` in `.env` eintragen. Mehrere IDs sind kommagetrennt möglich. Danach `docker compose --profile telegram up -d --force-recreate telegram` ausführen.
5. Dem Bot einen öffentlichen HTTP- oder HTTPS-Rezeptlink schicken. Er antwortet mit dem gespeicherten Rezeptnamen und der ID oder mit einem Importfehler. Das Rezept erscheint anschließend in der lokalen Weboberfläche.
6. Mit `/pdf <Rezept-ID>`, zum Beispiel `/pdf 12`, das gespeicherte Rezept als PDF im Telegram-Chat anfordern. Die Importbestätigung enthält den passenden Befehl. Der Bot erstellt das PDF aus dem aktuellen Datenbankeintrag, also auch mit späteren Änderungen aus der Weboberfläche.

Ohne Docker kann der Bot nach Einrichtung der Python-Umgebung mit `.venv/bin/python -m app.telegram_bot` als zweiter Prozess gestartet werden. Solange keine Nutzer-ID freigegeben ist, beantwortet er nur `/id`. Gruppen werden nicht verarbeitet. Bereits bearbeitete Telegram-Updates werden gespeichert, damit eine erneute Zustellung kein zweites Rezept erzeugt.

## Start ohne Docker

Python 3.12+ und die Systembibliotheken für WeasyPrint (Pango, HarfBuzz, Fontconfig sowie eine Schrift wie DejaVu) werden benötigt.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Für den lokalen Start in `.env` `DATABASE_URL=sqlite:///./data/simmer.db` setzen. Anschließend:

```bash
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8001
```

## Hintergrundbetrieb mit automatischen Updates

Der Python-Hintergrundprozess unterstützt Linux, macOS und Windows und braucht keinen
bestimmten Dienstmanager. Voraussetzung sind Git, Python 3.12+, eine eingerichtete
`.venv` und die Systembibliotheken für WeasyPrint. Die folgenden Befehle im Projektordner
mit dem Python-Befehl des Systems ausführen (`python`, unter Linux gegebenenfalls `python3`):

```bash
python -m scripts.run_service --detach
```

Simmer läuft dann auf `http://127.0.0.1:8001`. Der Hintergrundprozess prüft nach 30 Sekunden
und danach stündlich `origin/main` des bei der Einrichtung gespeicherten GitHub-Repositories.
Er lädt neue Änderungen herunter, führt sie mit lokalen Commits zusammen und installiert
die Python-Abhängigkeiten in einer separaten Umgebung. Erst nach erfolgreichem `pip check`
und der gesamten Testsuite sichert er die SQLite-Datenbank und startet Simmer mit der
neuen Version. Bei einem fehlgeschlagenen Neustart stellt er Code, Python-Umgebung und
Datenbank wieder her. Unterbrochene Installationen werden beim nächsten Start zurückgesetzt.

Lokale Codeänderungen müssen als Git-Commit gespeichert sein. Bei uncommitteten Änderungen,
Merge-Konflikten oder fehlgeschlagenen Prüfungen bleibt die bisherige Version in Betrieb.
Rezepte, hochgeladene Bilder und `.env` gehören nicht in den Git-Commit und bleiben lokal.
Es wird nichts zu GitHub hochgeladen. Docker-Container werden durch diesen Updater nicht verwaltet.

```bash
# Nur nach neuen Änderungen suchen
python -m scripts.auto_update --check

# Sofort prüfen und gegebenenfalls installieren
python -m scripts.auto_update

# Hintergrundprozess beenden
python -m scripts.run_service --stop

# Anderen Port bzw. anderes Prüfintervall wählen (beim Start)
python -m scripts.run_service --detach --port 8001 --interval 3600
```

Protokoll (`service.log` beim Start mit `--detach`), Update-Status (`status.json`),
Datenbanksicherungen (`backups/`) und Python-Umgebungen liegen unter Linux/macOS standardmäßig
in `~/.local/state/simmer-updater` (bzw. `$XDG_STATE_HOME/simmer-updater`) und unter Windows
in `%LOCALAPPDATA%\Simmer`. Ein eigenes Verzeichnis lässt sich bei jedem Befehl über
`--state-dir` angeben. Sicherungen und ältere Umgebungen bleiben für die Wiederherstellung erhalten.
Ein Netzwerkfehler beendet Simmer nicht; die nächste Prüfung folgt beim nächsten Intervall.

Für den Autostart nach einer Anmeldung kann derselbe Befehl ohne `--detach` in den
eigenen Dienstmanager eingebunden werden (systemd, launchd oder Windows-Aufgabenplanung).
`--detach` allein richtet keinen Autostart nach einem Neustart des Rechners ein.

## Nutzung

1. Auf der Startseite **Rezept hinzufügen** wählen. Linkimport und manuelle Erfassung verwenden dieselbe Oberfläche.
2. Optional einen öffentlichen HTTP-/HTTPS-Rezeptlink eingeben und **Daten übernehmen** wählen. Die Felder und das Bild werden vorgefüllt, ohne einen Datenbankeintrag anzulegen.
3. Name, Zutaten, Schritte und weitere Angaben prüfen oder manuell ausfüllen. Das Bild kann ersetzt oder entfernt werden.
4. Erst **Rezept speichern** legt das Rezept in der Sammlung ab. **Abbrechen** verwirft die Erfassung.
5. Gespeicherte Rezepte lassen sich auf der Detailseite bearbeiten und als PDF herunterladen.

Bei der manuellen Erfassung und Bearbeitung können JPG-, PNG- oder WebP-Bilder per Drag-and-drop oder Dateiauswahl hinzugefügt werden (standardmäßig bis 5 MB). Die Bilder werden lokal gespeichert und auch im PDF verwendet.

Auf Smartphones lässt sich die Start- oder Rezeptseite durch Herunterziehen am oberen Seitenrand und anschließendes Loslassen aktualisieren. Während der Rezepterfassung oder Bearbeitung ist die Geste deaktiviert, damit ungespeicherte Eingaben erhalten bleiben.

Die manuelle Bearbeitung verwendet eine Zutat beziehungsweise einen Zubereitungsschritt pro Zeile. Die strukturierte API speichert Zutaten zusätzlich mit optionaler Menge, Einheit und Bezeichnung. Beim Bearbeiten in der Weboberfläche bleibt der vollständige Zutatentext erhalten; erkennbare Mengen und Einheiten werden beim Speichern erneut aufgeteilt.

Zutatengruppen von Chefkoch (z. B. Teig, Belag und Streusel) und Jo Semola (z. B. Hauptteig und Sauerteig) bleiben in der Ansicht und im PDF erhalten. Beim Bearbeiten markieren `[Gruppenname]` eine neue Gruppe und `[]` Zutaten ohne Gruppe; in der API heißt das optionale Zutatenfeld `group`. Öffentliche Monsieur-Cuisine-Rezepte werden über die Rezept-API der Seite importiert, ohne JavaScript im Browser auszuführen.

## API

Die interaktive API-Dokumentation ist unter `/docs` verfügbar.

| Methode | Pfad | Zweck |
| --- | --- | --- |
| POST | `/api/recipes` | Rezept manuell erfassen, optional mit `image_upload` als Bild-Data-URL |
| POST | `/api/recipes/preview` | Rezeptlink auslesen und Formular-Daten einschließlich Bild liefern, ohne zu speichern |
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

`source_type` und `version` sind Teil des einheitlichen Datenmodells. Extraktion und PDF-Renderer teilen sich nur dieses Modell, keinen quellspezifischen Code. Die Rezeptversion ist ein Änderungszähler; frühere Fassungen werden noch nicht gespeichert.

- Viele Rezeptseiten liefern weder vollständige strukturierte Daten noch für `recipe-scrapers` erkennbare Angaben. Simmer meldet dann einen verständlichen Importfehler.
- JavaScript-gerenderte Seiten und Paywalls werden nicht unterstützt.
- Fehlende Angaben bleiben leer. Bildabruf ist optional; wenn er scheitert, bleibt das Rezept ohne lokal gespeichertes Bild. Bilder werden für das PDF ausschließlich aus den gespeicherten Bilddaten geladen. Externe Ressourcen sind beim PDF-Rendering gesperrt.
- Abrufe haben Zeit- und Größenlimits. Jeder Redirect und jedes DNS-Ergebnis wird geprüft; private, lokale, Link-local- und reservierte IPs sind gesperrt. HTTP/HTTPS auf Standardports ist erlaubt.
- Ohne Benutzerkonten ist jede Person mit Netzwerkzugriff auf die Anwendung auch zur Bearbeitung und Löschung berechtigt.
- Telegram-Linkimport ist optional. Sprachnachrichten, KI-Generierung, Einkaufslisten und Cloud-Synchronisierung sind nicht Bestandteil dieser Version.
