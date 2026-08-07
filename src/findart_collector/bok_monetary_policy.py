"""Collector for Bank of Korea Monetary Policy Board policy statements."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from html import unescape
from html.parser import HTMLParser
import re
from urllib.parse import parse_qs, urljoin, urlparse

import requests

from .news_rss import isoformat
from .market_regime import upsert_market_regime


BOK_BASE_URL = "https://www.bok.or.kr"
# ``list.do`` renders only the search shell.  The actual result rows are loaded
# asynchronously from ``listCont.do``.
BOK_MONETARY_POLICY_LIST_URL = f"{BOK_BASE_URL}/portal/singl/newsData/listCont.do"
BOK_MONETARY_POLICY_DETAIL_URL = f"{BOK_BASE_URL}/portal/bbs/P0000559/view.do"
BOK_MONETARY_POLICY_LIST_PARAMS = {
    "targetDepth": "3",
    "menuNo": "201263",
    "syncMenuChekKey": "2",
    "searchCnd": "1",
    "searchKwd": "금융통화위원회",
    "depth2": "200038",
    "depth3": "201263",
    "sort": "1",
    "pageUnit": "50",
}
SOURCE_NAME = "BOK_MONETARY_POLICY"
PUBLISHER = "한국은행"
TITLE_PATTERN = re.compile(r"^통화정책방향\s*\(\d{4}\.\d{1,2}\.\d{1,2}\)$")


class MonetaryPolicyNotFoundError(RuntimeError):
    pass


def today_briefing_with_interest_rate_regime(
    briefing: dict[str, object], interest_rate_regime: dict[str, str],
) -> dict[str, object]:
    """Apply the shared interest update while retaining every Today field."""
    market = briefing.get("market")
    if not isinstance(market, list):
        raise RuntimeError("FinDART Today 브리핑 응답에 market이 없습니다")
    typed_market = [item for item in market if isinstance(item, dict)]
    if len(typed_market) != len(market):
        raise RuntimeError("FinDART Today 브리핑의 market 형식이 올바르지 않습니다")
    # id is a path parameter; all other response fields are retained verbatim.
    return {key: value for key, value in briefing.items() if key != "id"} | {
        "market": upsert_market_regime(typed_market, interest_rate_regime),
    }


@dataclass(frozen=True)
class BokMonetaryPolicy:
    external_id: str
    source_url: str
    title: str
    body: str
    published_at: datetime
    collected_at: datetime

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
            "attributes": {"documentType": "MONETARY_POLICY_DIRECTION"},
            "publishedAt": isoformat(self.published_at),
            "collectedAt": isoformat(self.collected_at),
        }

    def policy_payload(self, original_content_id: str, analysis: dict[str, object]) -> dict[str, object]:
        evidence = analysis.get("evidence", [])
        analysis_body = "\n".join(
            [
                f"금리 정책 기조: {analysis['phase']}",
                f"이번 결정: {analysis['decision']} (기준금리 {analysis['currentRate']}%)",
                str(analysis["summary"]),
                *[f"- {item['quote']} ({item['reason']})" for item in evidence if isinstance(item, dict)],
            ]
        )
        return {
            "source": SOURCE_NAME,
            "externalId": self.external_id,
            "collectedAt": isoformat(self.collected_at),
            "checksum": sha256(analysis_body.encode("utf-8")).hexdigest(),
            "originalContentIds": [original_content_id],
            "title": self.title,
            "body": analysis_body,
            "publishedAt": isoformat(self.published_at),
            "evidence": [{
                "documentType": "POLICY_BRIEFING",
                "title": self.title,
                "publisher": PUBLISHER,
                "publishedAt": isoformat(self.published_at),
                "sourceUrl": self.source_url,
            }],
        }


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href") or ""
        if ("singl/newsData/view.do" in href or "P0000559/view.do" in href) and "nttId=" in href:
            self.urls.append(urljoin(BOK_BASE_URL, href))


def _statement_urls(html: str) -> list[str]:
    parser = _LinkParser()
    parser.feed(html)
    # The BOK list has used both ordinary links and JavaScript detail handlers.
    # nttId is stable in either representation.
    linked_ids = {
        parse_qs(urlparse(url).query).get("nttId", [""])[0]
        for url in parser.urls
    }
    for ntt_id in re.findall(r"nttId\s*(?:=|:|%3D)\s*['\"]?(\d+)", html, flags=re.IGNORECASE):
        if ntt_id not in linked_ids:
            parser.urls.append(f"{BOK_MONETARY_POLICY_DETAIL_URL}?menuNo=200690&nttId={ntt_id}")
    return list(dict.fromkeys(parser.urls))


class _MonetaryPolicyLinkParser(HTMLParser):
    """Extract only '통화정책방향' rows from the searched BOK result list."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.urls: list[str] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a" or self._href is not None:
            return
        href = dict(attrs).get("href") or ""
        if "P0000559/view.do" in href and "nttId=" in href:
            self._href = urljoin(BOK_BASE_URL, href)
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._href is None:
            return
        if TITLE_PATTERN.fullmatch(_clean(self._text)):
            self.urls.append(self._href)
        self._href = None
        self._text = []


