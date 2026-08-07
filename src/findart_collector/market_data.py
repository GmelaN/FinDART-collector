"""Market and ECOS indicators used as explicit daily-briefing context."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Callable

import requests


ECOS_BASE_URL = "https://ecos.bok.or.kr/api/StatisticSearch"


class MarketDataCollector:
    """Collect a compact, source-labelled context block for one briefing day.

    FinanceDataReader is imported only when KOSPI data is requested.  That keeps
    the collector usable when a macro-only deployment has not installed it yet.
    """

    def __init__(
        self,
        ecos_api_key: str | None = None,
        *,
        session: requests.Session | None = None,
        fdr_reader: Callable[..., Any] | None = None,
        timeout: float = 20.0,
    ) -> None:
        self.ecos_api_key = ecos_api_key or ""
        self.session = session or requests.Session()
        self.fdr_reader = fdr_reader
        self.timeout = timeout

    def collect(self, day: date) -> dict[str, object]:
        """Return available indicators; an unavailable source never stops ingestion."""
        indicators: dict[str, object] = {"asOf": day.isoformat()}
        for name, loader in (
            ("kospi", lambda: self._kospi(day)),
            ("interestRate", lambda: self._interest_rate(day)),
            ("exchangeRate", lambda: self._exchange_rate(day)),
            ("inflation", lambda: self._inflation(day)),
            ("growth", lambda: self._growth(day)),
        ):
            try:
                value = loader()
            except (ImportError, requests.RequestException, ValueError, KeyError, TypeError, IndexError):
                continue
            if value:
                indicators[name] = value
        self._attach_real_interest_rate(indicators)
        return indicators

    def _kospi(self, day: date) -> dict[str, object] | None:
        reader = self.fdr_reader
        if reader is None:
            import FinanceDataReader as fdr

            reader = fdr.DataReader
        # A few extra calendar days cover weekends and Korean market holidays.
        frame = reader("KS11", (day - timedelta(days=370)).isoformat(), day.isoformat())
        if frame is None or frame.empty or len(frame.index) < 2:
            return None
        recent = frame.tail(2)
        previous, latest = recent.iloc[0], recent.iloc[1]
        previous_close, close = float(previous["Close"]), float(latest["Close"])
        result: dict[str, object] = {
            "source": "FinanceDataReader",
            "series": "KOSPI (KS11)",
            "date": recent.index[-1].date().isoformat(),
            "close": round(close, 2),
            "change": round(close - previous_close, 2),
            "changePercent": round((close / previous_close - 1) * 100, 2),
            "unit": "index points",
        }
        for label, periods in (("change5DayPercent", 5), ("change20DayPercent", 20), ("changeOneYearPercent", 252)):
            if len(frame.index) > periods:
                past_close = float(frame.iloc[-(periods + 1)]["Close"])
                result[label] = round((close / past_close - 1) * 100, 2)
        return result

    def _interest_rate(self, day: date) -> dict[str, object] | None:
        rows = self._ecos_rows("722Y001", "D", day - timedelta(days=370), day, "0101000")
        observation = self._observation_with_history(rows, "한국은행 기준금리", "ECOS", value_key="rate", percentage_points=True)
        if observation is not None:
            monthly_rates: dict[str, float] = {}
            for row in rows:
                monthly_rates[str(row["TIME"])[:6]] = float(row["DATA_VALUE"])
            # Keep an extra month because the latest CPI publication can lag the
            # latest daily policy-rate observation by one calendar month.
            observation["recentMonthlyRates"] = [
                {"period": period, "rate": rate}
                for period, rate in list(monthly_rates.items())[-5:]
            ]
        return observation

    def _exchange_rate(self, day: date) -> dict[str, object] | None:
        rows = self._ecos_rows("731Y001", "D", day - timedelta(days=370), day, "0000001")
        return self._observation_with_history(rows, "원/미국달러 매매기준율", "ECOS", value_key="rate", periods=(5, 20, 252))

    def _inflation(self, day: date) -> dict[str, object] | None:
        # A three-month real-rate comparison needs four CPI year-on-year
        # observations. Each year-on-year observation needs the matching month
        # one year earlier, so allow at least 16 monthly rows plus publication
        # timing slack.
        rows = self._ecos_rows("901Y009", "M", day - timedelta(days=550), day, "0")
        observation = self._observation_with_history(rows, "소비자물가지수 총지수", "ECOS", value_key="index", periods=(1, 12))
        if observation is not None:
            latest = float(rows[-1]["DATA_VALUE"])
            if len(rows) > 12:
                observation["yearOnYearPercent"] = round((latest / float(rows[-13]["DATA_VALUE"]) - 1) * 100, 2)
            if len(rows) > 13:
                previous_yoy = (float(rows[-2]["DATA_VALUE"]) / float(rows[-14]["DATA_VALUE"]) - 1) * 100
                observation["previousYearOnYearPercent"] = round(previous_yoy, 2)
            yoy_history = [
                {
                    "period": str(rows[index]["TIME"]),
                    "yearOnYearPercent": round(
                        (float(rows[index]["DATA_VALUE"]) / float(rows[index - 12]["DATA_VALUE"]) - 1) * 100,
                        2,
                    ),
                }
                for index in range(12, len(rows))
            ]
            # Retain current plus the three months needed to measure the change.
            observation["recentYearOnYearPercent"] = yoy_history[-4:]
        return observation

    @staticmethod
    def _attach_real_interest_rate(indicators: dict[str, object]) -> None:
        """Add real-rate level and three-month pressure to the rate context.

        The real rate is the policy rate minus the CPI year-on-year inflation
        rate. Monthly policy-rate observations are aligned to CPI months; this
        prevents a daily observation gap from being mistaken for a rate change.
        """
        interest = indicators.get("interestRate")
        inflation = indicators.get("inflation")
        if not isinstance(interest, dict) or not isinstance(inflation, dict):
            return
        rates = interest.get("recentMonthlyRates")
        cpi_history = inflation.get("recentYearOnYearPercent")
        if not isinstance(rates, list) or not isinstance(cpi_history, list):
            return
        rates_by_period = {
            item.get("period"): item.get("rate")
            for item in rates
            if isinstance(item, dict) and isinstance(item.get("period"), str) and isinstance(item.get("rate"), (int, float))
        }
        real_rates = [
            {
                "period": item["period"],
                "rate": round(float(rates_by_period[item["period"]]) - float(item["yearOnYearPercent"]), 2),
            }
            for item in cpi_history
            if isinstance(item, dict)
            and isinstance(item.get("period"), str)
            and isinstance(item.get("yearOnYearPercent"), (int, float))
            and item["period"] in rates_by_period
        ]
        if len(real_rates) < 4:
            return
        recent = real_rates[-4:]
        latest, three_months_ago = recent[-1], recent[0]
        change = round(float(latest["rate"]) - float(three_months_ago["rate"]), 2)
        pressure = MarketDataCollector._real_rate_pressure(change)
        interest.update({
            "realRate": latest["rate"],
            "realRatePeriod": latest["period"],
            "realRateThreeMonthsAgo": three_months_ago["rate"],
            "realRateChangeThreeMonthsPercentagePoints": change,
            "realRatePressure": pressure,
            "recentRealRates": recent,
        })

    @staticmethod
    def _real_rate_pressure(change: float) -> str:
        if change >= 0.75:
            return "강한 상승 압력"
        if change >= 0.5:
            return "약한 상승 압력"
        if change <= -0.75:
            return "강한 하락 압력"
        if change <= -0.5:
            return "약한 하락 압력"
        return "유지"

    def _growth(self, day: date) -> dict[str, object] | None:
        rows = self._ecos_rows("200Y108", "Q", day - timedelta(days=370), day, "10601")
        if len(rows) < 2:
            return None
        latest, previous = rows[-1], rows[-2]
        value, previous_value = float(latest["DATA_VALUE"]), float(previous["DATA_VALUE"])
        result: dict[str, object] = {
            "source": "ECOS",
            "series": "계절조정 실질 GDP(국내총생산에 대한 지출)",
            "period": str(latest["TIME"]),
            "value": value,
            "unit": str(latest.get("UNIT_NAME", "")),
            "quarterOnQuarterPercent": round((value / previous_value - 1) * 100, 2),
        }
        if len(rows) >= 5:
            year_ago = float(rows[-5]["DATA_VALUE"])
            result["yearOnYearPercent"] = round((value / year_ago - 1) * 100, 2)
        return result

    def _latest_ecos(
        self, table: str, cycle: str, start: date, end: date, item_code: str
    ) -> dict[str, object] | None:
        rows = self._ecos_rows(table, cycle, start, end, item_code)
        return rows[-1] if rows else None

    def _ecos_rows(self, table: str, cycle: str, start: date, end: date, item_code: str) -> list[dict[str, object]]:
        if not self.ecos_api_key:
            return []
        start_time, end_time = self._ecos_time(cycle, start), self._ecos_time(cycle, end)
        url = "/".join(
            [ECOS_BASE_URL, self.ecos_api_key, "json", "kr", "1", "1000", table, cycle, start_time, end_time, item_code]
        )
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            return []
        rows = payload.get("StatisticSearch", {}).get("row", [])
        return sorted(
            (row for row in rows if isinstance(row, dict) and row.get("DATA_VALUE") not in (None, "")),
            key=lambda row: str(row.get("TIME", "")),
        )

    @staticmethod
    def _ecos_time(cycle: str, value: date) -> str:
        if cycle == "D":
            return value.strftime("%Y%m%d")
        if cycle == "M":
            return value.strftime("%Y%m")
        if cycle == "Q":
            return f"{value.year}Q{(value.month - 1) // 3 + 1}"
        raise ValueError(f"지원하지 않는 ECOS 주기: {cycle}")

    @staticmethod
    def _observation(
        row: dict[str, object] | None, series: str, source: str, *, value_key: str
    ) -> dict[str, object] | None:
        if row is None:
            return None
        return {
            "source": source,
            "series": series,
            "period": str(row["TIME"]),
            value_key: float(row["DATA_VALUE"]),
            "unit": str(row.get("UNIT_NAME", "")),
        }

    @staticmethod
    def _observation_with_history(
        rows: list[dict[str, object]], series: str, source: str, *, value_key: str,
        periods: tuple[int, ...] = (), percentage_points: bool = False,
    ) -> dict[str, object] | None:
        if not rows:
            return None
        latest = rows[-1]
        latest_value = float(latest["DATA_VALUE"])
        result: dict[str, object] = {
            "source": source,
            "series": series,
            "period": str(latest["TIME"]),
            value_key: latest_value,
            "unit": str(latest.get("UNIT_NAME", "")),
        }
        for period in periods:
            if len(rows) <= period:
                continue
            past_value = float(rows[-(period + 1)]["DATA_VALUE"])
            suffix = {1: "One", 5: "5Day", 12: "12Month", 20: "20Day", 252: "OneYear"}.get(period, str(period))
            result[f"change{suffix}{'PercentagePoints' if percentage_points else 'Percent'}"] = round(
                latest_value - past_value if percentage_points else (latest_value / past_value - 1) * 100,
                2,
            )
        if percentage_points and len(rows) > 1:
            result["changeOneYearPercentagePoints"] = round(latest_value - float(rows[0]["DATA_VALUE"]), 2)
        return result
