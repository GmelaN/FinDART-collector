from datetime import date
import os
import unittest

from dotenv import load_dotenv

from findart_collector.market_data import MarketDataCollector
from findart_collector.market_regime import build_interest_rate_regime


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class FakeEcosSession:
    def get(self, url, **kwargs):
        if "/722Y001/" in url:
            rows = [{"TIME": "20260710", "DATA_VALUE": "2.5", "UNIT_NAME": "연%"}]
        elif "/731Y001/" in url:
            rows = [{"TIME": "20260714", "DATA_VALUE": "1504.9", "UNIT_NAME": "원"}]
        elif "/901Y009/" in url:
            rows = [{"TIME": "202606", "DATA_VALUE": "119.99", "UNIT_NAME": "2020=100"}]
        elif "/200Y108/" in url:
            rows = [
                {"TIME": "2025Q2", "DATA_VALUE": "578719.2", "UNIT_NAME": "십억원"},
                {"TIME": "2025Q3", "DATA_VALUE": "586599.9", "UNIT_NAME": "십억원"},
                {"TIME": "2025Q4", "DATA_VALUE": "585964", "UNIT_NAME": "십억원"},
                {"TIME": "2026Q1", "DATA_VALUE": "596692.8", "UNIT_NAME": "십억원"},
                {"TIME": "2026Q2", "DATA_VALUE": "600405.7", "UNIT_NAME": "십억원"},
            ]
        else:
            rows = []
        return FakeResponse({"StatisticSearch": {"row": rows}})


class MarketDataCollectorTests(unittest.TestCase):
    def test_adds_ecos_indicators_with_periods_and_units(self):
        data = MarketDataCollector("ecos-key", session=FakeEcosSession()).collect(date(2026, 7, 24))

        self.assertEqual(data["asOf"], "2026-07-24")
        self.assertEqual(data["interestRate"]["rate"], 2.5)
        self.assertEqual(data["exchangeRate"]["unit"], "원")
        self.assertEqual(data["inflation"]["period"], "202606")
        self.assertEqual(data["growth"]["quarterOnQuarterPercent"], 0.62)
        self.assertEqual(data["growth"]["yearOnYearPercent"], 3.75)

    def test_adds_real_rate_and_three_month_pressure(self):
        indicators = {
            "interestRate": {
                "recentMonthlyRates": [
                    {"period": "202601", "rate": 3.0},
                    {"period": "202602", "rate": 3.0},
                    {"period": "202603", "rate": 3.0},
                    {"period": "202604", "rate": 3.5},
                ],
            },
            "inflation": {
                "recentYearOnYearPercent": [
                    {"period": "202601", "yearOnYearPercent": 2.0},
                    {"period": "202602", "yearOnYearPercent": 2.0},
                    {"period": "202603", "yearOnYearPercent": 2.0},
                    {"period": "202604", "yearOnYearPercent": 2.0},
                ],
            },
        }

        MarketDataCollector._attach_real_interest_rate(indicators)

        rate = indicators["interestRate"]
        self.assertEqual(rate["realRate"], 1.5)
        self.assertEqual(rate["realRateChangeThreeMonthsPercentagePoints"], 0.5)
        self.assertEqual(rate["realRatePressure"], "약한 상승 압력")

    def test_requests_enough_cpi_history_for_a_three_month_real_rate_comparison(self):
        class RecordingSession(FakeEcosSession):
            def __init__(self): self.urls = []

            def get(self, url, **kwargs):
                self.urls.append(url)
                return super().get(url, **kwargs)

        session = RecordingSession()
        MarketDataCollector("ecos-key", session=session).collect(date(2026, 7, 24))

        cpi_url = next(url for url in session.urls if "/901Y009/" in url)
        self.assertIn("/202501/", cpi_url)

    def test_renders_real_rate_pressure_from_live_ecos_response(self):
        load_dotenv()
        ecos_api_key = os.getenv("KOREA_BANK_ECOS_API_KEY")
        if not ecos_api_key:
            self.skipTest("KOREA_BANK_ECOS_API_KEY가 없어 실제 ECOS 통합 테스트를 건너뜁니다")

        data = MarketDataCollector(ecos_api_key).collect(date.today())
        interest = data.get("interestRate")
        inflation = data.get("inflation")
        self.assertIsInstance(interest, dict, "ECOS 기준금리 응답을 수집하지 못했습니다")
        self.assertIsInstance(inflation, dict, "ECOS CPI 응답을 수집하지 못했습니다")
        self.assertIn("realRate", interest)
        self.assertIn("realRateChangeThreeMonthsPercentagePoints", interest)
        self.assertIn("realRatePressure", interest)

        rates_by_period = {item["period"]: item["rate"] for item in interest["recentMonthlyRates"]}
        real_rates = [
            (item["period"], round(rates_by_period[item["period"]] - item["yearOnYearPercent"], 2))
            for item in inflation["recentYearOnYearPercent"]
            if item["period"] in rates_by_period
        ]
        self.assertGreaterEqual(len(real_rates), 4)
        expected_real_rate = real_rates[-1][1]
        expected_change = round(real_rates[-1][1] - real_rates[-4][1], 2)
        expected_pressure = MarketDataCollector._real_rate_pressure(expected_change)

        regime = build_interest_rate_regime(
            data,
            {"phase": "인상 기조", "summary": "금리 인상 기조를 유지합니다."},
        )

        self.assertEqual(interest["realRate"], expected_real_rate)
        self.assertEqual(interest["realRateChangeThreeMonthsPercentagePoints"], expected_change)
        self.assertEqual(interest["realRatePressure"], expected_pressure)
        self.assertIsNotNone(regime)
        self.assertIn(
            f"실질금리(기준금리−소비자물가 상승률)는 {expected_real_rate:.2f}%p이며 "
            f"3개월 전 대비 {expected_change:+.2f}%p로 {expected_pressure}입니다.",
            regime["rationale"],
        )
