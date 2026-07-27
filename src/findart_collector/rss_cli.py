from __future__ import annotations

import argparse
import json
import os
import sys

from dotenv import load_dotenv

from .news_rss import NewsRssCollector, parse_feed_urls


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="복수 뉴스 RSS 피드 수집기")
    parser.add_argument("--limit-per-source", type=int, default=10, help="피드별 최대 기사 수 (기본값: 10)")
    args = parser.parse_args()

    feed_urls = parse_feed_urls(os.getenv("NEWS_RSS_URIS"))
    if not feed_urls:
        parser.error("NEWS_RSS_URIS에 하나 이상의 RSS URL을 설정하세요")

    results, errors = NewsRssCollector(feed_urls).fetch_all(args.limit_per_source)
    for result in results:
        for item in result.items:
            print(json.dumps(item.__dict__, ensure_ascii=False))
    for error in errors:
        print(f"RSS fetch 실패: {error}", file=sys.stderr)
    return 1 if errors and not results else 0


if __name__ == "__main__":
    sys.exit(main())
