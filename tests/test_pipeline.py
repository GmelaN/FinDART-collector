from datetime import datetime, timezone
import unittest

from findart_collector.news_rss import NewsItem
from findart_collector.pipeline import daily_briefing_payload, ingest_daily_news


class FakeApi:
    def __init__(self):
        self.originals = []
        self.processed = []
        self.policy_briefing_days = []

    def ingest_original(self, payload):
        self.originals.append(payload)
        return f"original-{len(self.originals)}"

    def ingest_processed(self, path, payload):
        self.processed.append((path, payload))
        return {"data": {"status": "CREATED"}}

    def list_policy_briefings(self, day):
        self.policy_briefing_days.append(day)
        return [{"title": "AI 산업 육성 브리핑", "body": "지원 방안을 발표했습니다.", "publishedAt": f"{day}T00:00:00Z"}]


class FakeNim:
    def create_daily_briefing(self, articles, policy_briefings=None, market_indicators=None, rule_based_market=None):
        if not hasattr(self, "requests"):
            self.requests = []
        self.requests.append({"articles": articles, "policy_briefings": policy_briefings, "market_indicators": market_indicators, "rule_based_market": rule_based_market})
        return {
            "title": "오늘의 시장 브리핑",
            "summary": "주요 뉴스를 정리했습니다.",
            "market": [{"category": "GROWTH", "phase": "관망", "rationale": "기사 내용이 혼재합니다."}],
            "issueTitles": ["AI 산업"],
        }


class RealRateMarketData:
    """RSS 파이프라인에 전달할 ECOS 계산 완료 지표."""

    def collect(self, day):
        return {
            "asOf": day.isoformat(),
            "interestRate": {
                "rate": 2.75,
                "realRate": -0.04,
                "realRateChangeThreeMonthsPercentagePoints": 0.03,
                "realRatePressure": "유지",
            },
        }


class DailyNewsPipelineTests(unittest.TestCase):
    def test_groups_by_published_date_and_pushes_originals_first(self):
        items = [
            NewsItem("언론사", "https://feed.example", "a", "기사 A", "https://news.example/a", "요약 A", "Fri, 24 Jul 2026 11:00:00 +0900"),
            NewsItem("언론사", "https://feed.example", "b", "기사 B", "https://news.example/b", "요약 B", "Fri, 24 Jul 2026 12:00:00 +0900"),
            NewsItem("언론사", "https://feed.example", "c", "기사 C", "https://news.example/c", "요약 C", "Sat, 25 Jul 2026 12:00:00 +0900"),
        ]
        api = FakeApi()
        nim = FakeNim()
        results = ingest_daily_news(items, api, nim, collected_at=datetime(2026, 7, 26, tzinfo=timezone.utc))

        self.assertEqual([day.isoformat() for day, _ in results], ["2026-07-24", "2026-07-25"])
        self.assertEqual(len(api.originals), 3)
        self.assertEqual(len(api.processed), 2)
        first = api.processed[0][1]
        self.assertEqual(first["originalContentIds"], ["original-1", "original-2"])
        self.assertEqual(first["briefingDate"], "2026-07-24")
        self.assertEqual(first["headlines"][0]["id"], "original-1")
        self.assertEqual(len(api.processed), 2)
        self.assertEqual([day.isoformat() for day in api.policy_briefing_days], ["2026-07-24", "2026-07-25"])
        self.assertTrue(all(request["policy_briefings"] for request in nim.requests))
        self.assertEqual(nim.requests[0]["policy_briefings"][0]["title"], "AI 산업 육성 브리핑")
        self.assertEqual(nim.requests[0]["market_indicators"], {"asOf": "2026-07-24"})
        self.assertEqual(nim.requests[0]["rule_based_market"], [])

    def test_payload_has_required_daily_fields(self):
        article = NewsItem("언론사", "https://feed.example", "a", "기사", "https://news.example/a", "요약", None)
        payload = daily_briefing_payload(
            datetime(2026, 7, 24).date(),
            [article],
            ["original-1"],
            FakeNim().create_daily_briefing([]),
            datetime(2026, 7, 25, tzinfo=timezone.utc),
        )
        self.assertTrue({"source", "externalId", "originalContentIds", "market", "summary"}.issubset(payload))

    def test_uses_monetary_policy_analysis_for_interest_rate_by_default(self):
        item = NewsItem("언론사", "https://feed.example", "a", "기사", "https://news.example/a", "요약", "Fri, 24 Jul 2026 11:00:00 +0900")
        api = FakeApi()
        ingest_daily_news(
            [item],
            api,
            FakeNim(),
            collected_at=datetime(2026, 7, 25, tzinfo=timezone.utc),
            monetary_policy_analysis={"phase": "인하 기조", "summary": "물가와 성장 여건을 점검하며 완화를 이어갑니다."},
        )
        market = api.processed[0][1]["market"]
        self.assertEqual(market[0]["category"], "INTEREST_RATE")
        self.assertEqual(market[0]["phase"], "인하 기조")

    def test_rss_pipeline_sends_real_rate_text_to_nim_and_daily_payload(self):
        item = NewsItem("언론사", "https://feed.example", "a", "기사", "https://news.example/a", "요약", "Fri, 24 Jul 2026 11:00:00 +0900")
        api = FakeApi()
        nim = FakeNim()

        ingest_daily_news(
            [item],
            api,
            nim,
            collected_at=datetime(2026, 7, 25, tzinfo=timezone.utc),
            market_data=RealRateMarketData(),
            monetary_policy_analysis={"phase": "동결 기조", "summary": "기준금리를 유지합니다."},
        )

        expected = "실질금리(기준금리−소비자물가 상승률)는 -0.04%p이며 3개월 전 대비 +0.03%p로 유지입니다."
        nim_market = nim.requests[0]["rule_based_market"]
        self.assertIn(expected, nim_market[0]["rationale"])
        payload_market = api.processed[0][1]["market"]
        self.assertEqual(payload_market, nim_market)
