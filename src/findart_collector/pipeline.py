"""End-to-end ingestion pipelines for RSS news and policy briefings."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from hashlib import sha256
from typing import Any, Iterable

from .news_rss import NewsItem, briefing_date, isoformat
from .nim import NimClient
from .market_data import MarketDataCollector
from .market_regime import classify_market_regimes, update_interest_rate_regime
from .policy_briefing import FinDartApiClient, PolicyBriefing
from .progress import tqdm


NEWS_SOURCE = "NEWS_RSS_DAILY"


def ingest_policy_briefings(
    briefings: Iterable[PolicyBriefing], api: FinDartApiClient, nim: NimClient
) -> list[tuple[str, dict[str, object]]]:
    results = []
    briefing_list = list(briefings)
    for briefing in tqdm(briefing_list, desc="정책브리핑 적재", unit="문서"):
        # The original must be persisted before its NIM-derived processed content.
        original_id = api.ingest_original(briefing.original_payload())
        body = nim.rewrite_policy_briefing(title=briefing.title, body=briefing.body)
        processed = api.ingest_processed(
            "/api/v1/collector/processed-contents/policy-briefings",
            briefing.policy_payload(original_id, body=body),
        )
        results.append((original_id, processed))
    return results


def ingest_daily_news(
    items: Iterable[NewsItem], api: FinDartApiClient, nim: NimClient, *, collected_at: datetime | None = None,
    market_data: MarketDataCollector | None = None,
    monetary_policy_analysis: dict[str, object] | None = None,
) -> list[tuple[date, dict[str, object]]]:
    collected_at = collected_at or datetime.now(timezone.utc)
    groups: dict[date, list[NewsItem]] = defaultdict(list)
    for item in items:
        groups[briefing_date(item, collected_at)].append(item)

    results = []
    for day in tqdm(sorted(groups), desc="일일 브리핑 생성", unit="일자"):
        articles = groups[day]
        original_ids = [
            api.ingest_original(item.original_payload(collected_at))
            for item in tqdm(articles, desc=f"{day.isoformat()} RSS 원문 적재", unit="기사", leave=False)
        ]
        policy_briefings = api.list_policy_briefings(day)
        indicators = market_data.collect(day) if market_data else {"asOf": day.isoformat()}
        rule_based_market = update_interest_rate_regime(
            classify_market_regimes(indicators),
            indicators,
            monetary_policy_analysis,
        )
        generated = nim.create_daily_briefing(
            [
                {"title": item.title, "summary": item.summary, "sourceUrl": item.url, "publisher": item.source}
                for item in articles
            ],
            [
                {
                    "title": str(briefing.get("title", "")),
                    "body": str(briefing.get("body", "")),
                    "publishedAt": str(briefing.get("publishedAt", "")),
                }
                for briefing in policy_briefings
            ],
            indicators,
            rule_based_market,
        )
        payload = daily_briefing_payload(day, articles, original_ids, generated, collected_at, market=rule_based_market or None)
        results.append((day, api.ingest_processed("/api/v1/collector/processed-contents/daily-briefings", payload)))
    return results


def daily_briefing_payload(
    day: date,
    articles: list[NewsItem],
    original_ids: list[str],
    generated: dict[str, Any],
    collected_at: datetime,
    market: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    references = [{"id": original_id, "title": article.title, "sourceUrl": article.url} for article, original_id in zip(articles, original_ids)]
    issue_titles = generated.get("issueTitles", [])
    issues = [{"title": title} for title in issue_titles if isinstance(title, str) and title.strip()]
    fingerprint = "\n".join([day.isoformat(), *original_ids, generated["summary"]])
    return {
        "source": NEWS_SOURCE,
        "externalId": f"daily-news-{day.isoformat()}",
        "collectedAt": isoformat(collected_at),
        "checksum": sha256(fingerprint.encode("utf-8")).hexdigest(),
        "originalContentIds": original_ids,
        "briefingDate": day.isoformat(),
        "mode": "DAILY",
        "title": generated["title"].strip(),
        "summary": generated["summary"].strip(),
        "market": market or generated["market"],
        "headlines": references,
        "issues": issues,
        "issueTracking": [],
        "events": [],
        "publishedAt": isoformat(datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)),
    }
