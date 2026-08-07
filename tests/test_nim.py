import unittest

from findart_collector.nim import NimClient


class NimClientTests(unittest.TestCase):
    def test_adds_nvidia_provider_prefix_for_short_model_name(self):
        client = NimClient("test-key", "nemotron-3-ultra-550b-a55b")
        self.assertEqual(client.model, "nvidia/nemotron-3-ultra-550b-a55b")

    def test_preserves_provider_qualified_model_name(self):
        client = NimClient("test-key", "meta/llama-3.3-70b-instruct")
        self.assertEqual(client.model, "meta/llama-3.3-70b-instruct")

    def test_uses_next_model_after_a_retryable_nim_failure(self):
        session = FallbackNimSession()
        client = NimClient("test-key", "primary", fallback_models=["fallback/model"], session=session)

        result = client.create_daily_briefing([])

        self.assertEqual(result["title"], "브리핑")
        self.assertEqual([request["json"]["model"] for request in session.requests], ["nvidia/primary", "fallback/model"])

    def test_uses_fallback_when_primary_omits_required_daily_market(self):
        session = InvalidDailyResultSession()
        client = NimClient("test-key", "primary", fallback_models=["fallback/model"], session=session)

        result = client.create_daily_briefing([])

        self.assertEqual(result["market"][0]["category"], "GROWTH")
        self.assertEqual([request["json"]["model"] for request in session.requests], ["nvidia/primary", "fallback/model"])

    def test_classifies_monetary_policy_with_structured_output(self):
        session = MonetaryPolicySession()
        client = NimClient("test-key", "model", session=session)

        result = client.classify_monetary_policy(title="통화정책방향(2026.7.16)", body="금융통화위원회는 한국은행 기준금리를 2.75%로 상향 조정했다.")

        self.assertEqual(result["phase"], "인상 기조")
        self.assertIn("판정 예시 5", session.request["json"]["messages"][0]["content"])

    def test_sends_market_indicators_as_explicit_daily_briefing_context(self):
        session = FakeNimSession()
        client = NimClient("test-key", "model", session=session)

        client.create_daily_briefing(
            [{"title": "기사", "summary": "요약", "sourceUrl": "https://news.example", "publisher": "언론사"}],
            market_indicators={"kospi": {"changePercent": -3.2}, "interestRate": {"rate": 2.5}},
            rule_based_market=[{"category": "INTEREST_RATE", "phase": "동결", "rationale": "기준금리 2.50%"}],
        )

        document = session.request["json"]["messages"][1]["content"]
        self.assertIn('"marketIndicators"', document)
        self.assertIn('"changePercent": -3.2', document)
        self.assertIn('"ruleBasedMarket"', document)
        self.assertIn("기준금리", session.request["json"]["messages"][0]["content"])
        self.assertIn("700~1,100자", session.request["json"]["messages"][0]["content"])
        self.assertEqual(session.request["json"]["reasoning_effort"], "none")

    def test_limits_daily_source_context_before_sending_it_to_nim(self):
        session = FakeNimSession()
        client = NimClient("test-key", "model", session=session)

        client.create_daily_briefing(
            [{"title": "기사" * 200, "summary": "요약" * 2_000, "sourceUrl": "https://news.example", "publisher": "언론사"}] * 30,
            [{"title": "정책" * 200, "body": "본문" * 2_000, "publishedAt": "2026-07-28"}] * 20,
        )

        document = session.request["json"]["messages"][1]["content"]
        self.assertLessEqual(len(document), 24_000)


class FakeNimResponse:
    status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return {
            "choices": [
                {"message": {"content": '{"title":"브리핑","summary":"요약","market":[{"category":"GROWTH","phase":"관망","rationale":"근거"}]}'}}
            ]
        }


class FakeNimSession:
    def post(self, *args, **kwargs):
        self.request = {"args": args, **kwargs}
        return FakeNimResponse()


class FallbackNimResponse(FakeNimResponse):
    status_code = 503
    text = "temporarily unavailable"


class FallbackNimSession:
    def __init__(self):
        self.requests = []

    def post(self, *args, **kwargs):
        self.requests.append({"args": args, **kwargs})
        return FallbackNimResponse() if len(self.requests) == 1 else FakeNimResponse()


class InvalidDailyResultResponse(FakeNimResponse):
    def json(self):
        return {"choices": [{"message": {"content": '{"title":"브리핑","summary":"요약"}'}}]}


class InvalidDailyResultSession:
    def __init__(self):
        self.requests = []

    def post(self, *args, **kwargs):
        self.requests.append({"args": args, **kwargs})
        return InvalidDailyResultResponse() if len(self.requests) == 1 else FakeNimResponse()


class MonetaryPolicyResponse(FakeNimResponse):
    def json(self):
        return {"choices": [{"message": {"content": '{"phase":"인상 기조","decision":"HIKE","currentRate":2.75,"summary":"기준금리를 올렸습니다.","evidence":[{"quote":"기준금리를 상향 조정","reason":"인상 결정"}]}'}}]}


class MonetaryPolicySession:
    def post(self, *args, **kwargs):
        self.request = {"args": args, **kwargs}
        return MonetaryPolicyResponse()
