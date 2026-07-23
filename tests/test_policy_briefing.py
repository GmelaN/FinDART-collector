from datetime import datetime, timezone
import unittest

from findart_collector.policy_briefing import (
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