def _monetary_policy_statement_urls(html: str) -> list[str]:
    parser = _MonetaryPolicyLinkParser()
    parser.feed(html)
    return list(dict.fromkeys(parser.urls))


class _BodyParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.body_parts: list[str] = []
        self.capture_title = False
        self.capture_body = False
        self.depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = set((dict(attrs).get("class") or "").split())
        if tag in {"h2", "h3"}:
            self.capture_title = True
        if tag == "div" and {"view_cont", "view-content", "bbs-view", "dbdata"} & classes:
            self.capture_body, self.depth = True, 1
            return
        if self.capture_body:
            self.depth += 1
            if tag in {"p", "div", "li", "br"}:
                self.body_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"h2", "h3"}:
            self.capture_title = False
        if self.capture_body:
            self.depth -= 1
            if self.depth == 0:
                self.capture_body = False

    def handle_data(self, data: str) -> None:
        if self.capture_title:
            self.title_parts.append(data)
        if self.capture_body:
            self.body_parts.append(data)


def _clean(parts: list[str]) -> str:
    return re.sub(r"\n{3,}", "\n\n", re.sub(r" *\n *", "\n", re.sub(r"[ \t]+", " ", "".join(parts)))).strip()


def parse_statement(html: str, source_url: str, *, collected_at: datetime | None = None) -> BokMonetaryPolicy:
    parser = _BodyParser()
    parser.feed(html)
    title = next(
        (
            _clean([unescape(re.sub(r"<[^>]+>", "", value))])
            for value in re.findall(r"<h[23][^>]*>(.*?)</h[23]>", html, flags=re.IGNORECASE | re.DOTALL)
            if TITLE_PATTERN.fullmatch(_clean([unescape(re.sub(r"<[^>]+>", "", value))]))
        ),
        "",
    )
    body = _clean(parser.body_parts)
    if not body:
        visible_text = _clean([unescape(re.sub(r"<[^>]+>", " ", html))])
        start = visible_text.find("□ 금융통화위원회")
        end = visible_text.find("목록", start)
        body = visible_text[start:end if end > start else None].strip() if start >= 0 else ""
    if not TITLE_PATTERN.fullmatch(title) or not body:
        raise MonetaryPolicyNotFoundError("통화정책방향 제목 또는 본문을 찾지 못했습니다")
    if not all(term in body for term in ("금융통화위원회", "한국은행 기준금리")):
        raise MonetaryPolicyNotFoundError("기준금리 결정문이 아닌 게시물입니다")
    ntt_id = parse_qs(urlparse(source_url).query).get("nttId", [""])[0]
    if not ntt_id:
        raise MonetaryPolicyNotFoundError("nttId가 없는 한국은행 게시물입니다")
    year, month, day = map(int, re.search(r"\((\d{4})\.(\d{1,2})\.(\d{1,2})\)", title).groups())  # type: ignore[union-attr]
    return BokMonetaryPolicy(ntt_id, source_url, title, body, datetime(year, month, day, tzinfo=timezone.utc), collected_at or datetime.now(timezone.utc))


class BokMonetaryPolicyCollector:
    def __init__(self, session: requests.Session | None = None, timeout: float = 20.0) -> None:
        self.session = session or requests.Session()
        self.timeout = timeout

    def collect_latest(self, pages: int = 3) -> BokMonetaryPolicy:
        current_year = datetime.now(timezone.utc).year
        for page in range(1, pages + 1):
            params = {
                **BOK_MONETARY_POLICY_LIST_PARAMS,
                "pageIndex": page,
                # The board's date selector uses a four-digit year string.
                "date": str(current_year),
            }
            response = self.session.get(BOK_MONETARY_POLICY_LIST_URL, params=params, timeout=self.timeout)
            response.raise_for_status()
            statement = self._first_verified(_monetary_policy_statement_urls(response.text))
            if statement:
                return statement
        raise MonetaryPolicyNotFoundError("최신 통화정책방향 결정문을 찾지 못했습니다")

    def _first_verified(self, urls: list[str]) -> BokMonetaryPolicy | None:
        for url in urls:
            detail = self.session.get(url, timeout=self.timeout)
            detail.raise_for_status()
            try:
                return parse_statement(detail.text, url)
            except MonetaryPolicyNotFoundError:
                continue
        return None
