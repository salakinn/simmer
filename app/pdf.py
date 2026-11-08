import base64
from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import CSS, HTML
from weasyprint.urls import URLFetcherResponse


env = Environment(loader=FileSystemLoader("app/templates"), autoescape=select_autoescape(["html"]))


def render_pdf(recipe, image_data: str | None = None) -> bytes:
    html = env.get_template("pdf.html").render(recipe=recipe, image_data=image_data)

    def local_images_only(url):
        for media_type in ("image/jpeg", "image/png", "image/webp"):
            prefix = f"data:{media_type};base64,"
            if url.startswith(prefix):
                return URLFetcherResponse(url, body=base64.b64decode(url[len(prefix):], validate=True), headers={"Content-Type": media_type})
        raise ValueError("Externe Ressourcen sind beim PDF-Rendering gesperrt")

    page = HTML(string=html, base_url=None, url_fetcher=local_images_only)
    for columns, scale in ((1, 1), (2, 1), (2, .9), (2, .8), (2, .7), (2, .6), (2, .5), (2, .4), (2, .3), (2, .2), (2, .1)):
        compact = CSS(string=f"""
            .overview {{ font-size: {10 * scale}pt !important; line-height: 1.35 !important; }}
            .overview h1 {{ font-size: {28 * scale}pt !important; margin-bottom: {5 * scale}mm !important; }}
            .overview .description {{ font-size: {11 * scale}pt !important; margin-bottom: {8 * scale}mm !important; }}
            .overview .meta {{ font-size: {9 * scale}pt !important; margin-bottom: {9 * scale}mm !important; }}
            .overview .hero {{ max-height: {55 * scale}mm !important; margin-bottom: {8 * scale}mm !important; }}
            .overview h2 {{ font-size: {16 * scale}pt !important; margin: {10 * scale}mm 0 {5 * scale}mm !important; }}
            .overview ul {{ columns: {columns} !important; column-gap: 8mm !important; }}
            .overview li {{ padding-bottom: {2.5 * scale}mm !important; }}
        """)
        document = page.render(stylesheets=[compact])
        if (len(document.pages) > 1
                and "last-ingredient" in document.pages[0].anchors
                and "overview-end" in document.pages[0].anchors
                and "preparation" in document.pages[1].anchors):
            return document.write_pdf()
    raise ValueError("Beschreibung und Zutaten passen nicht auf eine PDF-Seite")
