from __future__ import annotations

import argparse
import json
import os
import sys

from dotenv import load_dotenv

from .news_rss import NewsRssCollector, interleave_feed_items, parse_feed_urls
from .nim import NimClient
from .market_data import MarketDataCollector
from .pipeline import ingest_daily_news
from .policy_briefing import FinDartApiClient


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="복수 뉴스 RSS 피드 수집기")
    parser.add_argument("--limit-per-source", type=int, default=10, help="피드별 최대 기사 수 (기본값: 10)")
    parser.add_argument("--ingest", action="store_true", help="원문과 NIM 일일 브리핑을 FinDART API에 적재")
    parser.add_argument("--findart-uri", default=os.getenv("FINDART_URI", "http://findart.com"))
    args = parser.parse_args()

    feed_urls = parse_feed_urls(os.getenv("NEWS_RSS_URIS"))
    if not feed_urls:
        parser.error("NEWS_RSS_URIS에 하나 이상의 RSS URL을 설정하세요")

    results, errors = NewsRssCollector(feed_urls).fetch_all(args.limit_per_source)
    items = interleave_feed_items(results)
    if args.ingest:
        client = FinDartApiClient(args.findart_uri, os.getenv("FINDART_TOKEN", ""))
        nim = NimClient(
            os.getenv("NVIDIA_NIM_API_KEY", ""),
            os.getenv("NVIDIA_NIM_MODEL", ""),
            fallback_models=os.getenv("NVIDIA_NIM_FALLBACK_MODELS", "").split(","),
        )
        market_data = MarketDataCollector(os.getenv("KOREA_BANK_ECOS_API_KEY"))
        for day, processed in ingest_daily_news(items, client, nim, market_data=market_data):
            status = processed.get("data", {}).get("status", "UNKNOWN")
            print(f"{day.isoformat()}: daily-briefing={status}")
    else:
        for item in items:
            print(json.dumps(item.__dict__, ensure_ascii=False))
    for error in errors:
        print(f"RSS fetch 실패: {error}", file=sys.stderr)
    return 1 if errors and not results else 0


if __name__ == "__main__":
    sys.exit(main())
