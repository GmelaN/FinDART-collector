"""대한민국 정책브리핑 부처 브리핑 수집기."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
import re
from typing import Iterable
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

import requests


KOREA_BASE_URL = "https://www.korea.kr"
POLICY_BRIEFING_LIST_URL = f"{KOREA_BASE_URL}/news/policyBriefingList.do"
SOURCE_NAME = "KOREA_POLICY_BRIEFING"
PUBLISHER = "대한민국 정책브리핑"


class PolicyBriefingParseError(ValueError):
    """Raised when a page is not a valid policy-briefing detail page."""


@dataclass(frozen=True)
class PolicyBriefing:
    external_id: str
    source_url: str
    title: str
    body: str
    published_at: datetime
    speaker: str | None
    collected_at: datetime

    @property
    def checksum(self) -> str:
        return sha256(self.body.encode("utf-8")).hexdigest()

    def original_payload(self) -> dict[str, object]:
        return {
            "contentType": "ARTICLE",
            "source": SOURCE_NAME,
            "externalId": self.external_id,
            "sourceUrl": self.source_url,
            "title": self.title,
            "rawBody": self.body,
            "publisher": PUBLISHER,
            "language": "ko",
            "attributes": {"speaker": self.speaker} if self.speaker else {},
            "publishedAt": isoformat(self.published_at),
            "collectedAt": isoformat(self.collected_at),
        }

    def policy_payload(self, original_content_id: str, *, body: str | None = None) -> dict[str, object]:
        processed_body = body or self.body
        return {
            "source": SOURCE_NAME,
            "externalId": self.external_id,
            "collectedAt": isoformat(self.collected_at),
            "checksum": sha256(processed_body.encode("utf-8")).hexdigest(),
            "originalContentIds": [original_content_id],
            "title": self.title,
            "body": processed_body,
            "publishedAt": isoformat(self.published_at),
            "evidence": [
                {
                    "documentType": "POLICY_BRIEFING",
                    "title": self.title,
                    "publisher": PUBLISHER,
                    "publishedAt": isoformat(self.published_at),
                    "sourceUrl": self.source_url,
                }
            ],
        }


def isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class _ListParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if href and "policyBriefingView.do" in href and "newsId=" in href:
            self.urls.append(urljoin(KOREA_BASE_URL, href))


class _DetailParser(HTMLParser):
    """Small, dependency-free parser for Korea.kr's stable article markup."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._capture: str | None = None
        self._depth = 0
        self._ignore_depth = 0
        self._seen_view_title = False
        self.title_parts: list[str] = []
        self.info_parts: list[str] = []
        self.body_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = set((dict(attrs).get("class") or "").split())
        if tag == "div" and "view_title" in classes:
            self._seen_view_title = True

        if self._capture is None:
            if tag == "h1" and self._seen_view_title and not self.title_parts:
                self._capture = "title"
                self._depth = 1
            elif tag == "div" and "info" in classes and not self.info_parts:
                self._capture = "info"
                self._depth = 1
            elif tag == "div" and "view_cont" in classes:
                self._capture = "body"
                self._depth = 1
            return

        self._depth += 1
        if self._capture == "body":
            if tag == "br":
                self.body_parts.append("\n")
            if tag in {"p", "div", "li", "h1", "h2", "h3"}:
                self.body_parts.append("\n")
            if tag in {"script", "style", "noscript", "video", "audio"}:
                self._ignore_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self._capture is None:
            return
        if self._capture == "body" and tag in {"script", "style", "noscript", "video", "audio"} and self._ignore_depth:
            self._ignore_depth -= 1
        self._depth -= 1
        if self._depth == 0:
            self._capture = None

    def handle_data(self, data: str) -> None:
        if self._capture == "title":
            self.title_parts.append(data)
        elif self._capture == "info":
            self.info_parts.append(data)
        elif self._capture == "body" and not self._ignore_depth:
            self.body_parts.append(data)


def clean_text(parts: Iterable[str]) -> str:
    text = "".join(parts).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def external_id_from_url(url: str) -> str:
    news_ids = parse_qs(urlparse(url).query).get("newsId")
    if not news_ids or not news_ids[0].isdigit():
        raise PolicyBriefingParseError(f"newsId가 없는 정책브리핑 URL입니다: {url}")
    return news_ids[0]


