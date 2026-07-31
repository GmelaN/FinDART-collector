from datetime import date
import unittest

from findart_collector.market_data import MarketDataCollector


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
