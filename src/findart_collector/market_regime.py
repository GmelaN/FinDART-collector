"""Deterministic market-regime classification from collected indicator values."""

from __future__ import annotations

from typing import Any


def classify_market_regimes(indicators: dict[str, object]) -> list[dict[str, str]]:
    """Return API-compatible market regimes without relying on LLM interpretation."""
    regimes = []
    for classifier in (_interest_rate, _exchange_rate, _inflation, _growth):
        regime = classifier(indicators)
        if regime:
            regimes.append(regime)
    return regimes


def upsert_market_regime(regimes: list[dict[str, str]], update: dict[str, str]) -> list[dict[str, str]]:
    """Replace one category in a market array, retaining every other entry.

    This is the shared update primitive for interest rates now and exchange
    rates, inflation, and growth when they gain independent update jobs.
    """
    category = update.get("category")
    if not isinstance(category, str) or not category:
        raise ValueError("market update에 category가 없습니다")
    result = list(regimes)
    for index, regime in enumerate(result):
        if regime.get("category") == category:
            result[index] = update
            return result
    return [*result, update]


def build_interest_rate_regime(
    indicators: dict[str, object], monetary_policy: dict[str, object] | None = None,
) -> dict[str, str] | None:
    """Build the one canonical interest-rate market update.

    Monetary Policy Board wording determines the policy phase. ECOS remains the
    fallback phase source and always contributes real-rate pressure when it is
    available.
    """
    interest_rate = _mapping(indicators.get("interestRate"))
    policy_phase = monetary_policy.get("phase") if monetary_policy else None
    policy_summary = monetary_policy.get("summary") if monetary_policy else None
    if isinstance(policy_phase, str) and policy_phase.strip() and isinstance(policy_summary, str) and policy_summary.strip():
        rationale = policy_summary.strip()
        real_rate_text = _real_rate_text(interest_rate)
        if real_rate_text:
            rationale = f"{rationale} {real_rate_text}"
        return _regime("INTEREST_RATE", policy_phase.strip(), rationale)
    return _interest_rate(indicators)


def update_interest_rate_regime(
    regimes: list[dict[str, str]], indicators: dict[str, object],
    monetary_policy: dict[str, object] | None = None,
) -> list[dict[str, str]]:
    """Apply the canonical interest-rate update to an existing market array."""
    update = build_interest_rate_regime(indicators, monetary_policy)
    return upsert_market_regime(regimes, update) if update else regimes


def _interest_rate(indicators: dict[str, object]) -> dict[str, str] | None:
    data = _mapping(indicators.get("interestRate"))
    rate, yearly_change = _number(data, "rate"), _number(data, "changeOneYearPercentagePoints")
    if rate is None or yearly_change is None:
        return None
    if yearly_change >= 0.25:
        phase = "긴축 기조"
    elif yearly_change <= -0.25:
        phase = "완화 기조"
    else:
        phase = "동결"
    direction = "+" if yearly_change >= 0 else ""
    rationale = f"한국은행 기준금리는 {rate:.2f}%이며 1년 전 대비 {direction}{yearly_change:.2f}%p입니다."
    real_rate_text = _real_rate_text(data)
    return _regime("INTEREST_RATE", phase, f"{rationale} {real_rate_text}".strip())


def _exchange_rate(indicators: dict[str, object]) -> dict[str, str] | None:
    data = _mapping(indicators.get("exchangeRate"))
    rate, change = _number(data, "rate"), _number(data, "change20DayPercent")
    if rate is None or change is None:
        return None
    if change >= 2:
        phase = "원화 약세"
    elif change <= -2:
        phase = "원화 강세"
    else:
        phase = "보합"
    direction = "+" if change >= 0 else ""
    return _regime("EXCHANGE_RATE", phase, f"원/달러 환율은 {rate:,.1f}원으로 최근 20거래일 대비 {direction}{change:.2f}%입니다.")


def _inflation(indicators: dict[str, object]) -> dict[str, str] | None:
    data = _mapping(indicators.get("inflation"))
    yoy, previous_yoy = _number(data, "yearOnYearPercent"), _number(data, "previousYearOnYearPercent")
    if yoy is None:
        return None
    if yoy >= 3:
        phase = "물가 압력"
    elif yoy <= 1:
        phase = "물가 안정"
    else:
        phase = "완만한 물가 상승"
    trend = ""
    if previous_yoy is not None:
        trend = " 확대" if yoy - previous_yoy >= 0.2 else " 둔화" if previous_yoy - yoy >= 0.2 else " 유지"
    return _regime("INFLATION", phase, f"소비자물가 전년동월비는 {yoy:.2f}%로 전월 대비{trend or ' 변화가 제한적'}입니다.")


def _growth(indicators: dict[str, object]) -> dict[str, str] | None:
    data = _mapping(indicators.get("growth"))
    qoq, yoy = _number(data, "quarterOnQuarterPercent"), _number(data, "yearOnYearPercent")
    if qoq is None:
        return None
    if qoq <= 0 and (yoy is None or yoy <= 0):
        phase = "수축"
    elif qoq < 0.5 or (yoy is not None and yoy < 1):
        phase = "둔화"
    else:
        phase = "확장"
    yoy_text = f", 전년동기 대비 {yoy:.2f}%" if yoy is not None else ""
    return _regime("GROWTH", phase, f"계절조정 실질 GDP는 전기 대비 {qoq:.2f}%{yoy_text}입니다.")


def _mapping(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _number(data: dict[str, object], key: str) -> float | None:
    value = data.get(key)
    return float(value) if isinstance(value, (int, float)) else None


def _real_rate_text(data: dict[str, object]) -> str:
    real_rate = _number(data, "realRate")
    change = _number(data, "realRateChangeThreeMonthsPercentagePoints")
    pressure = data.get("realRatePressure")
    if real_rate is None or change is None or not isinstance(pressure, str):
        return ""
    direction = "+" if change >= 0 else ""
    return f"실질금리(기준금리−소비자물가 상승률)는 {real_rate:.2f}%p이며 3개월 전 대비 {direction}{change:.2f}%p로 {pressure}입니다."


def _regime(category: str, phase: str, rationale: str) -> dict[str, str]:
    return {"category": category, "phase": phase, "rationale": rationale}
