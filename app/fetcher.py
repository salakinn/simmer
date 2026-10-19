"""DNS-checked, IP-pinned HTTP fetcher. Every redirect is revalidated."""
import http.client
import ipaddress
import socket
import ssl
from urllib.parse import urljoin, urlsplit

from .config import settings


class FetchError(Exception):
    pass


class SafeHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, hostname, ip, port, timeout):
        super().__init__(hostname, port=port, timeout=timeout, context=ssl.create_default_context())
        self._ip = ip

    def connect(self):
        raw = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)


class SafeHTTPConnection(http.client.HTTPConnection):
    def __init__(self, hostname, ip, port, timeout):
        super().__init__(hostname, port=port, timeout=timeout)
        self._ip = ip

    def connect(self):
        self.sock = socket.create_connection((self._ip, self.port), self.timeout)


def validate_url(url: str) -> tuple[str, str, int]:
    try:
        parsed = urlsplit(url)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError()
        port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
        if port not in {80, 443}:
            raise ValueError()
        host = parsed.hostname.rstrip(".")
        if host.lower() in {"localhost", "localhost.localdomain"} or host.lower().endswith(".localhost"):
            raise ValueError()
        return parsed.scheme.lower(), host, port
    except ValueError as exc:
        raise FetchError("Nur öffentliche HTTP-/HTTPS-Adressen auf Standardports sind erlaubt.") from exc


def resolve_public_ip(host: str, port: int) -> str:
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise FetchError("Die Adresse konnte nicht aufgelöst werden.") from exc
    ips = {item[4][0] for item in addresses}
    if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
        raise FetchError("Lokale, private oder reservierte Netzwerkadressen sind nicht erlaubt.")
    return sorted(ips)[0]


def fetch(url: str, *, max_bytes: int | None = None, content_types: tuple[str, ...] = ("text/html",), redirects: int = 5, headers: dict[str, str] | None = None) -> tuple[bytes, str, str]:
    limit = max_bytes or settings.max_html_bytes
    current = url
    for _ in range(redirects + 1):
        scheme, host, port = validate_url(current)
        ip = resolve_public_ip(host, port)
        parsed = urlsplit(current)
        path = (parsed.path or "/") + ("?" + parsed.query if parsed.query else "")
        connection = (SafeHTTPSConnection if scheme == "https" else SafeHTTPConnection)(host, ip, port, settings.request_timeout)
        try:
            connection.request("GET", path, headers={**(headers or {}), "Host": parsed.netloc, "User-Agent": "Simmer/0.1 (+local recipe importer)", "Accept": ", ".join(content_types), "Accept-Encoding": "identity"})
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader("Location")
                if not location:
                    raise FetchError("Die Weiterleitung enthält keine Zieladresse.")
                current = urljoin(current, location)
                continue
            if response.status >= 400:
                raise FetchError(f"Die Webseite antwortete mit HTTP {response.status}.")
            if response.status != 200:
                raise FetchError("Die Webseite konnte nicht geladen werden.")
            media_type = response.getheader("Content-Type", "").split(";", 1)[0].lower().strip()
            if media_type not in content_types:
                raise FetchError("Die Antwort hat keinen unterstützten Inhaltstyp.")
            try:
                content_length = int(response.getheader("Content-Length", "0"))
            except ValueError:
                content_length = 0
            if content_length > limit:
                raise FetchError("Die Datei ist zu groß.")
            data = response.read(limit + 1)
            if len(data) > limit:
                raise FetchError("Die Datei ist zu groß.")
            return data, current, media_type
        except (socket.timeout, TimeoutError):
            raise FetchError("Die Webseite hat nicht rechtzeitig geantwortet.") from None
        except (OSError, http.client.HTTPException) as exc:
            raise FetchError("Die Webseite konnte nicht sicher geladen werden.") from exc
        finally:
            connection.close()
    raise FetchError("Die Webseite leitet zu oft weiter.")
