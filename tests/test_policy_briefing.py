from datetime import date, datetime, timezone
import unittest

from findart_collector.policy_briefing import (
    FinDartApiClient,
    KoreaPolicyBriefingCollector,
    PolicyBriefingParseError,
    parse_policy_briefing,
)


DETAIL_HTML = """
<div class="view_title"><h1>AI 산업 육성 브리핑</h1><div class="variety"><div class="info">
  <span>2026.07.22</span><span>홍길동 대변인</span>
</div></div></div>
<div class="article_body"><div class="view_cont">
  <div class="movie"><video>제외할 영상 텍스트</video></div>
  안녕하십니까? <br /><br /> AI 산업 육성 방안을 발표합니다.
  <script>제외할 스크립트</script>
</div></div>
"""


class FakeResponse:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self):
        pass


class FakeSession:
    def get(self, url, **kwargs):
        return FakeResponse(
            '<a href="/briefing/policyBriefingView.do?newsId=156771779">첫 글</a>'
            '<a href="/briefing/policyBriefingView.do?newsId=156771779">중복</a>'
            '<a href="/briefing/policyBriefingView.do?newsId=156771707">둘째 글</a>'
        )


class ApiResponse:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class PolicyBriefingApiSession:
    def __init__(self):
        self.requests = []

    def get(self, url, **kwargs):
        self.requests.append((url, kwargs))
        page = kwargs["params"]["page"]
        pages = [
            {
                "content": [{"id": "policy-1", "title": "AI 산업 육성", "body": "지원 방안", "publishedAt": "2026-07-24T09:00:00Z"}],
                "page": 0,
                "size": 100,
                "totalElements": 2,
                "totalPages": 2,
            },
            {
                "content": [{"id": "policy-2", "title": "수출 지원", "body": "금융 지원", "publishedAt": "2026-07-24T10:00:00Z"}],
                "page": 1,
                "size": 100,
                "totalElements": 2,
                "totalPages": 2,
            },
        ]
        return ApiResponse({"success": True, "data": pages[page]})


class PolicyBriefingParserTests(unittest.TestCase):
    def test_parses_detail_page_and_builds_api_payloads(self):
        collected_at = datetime(2026, 7, 23, 12, tzinfo=timezone.utc)
        briefing = parse_policy_briefing(
            DETAIL_HTML,
            "https://www.korea.kr/briefing/policyBriefingView.do?newsId=156771779",
            collected_at=collected_at,
        )

        self.assertEqual(briefing.external_id, "156771779")
        self.assertEqual(briefing.title, "AI 산업 육성 브리핑")
        self.assertEqual(briefing.speaker, "홍길동 대변인")
        self.assertEqual(briefing.published_at, datetime(2026, 7, 22, tzinfo=timezone.utc))
        self.assertNotIn("제외할", briefing.body)
        self.assertEqual(briefing.original_payload()["language"], "ko")
        policy = briefing.policy_payload("original-1")
        self.assertEqual(policy["originalContentIds"], ["original-1"])
        self.assertEqual(policy["evidence"][0]["documentType"], "POLICY_BRIEFING")
        self.assertEqual(len(policy["checksum"]), 64)

    def test_rejects_missing_news_id(self):
        with self.assertRaises(PolicyBriefingParseError):
            parse_policy_briefing(DETAIL_HTML, "https://www.korea.kr/briefing/policyBriefingView.do")

    def test_list_urls_is_deduplicated(self):
        urls = KoreaPolicyBriefingCollector(session=FakeSession()).list_urls()
        self.assertEqual(
            urls,
            [
                "https://www.korea.kr/briefing/policyBriefingView.do?newsId=156771779",
                "https://www.korea.kr/briefing/policyBriefingView.do?newsId=156771707",
            ],
        )


class FinDartApiClientTests(unittest.TestCase):
    def test_lists_all_policy_briefings_for_the_requested_day(self):
        session = PolicyBriefingApiSession()
        client = FinDartApiClient("https://findart.example/", "token", session=session)

        briefings = client.list_policy_briefings(date(2026, 7, 24))

        self.assertEqual([briefing["id"] for briefing in briefings], ["policy-1", "policy-2"])
        self.assertEqual(
            [request[1]["params"] for request in session.requests],
            [
                {"from": "2026-07-24", "to": "2026-07-24", "page": 0, "size": 100},
                {"from": "2026-07-24", "to": "2026-07-24", "page": 1, "size": 100},
            ],
        )
        self.assertEqual(session.requests[0][1]["headers"], {"Authorization": "Bearer token"})
