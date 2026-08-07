import unittest

from findart_collector.market_regime import build_interest_rate_regime, classify_market_regimes, update_interest_rate_regime


class MarketRegimeTests(unittest.TestCase):
    def test_classifies_all_macro_categories_from_derived_values(self):
        regimes = classify_market_regimes(
            {
                "interestRate": {"rate": 2.5, "changeOneYearPercentagePoints": -0.5},
                "exchangeRate": {"rate": 1450.0, "change20DayPercent": 2.3},
                "inflation": {"yearOnYearPercent": 2.1, "previousYearOnYearPercent": 1.7},
                "growth": {"quarterOnQuarterPercent": 0.6, "yearOnYearPercent": 2.4},
            }
        )

        self.assertEqual([regime["category"] for regime in regimes], ["INTEREST_RATE", "EXCHANGE_RATE", "INFLATION", "GROWTH"])
        self.assertEqual([regime["phase"] for regime in regimes], ["완화 기조", "원화 약세", "완만한 물가 상승", "확장"])

    def test_omits_a_category_when_its_comparison_value_is_unavailable(self):
        regimes = classify_market_regimes({"interestRate": {"rate": 2.5}})
        self.assertEqual(regimes, [])

    def test_monetary_policy_decision_overrides_interest_rate_rule(self):
        regimes = update_interest_rate_regime(
            classify_market_regimes({"interestRate": {"rate": 2.5, "changeOneYearPercentagePoints": -0.5}}),
            {"interestRate": {"rate": 2.5, "changeOneYearPercentagePoints": -0.5}},
            {"phase": "강한 인상 기조", "summary": "기준금리 인상과 추가 인상 필요성을 제시했습니다."},
        )
        self.assertEqual(regimes, [{"category": "INTEREST_RATE", "phase": "강한 인상 기조", "rationale": "기준금리 인상과 추가 인상 필요성을 제시했습니다."}])

    def test_appends_real_rate_pressure_to_monetary_policy_rationale(self):
        regime = build_interest_rate_regime(
            {"interestRate": {"realRate": 0.5, "realRateChangeThreeMonthsPercentagePoints": -0.8, "realRatePressure": "강한 하락 압력"}},
            {"phase": "동결 기조", "summary": "정책금리를 유지했습니다."},
        )
        self.assertIsNotNone(regime)
        self.assertIn("실질금리(기준금리−소비자물가 상승률)는 0.50%p", regime["rationale"])
        self.assertIn("강한 하락 압력", regime["rationale"])
