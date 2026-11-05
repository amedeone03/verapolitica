"""Approved logos (parties), coats of arms (regions, provinces) and politician photos.

Keys: the party id, the region id, the province abbreviation, the politician
id, all as strings.
Only rows approved by a second redazione member exist, so every lookup here is
already public.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import EditorialSymbol

# Licences a logo may carry to be published. Anything else stays out.
LICENSES = {
    "pubblico-dominio": "Pubblico dominio",
    "cc0": "CC0",
    "cc-by": "CC BY",
    "cc-by-sa": "CC BY-SA",
    "autorizzato": "Uso autorizzato dal titolare",
    "istituzionale": "Stemma istituzionale (fonte ufficiale)",
}


def licenses_for(kind: str) -> dict[str, str]:
    """A politician's photo cannot claim the institutional coat-of-arms licence."""

    if kind == "politician":
        return {key: label for key, label in LICENSES.items() if key != "istituzionale"}
    return LICENSES


def media_url(image_id: int) -> str:
    return f"/media/{image_id}"


def logo_urls(session: Session, kind: str) -> dict[str, str]:
    rows = session.execute(select(EditorialSymbol.key, EditorialSymbol.image_id).where(EditorialSymbol.kind == kind))
    return {key: media_url(image_id) for key, image_id in rows}


def symbol_rows(session: Session, kind: str) -> dict[str, EditorialSymbol]:
    return {row.key: row for row in session.scalars(select(EditorialSymbol).where(EditorialSymbol.kind == kind))}


def symbol_dict(row: EditorialSymbol | None) -> dict | None:
    if row is None:
        return None
    return {
        "url": media_url(row.image_id),
        "credit": row.credit,
        "license": LICENSES.get(row.license, row.license),
        "source_url": row.source_url,
        "approved_by": row.approved_by,
    }
