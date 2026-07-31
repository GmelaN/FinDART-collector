from __future__ import annotations

from dotenv import load_dotenv
import argparse
import json
import os
import sys

from .policy_briefing import FinDartApiClient, KoreaPolicyBriefingCollector
from .nim import NimClient
from .pipeline import ingest_policy_briefings


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="대한민국 정책브리핑 부처 브리핑 수집기")
    parser.add_argument("--pages", type=int, default=1, help="조회할 목록 페이지 수 (기본값: 1)")
    parser.add_argument("--limit", type=int, help="수집할 문서 최대 수")
    parser.add_argument("--ingest", action="store_true", help="FinDART API에 적재")
    parser.add_argument("--findart-uri", default=os.getenv("FINDART_URI", "http://findart.com"))
    args = parser.parse_args()

    briefings = KoreaPolicyBriefingCollector().collect_pages(args.pages, args.limit)
    if not args.ingest:
        for briefing in briefings:
            print(json.dumps(briefing.original_payload(), ensure_ascii=False))
        return 0

    client = FinDartApiClient(args.findart_uri, os.getenv("FINDART_TOKEN", ""))
    nim = NimClient(
        os.getenv("NVIDIA_NIM_API_KEY", ""),
        os.getenv("NVIDIA_NIM_MODEL", ""),
        fallback_models=os.getenv("NVIDIA_NIM_FALLBACK_MODELS", "").split(","),
    )
    for briefing, (original_id, processed) in zip(briefings, ingest_policy_briefings(briefings, client, nim)):
        status = processed.get("data", {}).get("status", "UNKNOWN")
        print(f"{briefing.external_id}: original={original_id}, policy={status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
