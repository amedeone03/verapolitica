from __future__ import annotations

import re
from urllib.parse import urlsplit

SENATO_LOD_HOST = "dati.senato.it"
_SPARQL_HOSTS = frozenset({SENATO_LOD_HOST, "dati.camera.it"})
_RESOURCE_PATH = re.compile(r"^/(ddl|senatore)/(\d+)(?:\.html)?/?$", re.IGNORECASE)


def is_sparql_endpoint(url: str) -> bool:
    parsed = urlsplit(url.strip())
    host = (parsed.hostname or "").casefold()
    path = parsed.path.rstrip("/") or "/"
    return host in _SPARQL_HOSTS and path.casefold() == "/sparql"


def senato_lodview_url(value: str) -> str | None:
    """Return a LodView HTML URL for numeric Senato DDL or senator identifiers."""

    parsed = urlsplit(value.strip())
    host = (parsed.hostname or "").casefold()
    if host != SENATO_LOD_HOST:
        return None
    match = _RESOURCE_PATH.fullmatch(parsed.path)
    if match is None:
        return None
    kind, identifier = match.group(1).lower(), match.group(2)
    return f"https://{SENATO_LOD_HOST}/{kind}/{identifier}.html"


def citizen_source_url(url: str, *resource_hints: str | None) -> str:
    """Resolve a citizen-facing official page without mutating stored provenance.

    SPARQL endpoints stay as-is unless a numeric Senato DDL or senator identifier
    is already present in the stored URL or related source data.
    """

    candidate = url.strip()
    resolved = senato_lodview_url(candidate)
    if resolved is not None:
        return resolved
    if is_sparql_endpoint(candidate):
        for hint in resource_hints:
            if not hint:
                continue
            resolved = senato_lodview_url(hint)
            if resolved is not None:
                return resolved
    return candidate


def citizen_source_label(name: str) -> str:
    if name.casefold().startswith("senato della repubblica"):
        return "Senato della Repubblica"
    return name
