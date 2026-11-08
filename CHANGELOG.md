# Änderungen

## v0.2.0 – 8. November 2026

- Eigene Rezepte direkt in der Weboberfläche erfassen, bearbeiten und als PDF herunterladen.
- Rezeptbilder per Drag-and-drop oder Dateiauswahl hinzufügen, mit Vorschau und Entfernen-Funktion. JPG, PNG und WebP werden lokal gespeichert und serverseitig geprüft.
- Pull-to-refresh auf Smartphones: am oberen Seitenrand herunterziehen und loslassen. Rezeptformulare sind vor versehentlichem Neuladen geschützt.
- Neues Simmer-Logo als Browser-Favicon und Touch-Icon.
- Python-Hintergrundprozess für Linux, macOS und Windows mit stündlicher Prüfung von GitHub. Updates werden separat zusammengeführt, mit ihren Abhängigkeiten installiert und getestet. Vor dem Neustart wird die SQLite-Datenbank gesichert; bei Startfehlern werden Code, Umgebung und Datenbank wiederhergestellt.
- Lokale Codeänderungen und Merge-Konflikte blockieren die automatische Installation, ohne die laufende Version zu ersetzen.
- Optionaler Telegram-Bot für Linkimport und PDF-Abruf, mit Nutzerfreigaben und Schutz vor doppelter Verarbeitung.
- Bessere Auflösung von Rezeptbildern aus JSON-LD und Erhalt von Zutatengruppen.

Der Hintergrundprozess wurde unter Linux einschließlich vollständigem Update und Neustart geprüft. macOS und Windows wurden nicht auf echten Systemen getestet. Docker-Container werden vom Auto-Updater nicht verwaltet.
