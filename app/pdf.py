import base64
from io import BytesIO
from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML
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
    return HTML(string=html, base_url=None, url_fetcher=local_images_only).write_pdf()
