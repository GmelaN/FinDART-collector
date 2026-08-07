from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone

from dotenv import load_dotenv

from .bok_monetary_policy import BokMonetaryPolicyCollector, today_briefing_with_interest_rate_regime
from .market_data import MarketDataCollector
from .market_regime import build_interest_rate_regime
from .nim import NimClient
from .policy_briefing import FinDartApiClient


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="한국은행 최신 통화정책방향 적재 PoC")
    parser.add_argument("--ingest", action="store_true", help="원문과 정책 문서를 FinDART에 적재")
    parser.add_argument("--findart-uri", default=os.getenv("FINDART_URI", "http://findart.com"))
    parser.add_argument("--pages", type=int, default=3, help="확인할 최신 게시판 페이지 수")
    parser.add_argument("--today-date", type=date.fromisoformat, help="갱신할 Today 브리핑 기준일 (기본: 오늘)")
    args = parser.parse_args()

    statement = BokMonetaryPolicyCollector().collect_latest(args.pages)
    nim = NimClient(
        os.getenv("NVIDIA_NIM_API_KEY", ""),
        os.getenv("NVIDIA_NIM_MODEL", ""),
        fallback_models=os.getenv("NVIDIA_NIM_FALLBACK_MODELS", "").split(","),
    )
    analysis = nim.classify_monetary_policy(title=statement.title, body=statement.body)
    if not args.ingest:
        print(json.dumps({"document": statement.original_payload(), "analysis": analysis}, ensure_ascii=False))
        return 0
    api = FinDartApiClient(args.findart_uri, os.getenv("FINDART_TOKEN", ""))
    original_id = api.ingest_original(statement.original_payload())
    result = api.ingest_processed("/api/v1/collector/processed-contents/policy-briefings", statement.policy_payload(original_id, analysis))
    today_date = args.today_date or datetime.now(timezone.utc).date()
    today = api.get_today_briefing(today_date)
    today_id = today["id"]
    if not isinstance(today_id, str):  # guarded by get_today_briefing; helps static callers.
        raise RuntimeError("FinDART Today 브리핑 응답에 id가 없습니다")
    interest_rate_regime = build_interest_rate_regime(
        MarketDataCollector(os.getenv("KOREA_BANK_ECOS_API_KEY")).collect(today_date),
        analysis,
    )
    if interest_rate_regime is None:
        raise RuntimeError("Today에 반영할 금리 시장 국면을 만들지 못했습니다")
    updated_today = api.ingest_processed(
        "/api/v1/collector/processed-contents/daily-briefings",
        today_briefing_with_interest_rate_regime(
            api.daily_briefing_ingestion_payload(today_id),
            interest_rate_regime,
        ),
    )
    print(
        f"{statement.external_id}: original={original_id}, "
        f"policy={result.get('data', {}).get('status', 'UNKNOWN')}, "
        f"today={updated_today.get('data', {}).get('status', 'UPDATED')}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
