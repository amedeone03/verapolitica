"""robots.txt and sitemap.xml for the public app."""

from datetime import date
from typing import Annotated
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.deps import get_api_settings, get_db_session
from backend.app.core.config import Settings
from backend.app.models import Legislature, Politician, PoliticianVersion


router = APIRouter(include_in_schema=False)

SECTION_VIEWS = ("", "?view=politics", "?view=history", "?view=politicians", "?view=proposals",
                 "?view=referendums", "?view=voting-guide", "?view=glossary", "?view=methodology",
                 "?view=regions")


def _origin(request: Request, settings: Settings) -> str:
    configured = settings.public_base_url.strip().rstrip("/")
    return configured or str(request.base_url).rstrip("/")


@router.get("/robots.txt", response_class=PlainTextResponse)
def robots(request: Request, settings: Annotated[Settings, Depends(get_api_settings)]) -> str:
    origin = _origin(request, settings)
    return (
        "User-agent: *\n"
        "Allow: /app/\n"
        "Disallow: /admin/\n"
        "Disallow: /demo/\n"
        "Disallow: /docs\n"
        f"Sitemap: {origin}/sitemap.xml\n"
    )


@router.get("/sitemap.xml")
def sitemap(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_api_settings)],
) -> Response:
    origin = _origin(request, settings)
    urls: list[tuple[str, date | None]] = [(f"{origin}/app/{view}", None) for view in SECTION_VIEWS]
    published = session.execute(
        select(Politician.id, PoliticianVersion.published_at)
        .join(PoliticianVersion, PoliticianVersion.id == Politician.current_version_id)
        .where(PoliticianVersion.published_at.is_not(None))
        .order_by(Politician.id)
    )
    urls += [(f"{origin}/app/?politician={pid}", stamp.date()) for pid, stamp in published]
    urls += [(f"{origin}/app/?legislature={number}", None) for (number,) in session.execute(select(Legislature.number).order_by(Legislature.number))]
    body = "".join(
        f"<url><loc>{escape(loc)}</loc>{f'<lastmod>{when.isoformat()}</lastmod>' if when else ''}</url>"
        for loc, when in urls
    )
    xml = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>'
    return Response(content=xml, media_type="application/xml")
