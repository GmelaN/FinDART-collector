"""NVIDIA NIM client used to turn collected documents into reader-facing Korean."""

from __future__ import annotations

import json
from typing import Any, Callable, Iterable

import requests


NIM_CHAT_COMPLETIONS_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
MARKET_CATEGORIES = "INTEREST_RATE, EXCHANGE_RATE, INFLATION, GROWTH, EMPLOYMENT, TRADE"
MAX_DAILY_CONTEXT_CHARS = 24_000
MONETARY_POLICY_PHASES = "강한 인하 기조, 인하 기조, 동결 기조, 인상 기조, 강한 인상 기조"


class NimClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        fallback_models: Iterable[str] | None = None,
        session: requests.Session | None = None,
        timeout: float = 90.0,
    ) -> None:
        if not api_key:
            raise ValueError("NVIDIA_NIM_API_KEY를 설정하세요")
        if not model:
            raise ValueError("NVIDIA_NIM_MODEL을 설정하세요")
        self.api_key = api_key
        # NVIDIA API Catalog model IDs are provider-qualified, e.g.
        # nvidia/nemotron-3-ultra-550b-a55b. Keep fully-qualified custom IDs intact.
        self.model = self._model_id(model)
        self.models = list(dict.fromkeys([self.model, *(self._model_id(value) for value in fallback_models or [] if value.strip())]))
        self.session = session or requests.Session()
        self.timeout = timeout

    def rewrite_policy_briefing(self, *, title: str, body: str) -> str:
        result = self._complete(
            """당신은 한국 경제·정책 독자를 위한 편집자다. 제공된 정책브리핑만 근거로
핵심 내용과 영향이 명확한 자연스러운 한국어 본문으로 다듬어라. 새로운 사실, 수치,
해석을 만들지 말고, 인사말·중복·구어체는 제거한다. 반드시 JSON 객체만 반환한다:
{\"body\": \"다듬은 본문\"}. body는 비어 있으면 안 된다.""",
            {"title": title, "body": body},
            validator=self._validate_policy_result,
        )
        return result["body"].strip()

    def create_daily_briefing(
        self,
        articles: list[dict[str, str]],
        policy_briefings: list[dict[str, str]] | None = None,
        market_indicators: dict[str, object] | None = None,
        rule_based_market: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        return self._complete(
            f"""당신은 한국 금융 뉴스 편집자다. 뉴스 기사와 같은 날 발표된 정책브리핑을 함께
검토해 일일 브리핑을 만든다. marketIndicators에는 KOSPI 종가·등락률과 한국은행 ECOS의
기준금리, 원/달러 환율, 소비자물가, 실질 GDP 정보가 명시돼 있다. 해당 수치가 제공되면
수치·기준시점·단위를 정확히 반영해 금리(INTEREST_RATE), 환율(EXCHANGE_RATE), 물가(INFLATION),
성장(GROWTH) 판단에 활용하고, ruleBasedMarket이 제공되면 해당 category, phase, rationale을 market에
그대로 복사하라. 이를 해석·변경하거나 다른 market 항목을 추가하지 마라. 제공되지 않은 지표는 언급하거나 추정하지 마라. 정책브리핑은
시장·산업 영향의 맥락을 보완하는 근거이며, 기사나 정책 문서에 없는 사실을 추측하거나 추가하지 마라.
반드시 JSON 객체만 반환한다.
스키마: {{"title": "string", "summary": "string", "market": [{{"category":
"{MARKET_CATEGORIES} 중 하나", "phase": "string", "rationale": "string"}}],
"issueTitles": ["string"]}}. summary는 제목을 제외한 **700~1,100자 한국어**로 5~7개의
완결된 문장 또는 문단을 작성한다. (1) 오늘의 핵심 시장 흐름과 KOSPI 등락, (2) 이를 뒷받침하는
뉴스·정책·거시지표, (3) 업종·자산시장에 미칠 수 있는 영향, (4) 다음 거래일에 확인할 위험 또는
변수를 순서대로 연결하라. 각 문장은 제공된 근거를 밝혀 구체적으로 쓰되, 근거가 없는 원인·전망은
만들지 마라. 제공된 지표가 적으면 그 사실을 자연스럽게 설명하되 분량을 인사말이나 반복으로 채우지 마라.
스키마의 title, summary, market, issueTitles는 모두 반드시 포함해야 하며, market은 반드시 하나 이상이다.
명확한 시장 정보가 없으면
category는 GROWTH, phase는 "관망", rationale은 "제공된 기사에서 뚜렷한 시장 지표를 확인하기 어렵습니다."로 한다.""",
            self._daily_document(articles, policy_briefings or [], market_indicators or {}, rule_based_market or []),
            validator=self._validate_daily_result,
        )

    def classify_monetary_policy(self, *, title: str, body: str) -> dict[str, Any]:
        """Classify the latest Monetary Policy Board statement with cited evidence."""
        return self._complete(
            f"""당신은 한국은행 금융통화위원회 결정문을 분석하는 거시경제 애널리스트다.
제공된 결정문만 근거로 현재의 금리 정책 기조를 분류한다. 반드시 JSON 객체만 반환한다.
스키마: {{"phase": "{MONETARY_POLICY_PHASES} 중 하나", "decision": "HIKE|CUT|HOLD",
"currentRate": number, "summary": "string", "evidence": [{{"quote": "원문에서 그대로 가져온 짧은 문장", "reason": "분류 근거"}}]}}.
evidence는 1~3개이며 quote는 원문에 실제로 있는 문장만 사용한다.

판정 예시 1: 기준금리를 0.50%p 인하하고 '추가 인하 가능성을 열어둘 필요'가 있으면
phase는 '강한 인하 기조', decision은 CUT이다.
판정 예시 2: 기준금리를 0.25%p 인하했지만 '향후 물가와 금융안정을 점검'한다고 하면
phase는 '인하 기조', decision은 CUT이다.
판정 예시 3: 금리를 유지하면서 '현재 수준을 유지하면서 여건을 점검'한다고 하면
phase는 '동결 기조', decision은 HOLD이다.
판정 예시 4: 기준금리를 0.25%p 인상하고 물가 상방 위험을 강조하면
phase는 '인상 기조', decision은 HIKE이다.
판정 예시 5: 0.50%p 이상 인상하거나 물가·금융불균형 대응을 위해 추가 인상을 강하게 시사하면
phase는 '강한 인상 기조', decision은 HIKE이다.
결정 자체와 향후 운용 문구가 엇갈리면 향후 운용 문구를 반영하되, 원문에 없는 전망을 만들지 마라.
summary는 2~3문장으로 결정과 기조 근거를 한국어로 설명한다.""",
            {"title": title, "body": self._clip(body, 12_000)},
            validator=self._validate_monetary_policy_result,
        )

    def _complete(
        self,
        instruction: str,
        document: dict[str, Any],
        *,
        validator: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "temperature": 0.2,
            "reasoning_effort": "none",
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": instruction},
                {"role": "user", "content": json.dumps(document, ensure_ascii=False)},
            ],
        }
        failures: list[str] = []
        for model in self.models:
            try:
                response = self.session.post(
                    NIM_CHAT_COMPLETIONS_URL,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"model": model, **payload},
                    timeout=self.timeout,
                )
            except requests.RequestException as error:
                failures.append(f"{model}: 연결 오류 ({error})")
                continue
            if response.status_code in {404, 408, 409, 410, 429} or response.status_code >= 500:
                failures.append(f"{model}: HTTP {response.status_code}")
                continue
            if 400 <= response.status_code < 500:
                # The request is invalid for every model; do not send source
                # documents to further endpoints unnecessarily.
                raise RuntimeError(f"NIM 요청이 거절되었습니다 ({model}, HTTP {response.status_code}): {response.text[:1000]}")
            try:
                response.raise_for_status()
                result = self._json_result(response)
                if validator:
                    validator(result)
                return result
            except (requests.RequestException, RuntimeError) as error:
                failures.append(f"{model}: {error}")
        raise RuntimeError(f"NIM 모델이 모두 실패했습니다: {'; '.join(failures)}")

    @staticmethod
    def _model_id(model: str) -> str:
        value = model.strip()
        return value if "/" in value else f"nvidia/{value}"

    @staticmethod
    def _json_result(response: requests.Response) -> dict[str, Any]:
        try:
            content = response.json()["choices"][0]["message"]["content"]
            result = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
            raise RuntimeError("NIM 응답이 유효한 JSON이 아닙니다") from error
        if not isinstance(result, dict):
            raise RuntimeError("NIM 응답은 JSON 객체여야 합니다")
        return result

    @staticmethod
    def _daily_document(
        articles: list[dict[str, str]], policy_briefings: list[dict[str, str]], market_indicators: dict[str, object],
        rule_based_market: list[dict[str, str]],
    ) -> dict[str, object]:
        """Keep the NIM prompt below a predictable context budget.

        RSS summaries and policy bodies can be arbitrarily long.  The indicator
        block is small and retained in full; article and policy excerpts keep the
        leading factual content while preserving enough distinct sources.
        """
        document: dict[str, object] = {
            "articles": [
                {
                    "title": NimClient._clip(article.get("title", ""), 240),
                    "summary": NimClient._clip(article.get("summary", ""), 800),
                    "sourceUrl": article.get("sourceUrl", ""),
                    "publisher": NimClient._clip(article.get("publisher", ""), 120),
                }
                for article in articles[:12]
            ],
            "policyBriefings": [
                {
                    "title": NimClient._clip(briefing.get("title", ""), 240),
                    "body": NimClient._clip(briefing.get("body", ""), 1_000),
                    "publishedAt": briefing.get("publishedAt", ""),
                }
                for briefing in policy_briefings[:8]
            ],
            "marketIndicators": market_indicators,
            "ruleBasedMarket": rule_based_market,
        }
        # The per-document caps normally keep the JSON well below budget.  Drop
        # the least-recent policy documents, then articles, if URLs or unusually
        # dense text still make the request too large.
        while len(json.dumps(document, ensure_ascii=False)) > MAX_DAILY_CONTEXT_CHARS:
            policies = document["policyBriefings"]
            articles_context = document["articles"]
            if isinstance(policies, list) and policies:
                policies.pop()
            elif isinstance(articles_context, list) and articles_context:
                articles_context.pop()
            else:
                break
        return document

    @staticmethod
    def _clip(value: object, limit: int) -> str:
        text = str(value).strip()
        return text if len(text) <= limit else f"{text[:limit].rstrip()}…"

    @staticmethod
    def _validate_daily_result(result: dict[str, Any]) -> None:
        if not isinstance(result.get("title"), str) or not result["title"].strip():
            raise RuntimeError("NIM 일일 브리핑 응답에 title이 없습니다")
        if not isinstance(result.get("summary"), str) or not result["summary"].strip():
            raise RuntimeError("NIM 일일 브리핑 응답에 summary가 없습니다")
        market = result.get("market")
        if not isinstance(market, list) or not market:
            raise RuntimeError("NIM 일일 브리핑 응답에 market이 없습니다")
        for item in market:
            if not isinstance(item, dict) or item.get("category") not in MARKET_CATEGORIES.split(", "):
                raise RuntimeError("NIM 일일 브리핑의 market 형식이 올바르지 않습니다")
            if not all(isinstance(item.get(key), str) and item[key].strip() for key in ("phase", "rationale")):
                raise RuntimeError("NIM 일일 브리핑의 market 형식이 올바르지 않습니다")

    @staticmethod
    def _validate_policy_result(result: dict[str, Any]) -> None:
        if not isinstance(result.get("body"), str) or not result["body"].strip():
            raise RuntimeError("NIM 정책브리핑 응답에 body가 없습니다")

    @staticmethod
    def _validate_monetary_policy_result(result: dict[str, Any]) -> None:
        if result.get("phase") not in MONETARY_POLICY_PHASES.split(", "):
            raise RuntimeError("NIM 통화정책 분석의 phase가 올바르지 않습니다")
        if result.get("decision") not in {"HIKE", "CUT", "HOLD"}:
            raise RuntimeError("NIM 통화정책 분석의 decision이 올바르지 않습니다")
        if not isinstance(result.get("currentRate"), (int, float)):
            raise RuntimeError("NIM 통화정책 분석의 currentRate가 없습니다")
        if not isinstance(result.get("summary"), str) or not result["summary"].strip():
            raise RuntimeError("NIM 통화정책 분석의 summary가 없습니다")
        evidence = result.get("evidence")
        if not isinstance(evidence, list) or not 1 <= len(evidence) <= 3:
            raise RuntimeError("NIM 통화정책 분석의 evidence가 올바르지 않습니다")
        for item in evidence:
            if not isinstance(item, dict) or not all(isinstance(item.get(key), str) and item[key].strip() for key in ("quote", "reason")):
                raise RuntimeError("NIM 통화정책 분석의 evidence가 올바르지 않습니다")
