import json
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx

from backend.app.pipeline.collectors.base import CollectedDocument, CollectorError


class _ProfileLinkParser(HTMLParser):
    def __init__(self, index_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.index_url = index_url
        self.links: set[str] = set()

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.casefold() != "a":
            return
        href = dict(attrs).get("href")
        if not isinstance(href, str):
            return
        absolute = urljoin(self.index_url, href.strip())
        path = urlparse(absolute).path.rstrip("/")
        if path.startswith("/it/governo/") and any(
            marker in path
            for marker in (
                "/presidente-del-consiglio/",
                "/vice-presidente/",
                "/ministro/",
                "/sottosegretario/",
                "/sottosegretari-pcm/",
            )
        ):
            self.links.add(absolute.rstrip("/"))


class GovernoCollector:
    """Collect the official current-government index and linked HTML profiles."""

    version = "governo_collector_v1"
    response_media_type = "application/vnd.verapolitica.governo-bundle+json"

    def __init__(
        self,
        index_url: str,
        *,
        timeout_seconds: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.index_url = index_url
        self.timeout_seconds = timeout_seconds
        self.client = client

    def collect(self) -> CollectedDocument:
        headers = {
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": "VeraPolitica/0.1 (+official-data-ingestion)",
        }
        try:
            if self.client is not None:
                content = self._collect_with_client(self.client, headers)
            else:
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    content = self._collect_with_client(client, headers)
        except (httpx.HTTPError, UnicodeDecodeError, ValueError) as exc:
            raise CollectorError(f"Governo collection failed: {exc}") from exc

        return CollectedDocument(
            content=content,
            source_url=self.index_url,
            content_type=self.response_media_type,
            retrieved_at=datetime.now(timezone.utc),
            collector_version=self.version,
        )

    def _collect_with_client(
        self, client: httpx.Client, headers: dict[str, str]
    ) -> bytes:
        index_response = client.get(self.index_url, headers=headers)
        index_response.raise_for_status()
        index_html = index_response.content.decode(
            index_response.encoding or "utf-8", errors="strict"
        )
        link_parser = _ProfileLinkParser(self.index_url)
        link_parser.feed(index_html)
        profile_urls = sorted(link_parser.links)
        if not profile_urls:
            raise ValueError("official index contains no current-holder profile links")

        profiles = []
        for url in profile_urls:
            response = client.get(url, headers=headers)
            response.raise_for_status()
            profiles.append(
                {
                    "url": url,
                    "html": response.content.decode(
                        response.encoding or "utf-8", errors="strict"
                    ),
                }
            )
        bundle = {
            "bundle_version": 1,
            "index_url": self.index_url,
            "index_html": index_html,
            "profiles": profiles,
        }
        return json.dumps(
            bundle,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