def parse_policy_briefing(html: str, source_url: str, *, collected_at: datetime | None = None) -> PolicyBriefing:
    parser = _DetailParser()
    parser.feed(html)
    title, body, info = clean_text(parser.title_parts), clean_text(parser.body_parts), clean_text(parser.info_parts)
    # 발표자 텍스트가 바로 뒤따르는 경우가 있어, 숫자와 한글 사이의
    # word-boundary에 의존하지 않는다.
    date_match = re.search(r"(\d{4})\.(\d{2})\.(\d{2})", info)
    if not title or not body or not date_match:
        raise PolicyBriefingParseError("제목, 본문 또는 발행일을 찾지 못했습니다")
    published_at = datetime(*map(int, date_match.groups()), tzinfo=timezone.utc)
    speaker = info[date_match.end() :].strip() or None
    return PolicyBriefing(
        external_id=external_id_from_url(source_url),
        source_url=source_url,
        title=title,
        body=body,
        published_at=published_at,
        speaker=speaker,
        collected_at=collected_at or datetime.now(timezone.utc),
    )


class KoreaPolicyBriefingCollector:
    def __init__(self, session: requests.Session | None = None, timeout: float = 20.0) -> None:
        self.session = session or requests.Session()
        self.timeout = timeout

    def list_urls(self, page: int = 1) -> list[str]:
        if page < 1:
            raise ValueError("page는 1 이상이어야 합니다")
        response = self.session.get(POLICY_BRIEFING_LIST_URL, params={"pageIndex": page}, timeout=self.timeout)
        response.raise_for_status()
        parser = _ListParser()
        parser.feed(response.text)
        return list(dict.fromkeys(parser.urls))

    def collect(self, source_url: str) -> PolicyBriefing:
        response = self.session.get(source_url, timeout=self.timeout)
        response.raise_for_status()
        return parse_policy_briefing(response.text, source_url)

    def collect_pages(self, pages: int = 1, limit: int | None = None) -> list[PolicyBriefing]:
        if pages < 1:
            raise ValueError("pages는 1 이상이어야 합니다")
        urls = [url for page in range(1, pages + 1) for url in self.list_urls(page)]
        unique_urls = list(dict.fromkeys(urls))
        if limit is not None:
            unique_urls = unique_urls[:limit]
        return [self.collect(url) for url in unique_urls]


class FinDartApiClient:
    def __init__(self, base_url: str, token: str, session: requests.Session | None = None, timeout: float = 20.0) -> None:
        # if not token:
        #     raise ValueError("FinDART API 토큰이 필요합니다")
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.timeout = timeout
        self.headers = {"Authorization": f"Bearer {token}"}

    def ingest_original(self, payload: dict[str, object]) -> str:
        return self._ingestion_id(self._post("/api/v1/collector/original-contents", payload))

    def ingest_processed(self, path: str, payload: dict[str, object]) -> dict[str, object]:
        return self._post(path, payload)

    def list_policy_briefings(self, day: date) -> list[dict[str, object]]:
        """Return every policy briefing published on the given calendar day."""
        page = 0
        briefings: list[dict[str, object]] = []
        while True:
            result = self._get(
                "/api/v1/policy-briefings",
                params={"from": day.isoformat(), "to": day.isoformat(), "page": page, "size": 100},
            )
            data = result.get("data")
            if not isinstance(data, dict):
                raise RuntimeError("FinDART 정책브리핑 조회 응답에 data가 없습니다")
            content = data.get("content")
            if not isinstance(content, list):
                raise RuntimeError("FinDART 정책브리핑 조회 응답에 content가 없습니다")
            briefings.extend(item for item in content if isinstance(item, dict))
            total_pages = data.get("totalPages")
            if not isinstance(total_pages, int) or page >= total_pages - 1:
                return briefings
            page += 1

    def ingest(self, briefing: PolicyBriefing, *, processed_body: str | None = None) -> tuple[str, dict[str, object]]:
        original_id = self.ingest_original(briefing.original_payload())
        processed = self.ingest_processed(
            "/api/v1/collector/processed-contents/policy-briefings",
            briefing.policy_payload(original_id, body=processed_body),
        )
        return original_id, processed

    def _post(self, path: str, payload: dict[str, object]) -> dict[str, object]:
        response = self.session.post(f"{self.base_url}{path}", json=payload, headers=self.headers, timeout=self.timeout)
        response.raise_for_status()

        if not response.status_code in {200, 201}:
            raise RuntimeError(f"FinDART 적재 실패: {response.text}")

        result = response.json()
        return result

    def _get(self, path: str, *, params: dict[str, object]) -> dict[str, object]:
        response = self.session.get(f"{self.base_url}{path}", params=params, headers=self.headers, timeout=self.timeout)
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise RuntimeError("FinDART 조회 응답이 JSON 객체가 아닙니다")
        return result

    @staticmethod
    def _ingestion_id(result: dict[str, object]) -> str:
        data = result.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("id"), str):
            raise RuntimeError("FinDART 원문 적재 응답에 ID가 없습니다")
        return data["id"]
