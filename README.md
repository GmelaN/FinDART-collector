# FinDART collector

대한민국 정책브리핑의 **부처 브리핑**을 수집해 FinDART API에 적재합니다.

## 실행

```bash
source .venv/bin/activate
pip install -e .

# 최근 목록의 첫 페이지를 조회하고, 적재할 데이터 미리 보기
findart-policy-briefing --limit 3

# 원문과 정책 브리핑을 API에 적재
export FINDART_TOKEN='…'
findart-policy-briefing --ingest --pages 2
```

`FINDART_URI`는 FinDART 서버의 base URL이며, 기본값은 `.env.example`의 값입니다.
Bearer 토큰은 `FINDART_TOKEN`으로 전달합니다. `--ingest`를 지정하지 않으면 외부 API에 쓰지 않는 미리 보기 모드입니다.

수집기는 목록에서 상세 URL을 발견하고, 각 상세 페이지의 제목·발표일·발표자·본문을 추출합니다. 원문을 먼저 `/api/v1/collector/original-contents`에 적재한 뒤 반환된 ID를 이용해 `/api/v1/collector/processed-contents/policy-briefings`에 적재합니다. 동일 문서는 `externalId`와 본문 SHA-256 체크섬을 사용하므로 API의 중복/개정 처리와 호환됩니다.

