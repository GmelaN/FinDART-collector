# FinDART 수집·Today 브리핑 파이프라인

이 문서는 정책브리핑, 경제 뉴스 RSS, 시장·거시지표 및 한국은행 금융통화위원회 결정문을 FinDART에 적재하고 Today 브리핑을 만드는 흐름을 설명한다.

## 구성과 데이터 흐름

```text
정책브리핑 ──────────────> 원문 적재 ─> NIM 편집 ─> 정책 브리핑 적재

RSS 뉴스 ─┬─> 원문 적재 ─┐
정책 브리핑 ─────────────┼─> NIM 일일 브리핑 ─> Daily Briefing 적재 ─> Today
시장·ECOS 지표 ──────────┤
금통위 결정문 ─> NIM 5단계 분류 ┘
```

RSS 일일 브리핑의 `market.INTEREST_RATE`는 ECOS 시계열 규칙보다 금통위 결정문 분류를 우선한다. 환율·물가·성장 항목은 ECOS 기반 규칙을 사용한다.

## 실행 명령

모든 명령은 프로젝트 가상환경을 활성화하고 `.env`를 읽는다.

```bash
# 정책브리핑 미리 보기 / 적재
findart-policy-briefing --limit 3
findart-policy-briefing --ingest --pages 2

# 뉴스 RSS 미리 보기 / 일일 브리핑 적재
findart-news-rss --limit-per-source 5
findart-news-rss --ingest --limit-per-source 5

# 최신 금통위 결정문 분류 미리 보기 / 원문·정책 브리핑·Today 갱신
findart-bok-monetary-policy
findart-bok-monetary-policy --ingest
```

`--ingest`가 없는 명령은 외부 쓰기를 하지 않는다. `findart-bok-monetary-policy --ingest`는 기본적으로 오늘(UTC)의 Today 브리핑을 대상으로 한다. 다른 날짜를 지정하려면 다음과 같이 실행한다.

```bash
findart-bok-monetary-policy --ingest --today-date 2026-08-07
```

## 환경 변수

| 변수 | 용도 |
| --- | --- |
| `FINDART_URI` | FinDART API base URL |
| `FINDART_TOKEN` | Collector Bearer 토큰 |
| `NEWS_RSS_URIS` | 쉼표로 구분한 경제 RSS URL 목록 |
| `NVIDIA_NIM_API_KEY` | NVIDIA NIM 인증 키 |
| `NVIDIA_NIM_MODEL` | 주 NIM 모델 |
| `NVIDIA_NIM_FALLBACK_MODELS` | 쉼표로 구분한 폴백 모델 목록 |
| `KOREA_BANK_ECOS_API_KEY` | ECOS API 키 |

NIM 요청은 OpenAI 호환 Chat Completions API로 전송하며 `reasoning_effort: none`을 사용한다. 연결 오류 및 일시적 오류(404, 408, 409, 410, 429, 5xx)는 폴백 모델을 순서대로 시도한다. 요청 자체가 잘못된 4xx는 폴백하지 않는다.

## 정책브리핑과 RSS

정책브리핑 수집기는 목록에서 상세 URL을 찾아 제목·발표일·발표자·본문을 추출한다. 원문은 먼저 `/api/v1/collector/original-contents`에 적재하고, NIM 편집본은 `/api/v1/collector/processed-contents/policy-briefings`에 적재한다.

RSS 수집기는 여러 피드를 라운드로빈으로 섞고 URL 중복을 제거한다. 한 피드 실패는 다른 피드 처리를 중단시키지 않는다. 기사는 RSS 발행일별로 묶이며, 같은 날짜의 FinDART 정책브리핑도 일일 브리핑 프롬프트에 함께 넣는다. NIM에 보내는 기사·정책 본문은 길이 제한을 적용해 추론 입력을 제어한다.

## 시장·거시지표

일일 브리핑에는 다음 수치와 관측시점을 명시적으로 전달한다.

| 항목 | 원천 | 기본 규칙 결과 |
| --- | --- | --- |
| KOSPI | FinanceDataReader `KS11` | 종가·등락률을 브리핑 근거로 사용 |
| 기준금리 | ECOS | 금통위 분류 실패 시 긴축·완화·동결 규칙 및 실질금리 압력 사용 |
| 원/달러 환율 | ECOS | 원화 약세·강세·보합 |
| 소비자물가 | ECOS | 물가 압력·안정·완만한 물가 상승 |
| 실질 GDP | ECOS | 수축·둔화·확장 |

