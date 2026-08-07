# FinDART collector

대한민국 정책브리핑의 **부처 브리핑**을 수집해 FinDART API에 적재합니다.

전체 수집·시장지표·금통위 기조·Today 재적재 흐름은 [운영 문서](docs/collector-pipeline.md)를 참고하세요.

## 실행

```bash
source .venv/bin/activate
pip install -e .

# 최근 목록의 첫 페이지를 조회하고, 적재할 데이터 미리 보기
findart-policy-briefing --limit 3

# 원문을 적재하고 NIM으로 다듬은 정책 브리핑을 API에 적재
export FINDART_TOKEN='…'
findart-policy-briefing --ingest --pages 2
```

`FINDART_URI`는 FinDART 서버의 base URL이며, 기본값은 `.env.example`의 값입니다.
Bearer 토큰은 `FINDART_TOKEN`으로 전달합니다. `--ingest`를 지정하지 않으면 외부 API에 쓰지 않는 미리 보기 모드입니다.

## 뉴스 RSS

`.env`의 `NEWS_RSS_URIS`에 RSS URL을 쉼표로 구분해 등록하면 여러 소스를 함께 수집합니다. 기본 예시는
[knews-rss의 경제 피드 목록](https://github.com/akngs/knews-rss/blob/main/data/feed_specs.csv)을 바탕으로 실제
응답을 확인한 8개 매체를 사용합니다. 한 피드가 실패해도 나머지 피드는 계속 처리하며, 여러 매체의 기사를
라운드로빈으로 합쳐 특정 매체가 일일 브리핑 입력을 독점하지 않도록 합니다.

```bash
findart-news-rss --limit-per-source 5

# RSS 발행일별로 원문을 적재하고 NIM 일일 브리핑을 생성·적재
findart-news-rss --ingest --limit-per-source 5
```

정책브리핑 수집기는 목록에서 상세 URL을 발견하고, 각 상세 페이지의 제목·발표일·발표자·본문을 추출합니다. 원문을 먼저 `/api/v1/collector/original-contents`에 적재하고, NVIDIA NIM이 자연어로 다듬은 본문을 반환된 ID와 함께 `/api/v1/collector/processed-contents/policy-briefings`에 적재합니다.

RSS 수집기는 원문을 먼저 적재한 뒤 RSS의 **발행일별**로 기사를 묶습니다. NVIDIA NIM이 각 묶음에 대한 일일 브리핑을 생성하면 `/api/v1/collector/processed-contents/daily-briefings`에 적재합니다. NIM 인증에는 `.env`의 `NVIDIA_NIM_API_KEY`와 `NVIDIA_NIM_MODEL`을 사용합니다.

`NVIDIA_NIM_FALLBACK_MODELS`에는 쉼표로 구분한 모델 ID를 넣습니다. 주 모델이 연결 오류, 404/410, 429 또는 5xx로 실패하면 순서대로 재시도합니다. 요청 형식 오류(4xx)는 다른 모델로 재시도하지 않고 즉시 보고합니다.

일일 브리핑 입력에는 FinanceDataReader의 KOSPI(`KS11`) 최근 거래일 종가·등락률과, `KOREA_BANK_ECOS_API_KEY`로 조회한 한국은행 ECOS 기준금리·원/달러 환율·소비자물가지수·계절조정 실질 GDP 증감률도 포함됩니다. 각 수치는 관측시점과 단위를 함께 전달하며, 한 데이터 소스가 실패해도 브리핑 적재는 계속됩니다.
