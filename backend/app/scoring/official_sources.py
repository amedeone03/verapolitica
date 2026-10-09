"""Authoritative-source allowlist for pledge evidence V1.

Precision over coverage: a document is usable as fulfilment evidence only when
its HTTPS hostname is on the official public-administration list. News, blogs,
social media and campaign sites are rejected even if they quote an official act.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit


OFFICIAL_HOSTS: frozenset[str] = frozenset(
    {
        "governo.it",
        "www.governo.it",
        "gazzettaufficiale.it",
        "www.gazzettaufficiale.it",
        "normattiva.it",
        "www.normattiva.it",
        "senato.it",
        "www.senato.it",
        "dati.senato.it",
        "camera.it",
        "www.camera.it",
        "dati.camera.it",
        "interno.gov.it",
        "www.interno.gov.it",
        "dait.interno.gov.it",
        "giustizia.it",
        "www.giustizia.it",
        "mef.gov.it",
        "www.mef.gov.it",
        "esteri.it",
        "www.esteri.it",
        "difesa.it",
        "www.difesa.it",
        "salute.gov.it",
        "www.salute.gov.it",
        "lavoro.gov.it",
        "www.lavoro.gov.it",
        "istruzione.it",
        "www.istruzione.it",
        "mit.gov.it",
        "www.mit.gov.it",
        "masaf.gov.it",
        "www.masaf.gov.it",
        "mase.gov.it",
        "www.mase.gov.it",
        "cultura.gov.it",
        "www.cultura.gov.it",
        "funzionepubblica.gov.it",
        "www.funzionepubblica.gov.it",
        "pariopportunita.gov.it",
        "www.pariopportunita.gov.it",
        "quirinale.it",
        "www.quirinale.it",
        "cortecostituzionale.it",
        "www.cortecostituzionale.it",
        "istat.it",
        "www.istat.it",
    }
)

OFFICIAL_SUFFIXES: tuple[str, ...] = (
    ".governo.it",
    ".giustizia.it",
    ".mef.gov.it",
    ".interno.gov.it",
    ".senato.it",
    ".camera.it",
)

BLOCKED_HOSTS: frozenset[str] = frozenset(
    {
        "ansa.it",
        "www.ansa.it",
        "corriere.it",
        "www.corriere.it",
        "repubblica.it",
        "www.repubblica.it",
        "lastampa.it",
        "www.lastampa.it",
        "ilsole24ore.com",
        "www.ilsole24ore.com",
        "ilfattoquotidiano.it",
        "www.ilfattoquotidiano.it",
        "ilgiornale.it",
        "www.ilgiornale.it",
        "huffingtonpost.it",
        "www.huffingtonpost.it",
        "twitter.com",
        "x.com",
        "www.x.com",
        "facebook.com",
        "www.facebook.com",
        "instagram.com",
        "www.instagram.com",
        "youtube.com",
        "www.youtube.com",
        "tiktok.com",
        "www.tiktok.com",
    }
)


@dataclass(frozen=True, slots=True)
class SourceDecision:
    official: bool
    reason: str
    hostname: str


def hostname_of(url: str) -> str:
    return (urlsplit(url).hostname or "").casefold()


def is_blocked_host(host: str) -> bool:
    return host in BLOCKED_HOSTS or any(
        host.endswith(suffix)
        for suffix in (
            ".ansa.it",
            ".corriere.it",
            ".repubblica.it",
            ".lastampa.it",
        )
    )


def is_official_host(host: str) -> bool:
    if not host or is_blocked_host(host):
        return False
    if host in OFFICIAL_HOSTS:
        return True
    return any(host.endswith(suffix) for suffix in OFFICIAL_SUFFIXES)


def classify_source_url(url: str) -> SourceDecision:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").casefold()
    if parsed.scheme != "https":
        return SourceDecision(False, "source_not_https", host)
    if is_blocked_host(host):
        return SourceDecision(False, "blocked_non_official_host", host)
    if is_official_host(host):
        return SourceDecision(True, "official_host", host)
    return SourceDecision(False, "unofficial_host", host)


def is_official_source_url(url: str) -> bool:
    return classify_source_url(url).official
