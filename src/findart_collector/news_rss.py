from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
from itertools import zip_longest
from typing import Iterable
from xml.etree import ElementTree

import requests
from .progress import tqdm


def parse_feed_urls(value: str | None) -> list[str]:
    """Return distinct, non-empty feed URLs from a comma-separated setting."""
    if not value:
        return []
    return list(dict.fromkeys(url.strip() for url in value.split(",") if url.strip()))


@dataclass(frozen=True)
class NewsItem:
    source: str
    source_url: str
    external_id: str
    title: str
    url: str
    summary: str
    published_at: str | None

    def published_datetime(self, fallback: datetime) -> datetime:
        if not self.published_at:
            return fallback
        try:
            value = parsedate_to_datetime(self.published_at)
        except (TypeError, ValueError, IndexError):
            try:
                value = datetime.fromisoformat(self.published_at.replace("Z", "+00:00"))
            except ValueError:
                return fallback
        return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value).astimezone(timezone.utc)

    def original_payload(self, collected_at: datetime) -> dict[str, object]:
        published_at = self.published_datetime(collected_at)
        source = f"NEWS_RSS:{sha256(self.source_url.encode('utf-8')).hexdigest()[:12]}"
        return {
            "contentType": "ARTICLE",
            "source": source,
            "externalId": self.external_id,
            "sourceUrl": self.url,
            "title": self.title,
            "rawBody": self.summary or self.title,
            "publisher": self.source,
            "language": "ko",
            "attributes": {"feedUrl": self.source_url},
            "publishedAt": isoformat(published_at),
            "collectedAt": isoformat(collected_at),
        }


@dataclass(frozen=True)
class FeedResult:
    source: str
    source_url: str
    items: list[NewsItem]


def isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def briefing_date(item: NewsItem, fallback: datetime) -> date:
    """Group articles by their source publication date (in the source timezone)."""
    if item.published_at:
        try:
            parsed = parsedate_to_datetime(item.published_at)
            return (parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed).date()
        except (TypeError, ValueError, IndexError):
            try:
                return datetime.fromisoformat(item.published_at.replace("Z", "+00:00")).date()
            except ValueError:
                pass
    return fallback.date()


def _text(element: ElementTree.Element | None) -> str:
    return "" if element is None or element.text is None else element.text.strip()


def _child(element: ElementTree.Element, name: str) -> ElementTree.Element | None:
    return next((child for child in element if child.tag.rsplit("}", 1)[-1] == name), None)


def _children(element: ElementTree.Element, name: str) -> list[ElementTree.Element]:
    return [child for child in element if child.tag.rsplit("}", 1)[-1] == name]


def parse_rss(xml: str | bytes, source_url: str, limit: int | None = None) -> FeedResult:
    root = ElementTree.fromstring(xml)
    channel = _child(root, "channel")
    if channel is not None:
        source = _text(_child(channel, "title")) or source_url
        entries = _children(channel, "item")
    elif root.tag.rsplit("}", 1)[-1] == "feed":  # Atom
        source = _text(_child(root, "title")) or source_url
        entries = _children(root, "entry")
    else:
        raise ValueError("RSS 또는 Atom 피드가 아닙니다")

    items: list[NewsItem] = []
    for entry in entries[:limit]:
        link_element = _child(entry, "link")
        url = (link_element.get("href", "") if link_element is not None else "") or _text(link_element)
        external_id = _text(_child(entry, "guid")) or _text(_child(entry, "id")) or url
        title = _text(_child(entry, "title"))
        if not external_id or not title or not url:
            continue
        summary = _text(_child(entry, "description")) or _text(_child(entry, "summary")) or _text(_child(entry, "content"))
        published_at = (
            _text(_child(entry, "pubDate"))
            or _text(_child(entry, "date"))
            or _text(_child(entry, "published"))
            or _text(_child(entry, "updated"))
            or None
        )
        items.append(NewsItem(source, source_url, external_id, title, url, summary, published_at))
    return FeedResult(source, source_url, items)


def interleave_feed_items(results: Iterable[FeedResult]) -> list[NewsItem]:
    """Merge feeds fairly so an early, busy feed cannot dominate LLM context."""
    iterators = [iter(result.items) for result in results]
    items: list[NewsItem] = []
    seen: set[str] = set()
    for batch in zip_longest(*iterators):
        for item in batch:
            if item is None:
                continue
            key = item.url or f"{item.source_url}:{item.external_id}"
            if key in seen:
                continue
            seen.add(key)
            items.append(item)
    return items


class NewsRssCollector:
    def __init__(self, feed_urls: list[str], session: requests.Session | None = None, timeout: float = 20.0) -> None:
        self.feed_urls = feed_urls
        self.session = session or requests.Session()
        if session is None:
            self.session.headers.setdefault(
                "User-Agent",
                "FinDART-collector/0.1 (+https://github.com/jshyeon/FinDART-collector)",
            )
            self.session.headers.setdefault("Accept", "application/rss+xml, application/xml, text/xml, */*")
        self.timeout = timeout

    def fetch_all(self, limit_per_source: int | None = None) -> tuple[list[FeedResult], list[str]]:
        results: list[FeedResult] = []
        errors: list[str] = []
        for feed_url in tqdm(self.feed_urls, desc="RSS 피드 조회", unit="피드"):
            try:
                response = self.session.get(feed_url, timeout=self.timeout)
                response.raise_for_status()
                # Feed HTTP headers frequently omit or misstate the charset.
                # ElementTree can honor the XML declaration when given bytes.
                results.append(parse_rss(response.content, feed_url, limit_per_source))
            except (requests.RequestException, ElementTree.ParseError, ValueError) as error:
                errors.append(f"{feed_url}: {error}")
        return results, errors
