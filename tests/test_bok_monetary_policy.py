from datetime import datetime, timezone
import unittest

from findart_collector.bok_monetary_policy import BokMonetaryPolicyCollector, _monetary_policy_statement_urls, _statement_urls, parse_statement, today_briefing_with_interest_rate_regime


DETAIL_HTML = """
<h2>통화정책방향(2026.7.16)</h2>
<div class="dbdata"><p>□ 금융통화위원회는 한국은행 기준금리를 현재의 2.50% 수준에서 2.75%로 상향 조정하여 통화정책을 운용하기로 하였다.</p></div>
"""


class Response:
    def __init__(self, text): self.text = text
    def raise_for_status(self): pass


class Session:
    def __init__(self): self.list_params = None

    def get(self, url, **kwargs):
        if "listCont.do" in url:
            self.list_params = kwargs["params"]
            return Response("""
                <a href="/portal/bbs/P0000559/view.do?menuNo=200690&amp;nttId=10099998">금융통화위원회 의사록</a>
                <a href="/portal/bbs/P0000559/view.do?menuNo=200690&amp;nttId=10099999">통화정책방향(2026.7.16)</a>
            """)
        return Response(DETAIL_HTML)


class BokMonetaryPolicyTests(unittest.TestCase):
    def test_parses_and_builds_ingestion_payloads(self):
        statement = parse_statement(DETAIL_HTML, "https://www.bok.or.kr/portal/singl/newsData/view.do?menuNo=201263&nttId=10099999", collected_at=datetime(2026, 7, 17, tzinfo=timezone.utc))
        self.assertEqual(statement.external_id, "10099999")
        self.assertEqual(statement.published_at, datetime(2026, 7, 16, tzinfo=timezone.utc))
        self.assertIn("2.75%", statement.body)
        analysis = {"phase": "인상 기조", "decision": "HIKE", "currentRate": 2.75, "summary": "금리를 인상했습니다.", "evidence": []}
        self.assertEqual(statement.policy_payload("original-1", analysis)["originalContentIds"], ["original-1"])

    def test_collects_the_latest_verified_statement(self):
        session = Session()
        statement = BokMonetaryPolicyCollector(session=session).collect_latest()
        self.assertEqual(statement.external_id, "10099999")
        self.assertEqual(session.list_params["searchKwd"], "금융통화위원회")
        self.assertEqual(session.list_params["pageUnit"], "50")
        self.assertRegex(session.list_params["date"], r"^20\d{2}$")

    def test_discovers_javascript_style_list_entries(self):
        urls = _statement_urls("<a href=\"javascript:view({nttId: '11062942'})\">통화정책방향</a>")
        self.assertEqual(urls, ["https://www.bok.or.kr/portal/bbs/P0000559/view.do?menuNo=200690&nttId=11062942"])

    def test_discovers_newsdata_detail_links(self):
        urls = _statement_urls('<a href="/portal/singl/newsData/view.do?menuNo=201263&amp;nttId=11062942">통화정책방향</a>')
        self.assertEqual(urls, ["https://www.bok.or.kr/portal/singl/newsData/view.do?menuNo=201263&nttId=11062942"])

    def test_filters_search_results_to_monetary_policy_direction(self):
        urls = _monetary_policy_statement_urls("""
            <a href="/portal/bbs/P0000559/view.do?nttId=1">금융통화위원회 의사록</a>
            <a href="/portal/bbs/P0000559/view.do?nttId=2">통화정책방향(2026.7.16)</a>
        """)
        self.assertEqual(urls, ["https://www.bok.or.kr/portal/bbs/P0000559/view.do?nttId=2"])

    def test_keeps_other_today_market_entries_when_updating_interest_rate(self):
        today = {
            "id": "today-1",
            "title": "기존 브리핑",
            "summary": "기존 요약",
            "market": [
                {"category": "INTEREST_RATE", "phase": "동결", "rationale": "기존 금리 문구"},
                {"category": "INFLATION", "phase": "물가 안정", "rationale": "기존 물가 문구"},
            ],
        }
        payload = today_briefing_with_interest_rate_regime(
            today,
            {"category": "INTEREST_RATE", "phase": "인상 기조", "rationale": "금통위 인상 기조. 실질금리 압력은 유지입니다."},
        )
        self.assertNotIn("id", payload)
        self.assertEqual(payload["summary"], "기존 요약")
        self.assertEqual(payload["market"][0]["phase"], "인상 기조")
        self.assertIn("실질금리", payload["market"][0]["rationale"])
        self.assertEqual(payload["market"][1], today["market"][1])
