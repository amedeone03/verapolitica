"""Upgrade institutional portrait URLs so browsers on HTTPS can load them.

Camera and Senato still publish some ``http://`` image addresses. Those are
blocked as mixed content on the public site. Only known official hosts are
rewritten to HTTPS; other schemes are dropped.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

_OFFICIAL_IMAGE_SUFFIXES = (".camera.it", ".senato.it", ".governo.it")
_OFFICIAL_IMAGE_HOSTS = frozenset(
    {
        "camera.it",
        "senato.it",
        "governo.it",
        "www.governo.it",
        "documenti.camera.it",
        "www.camera.it",
        "dati.camera.it",
        "www.senato.it",
        "dati.senato.it",
    }
)


def official_https_image_url(value: object) -> str | None:
    """Return a same-image HTTPS URL, or None when the value is not loadable."""

    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate:
        return None
    parsed = urlsplit(candidate)
    host = (parsed.hostname or "").casefold()
    if parsed.scheme in {"http", "https"} and host:
        official = host in _OFFICIAL_IMAGE_HOSTS or host.endswith(
            _OFFICIAL_IMAGE_SUFFIXES
        )
        if parsed.scheme == "http" and not official:
            return None
        return urlunsplit(("https", parsed.netloc, parsed.path, parsed.query, parsed.fragment))
    return None