각 데이터 원천은 독립적으로 실패 처리한다. 일부 지표 조회가 실패해도 뉴스 원문 및 일일 브리핑 적재는 계속된다.

### 실질금리 압력

기준금리의 일별 ECOS 자료와 CPI 전년동월비 월별 자료를 월 단위로 맞춰 실질금리(`명목 기준금리 - CPI 상승률`)를 계산한다. CPI 전년동월비 4개와 각 전년도 기준월이 필요하므로 CPI는 약 18개월을 조회한다. CPI 공표시차를 고려해 최근 4개 공통 월 관측치를 보관하며, 최신값과 3개월 전 값을 비교한다.

| 3개월 실질금리 변화량 | 표시 문자열 |
| --- | --- |
| `x >= +0.75%p` | 강한 상승 압력 |
| `+0.50%p <= x < +0.75%p` | 약한 상승 압력 |
| `-0.50%p < x < +0.50%p` | 유지 |
| `-0.75%p < x <= -0.50%p` | 약한 하락 압력 |
| `x <= -0.75%p` | 강한 하락 압력 |

금리 `rationale`에는 실질금리 수준, 3개월 변화량 및 위 압력 문자열을 표시한다. 금통위 기조가 우선 적용되는 날에도 이 문구는 기조 판정 근거 뒤에 이어서 표시된다.

금리 업데이트는 공통 market-regime upsert 단위로 구현되어 RSS 일일 브리핑 생성과 `findart-bok-monetary-policy --ingest`의 Today 재적재가 동일한 결과를 사용한다. 이 단위는 특정 `category`만 교체하고 나머지 market 항목을 보존하므로, 환율·물가·성장 독립 갱신도 같은 방식으로 추가할 수 있다.

## 금통위 결정문과 금리 기조

### 수집

한국은행의 `newsData/list.do`는 검색 화면만 반환한다. 실제 결과 행은 `newsData/listCont.do`에서 비동기로 반환되므로 수집기는 이 엔드포인트를 사용한다.

- 검색어: `금융통화위원회`
- 연도 필터: 실행 시점의 4자리 연도 (`date=YYYY`)
- 페이지 크기: 50
- 후보 중 제목이 `통화정책방향(YYYY.M.D)`인 게시물만 선택
- 상세 본문: `P0000559/view.do?nttId=...`의 `.dbdata`

목록에 함께 나타나는 금통위 의사록은 제목 필터로 제외한다.

### 분류

결정문 본문을 NIM 구조화 출력으로 분류한다. 출력에는 `phase`, `decision`, `currentRate`, `summary`, `evidence`가 포함되며, `evidence`는 원문 인용과 판정 근거를 가진다.

`phase`는 다음 다섯 값 중 하나다.

1. 강한 인상 기조
2. 인상 기조
3. 동결 기조
4. 인하 기조
5. 강한 인하 기조

일일 RSS 적재 시 이 결과가 존재하면 `market.INTEREST_RATE`의 `phase`와 `rationale`을 결정문 분류 결과로 교체한다. 수집 또는 분류가 실패하면 기존 ECOS 기반 금리 규칙을 그대로 사용한다.

## Today 브리핑 재적재

Today 응답에는 `indicatorCards`가 아니라 `market` 배열이 있다. 따라서 금통위 기조는 Today의 `market` 중 `category: INTEREST_RATE` 항목에 반영한다.

공개 OpenAPI에는 Today 수정용 PUT/PATCH가 없다. 갱신은 다음의 명세상 GET/POST 흐름으로 수행한다.

1. `GET /api/v1/today?date=YYYY-MM-DD`로 Today ID를 가져온다.
2. `GET /api/v1/processed-contents/{id}`로 `source`, `externalId`, 원문 ID, 수집 시각 및 전체 `content`를 가져온다.
3. 전체 `DailyBriefingIngestion` payload를 복원하고 `market.INTEREST_RATE`만 변경한다.
4. `POST /api/v1/collector/processed-contents/daily-briefings`로 재적재한다.

이 방식은 제목, 요약, 다른 시장 국면, 헤드라인, 이슈, 이벤트와 원문 연결 정보를 보존한다.

## 진행 표시와 검증

RSS 피드 조회, 정책브리핑 목록·문서 수집, 원문 적재, 일일 브리핑 생성에는 `tqdm` 진행 표시를 사용한다. 환경에 `tqdm`이 없을 경우 수집 자체는 진행되도록 무표시 폴백을 제공한다.

전체 단위 테스트는 다음 명령으로 실행한다.

```bash
./.venv/bin/python -m unittest discover -s tests -v
```
