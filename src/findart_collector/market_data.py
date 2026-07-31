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
        return indicators

    def _kospi(self, day: date) -> dict[str, object] | None:
        reader = self.fdr_reader
        if reader is None:
            import FinanceDataReader as fdr

            reader = fdr.DataReader
        # A few extra calendar days cover weekends and Korean market holidays.
        frame = reader("KS11", (day - timedelta(days=10)).isoformat(), day.isoformat())
        if frame is None or frame.empty or len(frame.index) < 2:
            return None
        recent = frame.tail(2)
        previous, latest = recent.iloc[0], recent.iloc[1]
        previous_close, close = float(previous["Close"]), float(latest["Close"])
        return {
            "source": "FinanceDataReader",
            "series": "KOSPI (KS11)",
            "date": recent.index[-1].date().isoformat(),
            "close": round(close, 2),
            "change": round(close - previous_close, 2),
            "changePercent": round((close / previous_close - 1) * 100, 2),
            "unit": "index points",
        }

    def _interest_rate(self, day: date) -> dict[str, object] | None:
        row = self._latest_ecos("722Y001", "D", day - timedelta(days=60), day, "0101000")
        return self._observation(row, "한국은행 기준금리", "ECOS", value_key="rate")

    def _exchange_rate(self, day: date) -> dict[str, object] | None:
        row = self._latest_ecos("731Y001", "D", day - timedelta(days=60), day, "0000001")
        return self._observation(row, "원/미국달러 매매기준율", "ECOS", value_key="rate")

    def _inflation(self, day: date) -> dict[str, object] | None:
        row = self._latest_ecos("901Y009", "M", day - timedelta(days=400), day, "0")
        observation = self._observation(row, "소비자물가지수 총지수", "ECOS", value_key="index")
        if observation is not None:
            observation["interpretation"] = "지수 수준이며, 전년동월 상승률이 아닙니다."
        return observation

    def _growth(self, day: date) -> dict[str, object] | None:
        rows = self._ecos_rows("200Y108", "Q", day - timedelta(days=900), day, "10601")
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
            [ECOS_BASE_URL, self.ecos_api_key, "json", "kr", "1", "100", table, cycle, start_time, end_time, item_code]
        )
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            return []
        rows = payload.get("StatisticSearch", {}).get("row", [])
        return [row for row in rows if isinstance(row, dict) and row.get("DATA_VALUE") not in (None, "")]

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
