# examples

2026-07 기간 실행 결과에서 발췌한 예시입니다. 현재 운영 구조는 기간 실행과
PostgreSQL 문서 카탈로그·상태 JSONL을 기준으로 합니다.

| 파일 | 내용 |
|---|---|
| `dry_run_output.txt` | 단월 호환 dry-run 콘솔 출력 예시 |
| `crawl_summary_sample.json` | `99_운영/runs/.../summary.json` (layout_version=3) 대표 예시 |

실제 산출물은 파일 서버의 다음 위치에 생성됩니다.

개발 환경은 프로젝트 루트에서 `uv sync --locked`로 준비합니다. FastAPI와 내장
스케줄러는 `uv run uvicorn app.api.main:app` 또는 WSL2의
`docker compose up -d`로 실행하며, Docker에서는 파일 서버 mount를 `/data`로
연결합니다. 상태 파일은 `99_운영/state` 아래의 상대경로 JSONL로 남고, DB에는
기존 `rs_disclosure_documents` 카탈로그만 기록됩니다.

```
{BASE_OUTPUT_PATH}\상품공시실문서\
    01_문서\{보험사}\{YYYY}\{MM}\{판매상태}__{YYYYMMDD}_{상품명}\약관.pdf
    01_문서\{보험사}\{YYYY}\{MM}\{판매상태}__{YYYYMMDD}_{상품명}\상품요약서.pdf
    01_문서\{보험사}\{YYYY}\{MM}\{판매상태}__{YYYYMMDD}_{상품명}\사업방법서.pdf
    99_운영\state\{범위}\{보험사코드}\
        download_plan.v3.jsonl
        download_state.v3.jsonl
        detail_checkpoint.v2.jsonl    (KB·KYOBO_LIFE·DB_LIFE 등 상세 체크포인트 사용사)
        months.v3\
            {YYYY-MM}.json             (월별 plan 인덱스)
            monthly_index.json          (전체 월 인덱스)
    99_운영\state\status\{보험사코드}\folder_moves.v2.jsonl
    99_운영\runs\{YYYY}\{MM}\{DD}\{run_id}\summary.json (layout_version=3)
    99_운영\runs\{YYYY}\{MM}\{DD}\{run_id}\crawler.log
    99_운영\runs\{YYYY}\{MM}\{DD}\{run_id}\errors.jsonl
```

문서 기준일을 알 수 없는 버전은 `01_문서\{보험사}\날짜미상\{판매상태}__날짜미상_{상품명}`에
저장됩니다. 판매상태 접두사는 `판매중__`, `판매완료__`, `상태미상__`이며, 저장용 상품명은
경계 공백을 trim하고 내부 공백 run은 앞 또는 뒤의 `_`와 인접하면 제거하고, 그렇지 않으면 `_`로
치환합니다(`A _123.pdf` → `A_123.pdf`). 원본 상품명·다운로드 파일명은 PostgreSQL
`rs_disclosure_documents`의 `product_name`·`original_filename`에 보존됩니다.

권장 기간 실행:

```powershell
uv run python main.py --start-date 2026-07-01 --end-date 2026-07-31 --dry-run
```

기존 단월 호출도 호환됩니다(`uv run python main.py --target-month 2026-07 --dry-run`).
장기 수집이나 여러 달에 걸친 재현에는 `--start-date`와 `--end-date`를 사용합니다.

기본 실행은 DB·LOTTE·SAMSUNG·KB·MERITZ·MIRAE_LIFE·KYOBO_LIFE·DB_LIFE 8개사의 기존
`판매중` 상품 상태를 재검증합니다. `--no-refresh-active`는 이를 생략하고,
`--refresh-active-only`는 신규 문서 없이 상태·폴더만 갱신합니다. `--rename-dry-run`은
상태 폴더 이동과 기존 문서 경로를 미리보기만 하며, 실행 로그·요약·DB 시도 상태 등 운영 산출물은
기록될 수 있습니다. `--dry-run`도 문서 파일과 상태 폴더는 만들지 않지만 실행 결과·체크포인트·plan은
실행 방식에 따라 기록될 수 있습니다.

## 실행 검증 요약 (2026-07-31)

| 보험사 | dry-run 대상 버전 | 문서 링크 | 실제 다운로드 검증 |
|---|---:|---:|---|
| DB손해보험 | 6 | 18 | **18건 전량 SUCCESS** |
| 롯데손해보험 | 49 | 145 | 표본 2버전 6건 SUCCESS |
| 메리츠화재 | 179 | 491 | 표본 2버전 6건 SUCCESS |
| KB손해보험 | 1 (상품 40개 표본) | 3 | 표본 2건 SUCCESS → 재실행 시 DUPLICATE_SKIPPED |
| 삼성화재 | 137 | 387 | 표본 2버전 4건 SUCCESS |

- 실제 저장 파일 34개, 합계 107.1 MB, 전부 PDF 헤더·크기·SHA-256 검증 통과
- 재실행 시 **상품 상세 조회**는 회사별 `detail_checkpoint.v2.jsonl`로 재사용하고,
  **문서 다운로드**는 PostgreSQL 문서 상태·파일 SHA-256·`download_state.v3.jsonl` 중복 판정으로 재다운로드를 방지하는 구조입니다.
