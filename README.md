# 보험사 상품공시 문서 자동 다운로드

보험사 상품공시실에서 지정한 **기간(시작일~종료일)** 동안 등록·적용·판매개시된 상품 버전을 조회하고,
해당 상품에 연결된 **약관 / 상품요약서 / 사업방법서** 원본 파일을 자동으로 내려받아
파일 서버에 저장하는 CLI 프로그램입니다.

`crawler/company_catalog.py`에는 **생명보험 18개사 + 손해보험 12개사 = 30개사**가 등록되어 있고,
그중 **28개사에 Adapter가 구현**되어 있습니다(HTTP 26 · Playwright 1 · 하이브리드 1).
`FUBON_HYUNDAI_LIFE`, `HANWHA_FIRE`는 `ACCESS_RESTRICTED`로 등록되어 전체 실행에서는 제외되고,
명시적으로 선택하면 수집을 시작하기 전에 오류로 종료합니다.

현재 운영 상태의 정본은 `crawler/company_catalog.py`(보험사·Adapter 상태),
`config.yaml`/`config.container.yaml`(실행·출력 설정), PostgreSQL
`rs_disclosure_documents`(문서 최신 상태)입니다. 아래 결과 보고서와 사이트 분석 문서는
날짜가 표시된 역사 기록이므로 현재 상태 판단에 사용하지 않습니다.

### 손해보험 (기존 PoC 5개사)

| 코드 | 보험사 | 수집 방식 |
|---|---|---|
| DB | DB손해보험 | 공시실 화면 JSON API 재현 (기간검색) |
| LOTTE | 롯데손해보험 | 공시실 화면 검색형 폼 POST 재현 (1회 조회) |
| MERITZ | 메리츠화재 | Playwright(헤드풀) + 페이지 내 API 호출 |
| KB | KB손해보험 | 폼 POST + 정적 HTML 파싱 |
| SAMSUNG | 삼성화재 | 공시실 화면 JSON API 재현 (전량 조회) |

### 확장 구현 (신규 Adapter 23개사 중 대표 목록)

아래는 주요 구현 사례를 보여주는 대표 목록입니다. 전체 등록 Adapter는 23개 신규 보험사이며,
각 회사의 실제 엔드포인트와 검증 상태는 [ENDPOINT_MATRIX.md](docs/ENDPOINT_MATRIX.md)와
`docs/sites/{코드}.md`에서 확인할 수 있습니다.

| 코드 | 보험사 | 구분 | 수집 방식 |
|---|---|---|---|
| KYOBO_LIFE | 교보생명 | 생명 | JSON API (목록 + 판매기간 상세) |
| MIRAE_LIFE | 미래에셋생명 | 생명 | JSON API (페이징) |
| DB_LIFE | DB생명 | 생명 | 정적 HTML + 약관 팝업 (구형 TLS) |
| IBK_LIFE | IBK연금보험 | 생명 | 정적 HTML 4개 화면 (EUC-KR) |
| IM_LIFE | iM라이프 | 생명 | 폼 POST (`sellType`) |
| KB_LIFE | KB라이프생명 | 생명 | JSON API (탭 + 페이징) |
| METLIFE | 메트라이프생명 | 생명 | 정적 HTML + 특약 팝업 |
| HANA_LIFE | 하나생명 | 생명 | 폼 POST (`status`) |
| HANA_NON_LIFE | 하나손해보험 | 손보 | JSON API 4단계 드릴다운 |
| HYUNDAI_MARINE | 현대해상 | 손보 | JSON API (`ajax.xhi`) |
| HEUNGKUK_FIRE | 흥국화재 | 손보 | 폼 POST (mode × type × page) |

### 문서

| 문서 | 내용 |
|---|---|
| [SITE_ANALYSIS.md](SITE_ANALYSIS.md) | 기존 5개사 상세 분석 원본 (Historical Snapshot — 2026-07-31) |
| [docs/sites/](docs/sites/) | **30개사 개별 분석** (`{코드}.md`) |
| [docs/SITE_ANALYSIS_30.md](docs/SITE_ANALYSIS_30.md) | 30개사 수집 방식·화면 구조·공통화 요소 분류 |
| [docs/ENDPOINT_MATRIX.md](docs/ENDPOINT_MATRIX.md) | 30개사 엔드포인트 매트릭스 + 구현 상태 |
| [docs/BASELINE_RESULT.md](docs/BASELINE_RESULT.md) | 확장 전 기준 상태 (Historical Snapshot) |
| [docs/IMPLEMENTATION_RESULT.md](docs/IMPLEMENTATION_RESULT.md) | 구현 결과·변경 파일·미해결 문제 (Historical Snapshot — 2026-08-06) |
| [docs/REGRESSION_TEST_RESULT.md](docs/REGRESSION_TEST_RESULT.md) | 회귀 및 신규 테스트 결과 (Historical Snapshot — 2026-08-04) |
| [docs/UNIMPLEMENTED_COMPANY_ANALYSIS.md](docs/UNIMPLEMENTED_COMPANY_ANALYSIS.md) | 2026-08-04 미구현 조사 기록 (Historical Snapshot) |
| [docs/REMAINING_14_IMPLEMENTATION_RESULT.md](docs/REMAINING_14_IMPLEMENTATION_RESULT.md) | 2026-08-04 중간 구현 결과 (Historical Snapshot) |

> **처음 이어받는 분은 [13. 프로젝트 구조와 주요 로직](#13-프로젝트-구조와-주요-로직-인수인계용) 부터 보세요.**
> 코드를 어디부터 읽어야 하는지, 무엇을 고치면 되는지, 사이트별 함정이 무엇인지 정리해 두었습니다.

> 운영 수집 범위는 **상품·상품 버전·문서 메타데이터 수집과 원본 파일 다운로드**입니다.
> 개발·검증용으로 명시한 로컬 PDF를 복사해 페이지 텍스트·표를 파일 산출물로
> 만드는 `load` CLI가 추가되었습니다. OCR, LLM 추출, 임베딩과 신규 적재/검색 DB 구조는
> 아직 포함하지 않으며 기존 수집 카탈로그의 상태 조회와 UPSERT 흐름은 그대로 유지합니다.

### 개발용 PDF Load

PDF 한 개를 Load합니다.

```powershell
python main.py load --pdf "C:\data\보험약관.pdf"
```

여러 PDF는 `--pdf`를 반복해서 지정하며 각각 독립적으로 처리합니다.

```powershell
python main.py load `
  --pdf "C:\data\보험약관.pdf" `
  --pdf "C:\data\사업방법서.pdf" `
  --pdf "C:\data\상품요약서.pdf"
```

결과는 `artifacts/load_test` 바로 아래에 PDF별 고유 폴더로 생성됩니다. 실행 단위
manifest·summary·log는 만들지 않습니다. 원본 PDF, 원문·정제문·LLM 입력문,
페이지 JSONL과 표 Markdown/XLSX를 보존합니다.

PDF Load 산출물 계약(v6)은 처리 단계가 폴더 이름에 드러나도록 PDF별 산출물을
다음과 같이 저장합니다.

```text
artifacts/load_test/
└── YYYYMMDD_HHMMSS_<PDF명>/
    ├── 00_input/
    │   └── 원본파일.pdf
    ├── 01_extracted/
    │   ├── pages.jsonl
    │   ├── raw_text.txt
    │   └── pages/
    │       └── page_XXXX.txt
    ├── 02_tables/
    │   ├── tables.jsonl
    │   ├── page_XXXX_table_XXX.md
    │   ├── page_XXXX_table_XXX.xlsx
    │   └── page_XXXX_table_XXX.png  # 원본 PDF 표 영역 시각 보존본
    ├── 02_images/
    │   ├── images.jsonl
    │   └── page_XXXX_image_XXX.<ext>
    ├── 03_processed/
    │   ├── content.md
    │   ├── pages.jsonl
    │   ├── tables/
    │   │   ├── page_XXXX_table_XXX.md
    │   │   └── page_XXXX_table_XXX.response.json
    │   └── pages/
    │       └── page_XXXX.md
    ├── 90_debug/
    │   ├── cropped.pdf
    │   └── header_footer_analysis.json
    └── 99_result/
        ├── load_manifest.json
        └── warnings.jsonl
```

`00_input`은 복사한 원본을 보존하고, `01_extracted`는 PDF에서 직접 읽은
원문·페이지 품질을 담습니다. `01_extracted/pages/page_XXXX.txt`는 페이지별 원문
열람본입니다. `02_tables`는 유의미한 표와 데이터 조각의 Markdown/XLSX 및 원본 영역 PNG 캡처를,
`02_images`는 PDF 내장 이미지와 이미지 JSONL을 담습니다. 동일 바이트의 이미지는
SHA-256으로 중복을 제거하고 이미지 레코드의 `occurrences`에 페이지·좌표를 기록합니다.
페이지 이미지 참조와 중복 이미지 occurrence는 페이지 번호 및 `(상단, 좌측, 하단, 우측)`
좌표순으로 정렬합니다.
`03_processed`는 정제문과 최종 LLM 입력 Markdown을 담습니다. `tables`에는 모든 저장 표의
최종 사용본을 두고, 실제 LLM 호출 표에는 최초 요청과 재시도를 모두 보존한
`*.response.json`을 함께 저장합니다. `pages`에는 페이지별 Markdown을 저장합니다. 실제
청킹은 LLM 추출 방식을 확정한 뒤 별도 단계로 추가합니다.
`90_debug`는 헤더·푸터 검증용이며, `99_result/load_manifest.json`은 원본·버전·상태·
집계·산출물 경로의 단일 정본입니다. 표·이미지·경고 목록은 한 레코드씩 처리할 수 있는
JSONL 정본으로 저장합니다. 페이지별 TXT/MD와 전체 TXT/MD는 사람이 확인하는 파생
산출물입니다. 세부 파일 계약은 [로드 설계.md](로드%20설계.md)를 참고하세요.

`text_content`는 PDF 본문의 일반 텍스트를 유지하고, Markdown 문법 충돌을 막기 위한
이스케이프는 `content_markdown`에만 적용합니다. `warnings.jsonl`은 고정된 `code`와
별도 `page_no`·표/후보 순번·`message` 필드를 사용하므로 오류 종류를 안정적으로
집계할 수 있습니다.

이미지는 작은 장식성 객체는 제외하고, 실제 내장 이미지는 `extraction_mode=EMBEDDED`로
저장합니다. 표 후보는 저장 전에 `MEANINGFUL`, `FRAGMENT`, `REJECTED`로 판정합니다.
빈 표, 단일 셀 제목 박스와 공통 라벨로만 구성된 1행 헤더는 `REJECTED`로 분류해
표 파일을 만들지 않고 일반 본문으로 보존합니다. 1열 텍스트는 실제 보장 목록일 수 있으므로
상위 표에 같은 내용이 이미 포함된 경우에만 중복으로 제외합니다. 1행이라도 숫자·금액·
비율이 있거나 페이지 경계에서 이어질 가능성이 있는 후보는 `FRAGMENT`로 보존합니다.
`MEANINGFUL`과 `FRAGMENT` 표는 같은 `table_id`의 `02_tables/*.png`로도
보존합니다. PNG는 MD/XLSX를 다시 그리지 않고 원본 PDF의 bbox에 2pt 여백을 더해
2배 배율로 렌더링합니다. 독립적인 행·열을 가진 중첩 표는 바깥 표와 내부 표를 모두
저장하고 각각 순차적으로 LLM에 전달하되, 페이지 Markdown에는 최상위 바깥 표만 넣어
내용을 중복하지 않습니다. 바깥 표에 이미 포함된 1차원 라벨 조각만 중복 후보로 제외합니다.
페이지 Markdown에는
`> 이미지 참조: <image_id> (<상대경로>)` 형식의 참조를 페이지 내 좌표 순서로
결합합니다. `load_manifest.json`의 `image_count`는 중복 제거 후 내장 이미지 파일 수,
`table_image_count`는 성공적으로 생성된 표 PNG 수입니다. PNG 생성 실패는
`TABLE_RENDER_FAILED` 경고로 남기되 나머지 PDF Load는 계속 진행합니다. 표 PNG 생성 시
원본 PDF는 문서당 한 번만 열고, 개별 표 렌더링 실패는 해당 표에만 격리합니다.
`detected_table_count`, `table_count`, `fragment_table_count`, `rejected_table_count`로
검출·저장·조각·제외 수를 구분하고, 제외 사유와 최소 판정 지표는 `warnings.jsonl`에
`TABLE_CANDIDATE_REJECTED`로 기록합니다.

헤더·푸터 제거는 기본적으로 꺼져 있으며 `.env`에서 다음 값으로 제어합니다.

```dotenv
PDF_LOAD_HEADER_FOOTER_ENABLED=false
```

표 LLM 재구성은 별도 토글로 제어합니다. 개발용 `.env`에서는 ON이며, OFF이면 네트워크를
호출하지 않고 원본 표 Markdown을 `03_processed/tables`에 그대로 복사합니다.

```dotenv
PDF_LOAD_TABLE_RECONSTRUCTION_ENABLED=true
LLM_BASE_URL=https://gemma4-31b-mtp.proxy.ainexus.ktcloud.com/v1
LLM_MODEL=gemma-4-31B-it
LLM_API_KEY=
LLM_REQUEST_TIMEOUT_SECONDS=120
LLM_MAX_OUTPUT_TOKENS=8192
```

`MEANINGFUL` 표만 표 PNG와 원본 Markdown을 함께 사용해 한 번에 하나씩 호출합니다.
중첩 표, 빈 셀 비율 25% 이상, 최장 셀 120자 이상은 설명형 Markdown으로 받고 그 외는
Markdown 표로 받습니다. 응답 형식이나 숫자 토큰 검증이 실패하면 한 번 재시도하며,
다시 실패하면 원본 표로 대체하고 문서 상태를 `PARTIAL`로 기록합니다. 공급자의 원본 JSON
응답은 이미지 base64와 인증정보를 제외하고 표별 `*.response.json`에 모든 시도분을 보존합니다.

활성화하면 3페이지 이상 문서에서 전체 페이지의 80% 이상 반복되는 상·하단 문장만
정제문에서 제외합니다. OCR 품질 판정에서는 설정과 관계없이 반복 헤더·푸터와 정상
추출된 표 영역의 중복 텍스트를 제외합니다. 핵심 표·이미지 추출 경고가 있으면 문서
상태는 `PARTIAL`로 기록합니다. 상세 계약은 [로드 설계.md](로드%20설계.md)를 참고하세요.

#### PDF Load 추후 진행 사항

현재 Load 결과를 실제 상품 데이터 추출과 DB 적재로 연결하기 전에 다음 작업을
순차적으로 보완할 예정입니다.

- 무선 표·병합 셀·여러 페이지에 걸친 연속 표 처리
- 헤더 자동 추론 및 표 원본 셀 JSON 보존
- 2단 문서의 열 구분과 읽기 순서 개선
- 스캔 페이지를 위한 실제 OCR 엔진 연동
- PDF별 subprocess timeout 및 강제 종료를 통한 오류 격리
- DB 문서 목록 연동과 LLM 기반 Product Profile·Detail 추출

이미지 산출물 계약과 구현 범위는 [로드 설계.md](로드%20설계.md)를, 추후 진행 사항은
[로드 설계.md의 추후 진행](로드%20설계.md#10-추후-진행)에
정리되어 있습니다.

---

## 1. 설치

```powershell
# Python 3.12 (Docker/Xvfb 검증 기준과 동일)
cd insurance-document-crawler
uv sync --locked

# 메리츠화재 수집에 필요 (브라우저 자동화)
uv run playwright install chromium
```

FastAPI 백엔드는 다음처럼 실행합니다. APScheduler는 FastAPI lifespan에서
파이썬 라이브러리로 함께 시작되고 종료되므로 별도 scheduler 프로세스를 띄우지
않습니다.

```powershell
uv run uvicorn app.api.main:app --host 0.0.0.0 --port 8000
```

Docker Desktop의 WSL2 Linux 엔진에서는 API 컨테이너 하나만 기동합니다.
Windows 작업 스케줄러는 사용하지 않습니다. 내장 scheduler는 매일
03:00(Asia/Seoul)에 전날 하루를 수집하며, PostgreSQL advisory lock과 기존
보험사별 lock으로 중복 실행을 막습니다.

최초 1회 Docker Desktop의 `Settings > Resources > WSL Integration`에서
`Oracle9`을 활성화하고 적용합니다. 그다음 Oracle9 WSL에서 Windows 로그인
자격증명을 재사용해 파일 서버를 mount합니다. SMB 비밀번호는 저장소나 Compose에
기록하지 않습니다.

```bash
# 파일서버 mount 최초 설정: Oracle9 WSL 안에서 실행
sudo mkdir -p /mnt/fileserver
sudo mount -t drvfs //Fileserver/data /mnt/fileserver
mountpoint /mnt/fileserver
```

평소에는 Windows PowerShell에서 프로젝트 폴더로 먼저 이동한 뒤 Oracle9에
진입합니다. 이 PC에서는 PowerShell의 현재 경로가 WSL의 `/mnt/c/...` 경로로
그대로 이어지는 것을 확인했습니다.

```powershell
cd C:\Users\taeksin\FAS\IPR\insurance-document-crawler
wsl -d Oracle9
```

프롬프트가 Oracle9 Linux로 바뀌면 현재 위치와 파일서버 mount를 확인하고
Compose를 실행합니다.

```bash
pwd
# /mnt/c/Users/taeksin/FAS/IPR/insurance-document-crawler

mountpoint /mnt/fileserver

# 시작
docker compose up -d

# 종료할 때
docker compose down
```

처음 실행하거나 소스·`uv.lock`·Dockerfile이 바뀐 뒤에는 같은 명령에
`--build`만 붙여 이미지를 갱신합니다. 이후 평소 시작·종료는 위의 짧은 두
명령만 사용합니다.

```bash
docker compose up -d --build
```

현재 `docker-compose.yml`의 기본 서비스는 scheduler가 내장된 `api` 하나이므로
서비스 이름이나 `-f` 옵션을 붙이지 않아도 됩니다. 이전 버전의 별도 `scheduler`
컨테이너가 남아 있는 환경에서 최초 전환할 때만
`docker compose up -d --remove-orphans`를 한 번 사용합니다.

컨테이너 종료 시 실행 중인 수집의 잠금·체크포인트 정리가 끝날 때까지 기다립니다.
기본 최대 대기 시간은 30분이며 `API_STOP_GRACE_PERIOD`로 조정할 수 있습니다.
그 시간을 넘겨 강제 종료했다면 재기동 전에 잠금을 확인하고 필요한 회사만 감사
이력을 남기며 해제합니다.

```bash
docker compose --profile manual run --rm collector --lock-status
docker compose --profile manual run --rm collector --force-unlock DB
```

`CRAWLER_OUTPUT_HOST_PATH`는 반드시 `상품공시실문서` 자체가 아니라 그 부모인
`IPR`을 가리켜야 합니다. Compose는 이 경로를 `/data`로 연결하고
`config.container.yaml`이 `/data/상품공시실문서`를 사용합니다. source가 없으면
빈 로컬 폴더를 만들지 않고 시작에 실패합니다. WSL 재시작 후에는 mount를 다시
실행하거나 [docker/wsl/fileserver.fstab](docker/wsl/fileserver.fstab)을
Oracle9의 `/etc/fstab`으로 설치해야 합니다. 이 파일에는 자격증명이 없으며
컨테이너의 비-root `pwuser`(UID/GID 1001)에 쓰기 권한을 매핑합니다.

처음 mount한 환경에서는 원자 쓰기·rename·JSONL append·회사 lock을 실제 파일
서버에서 먼저 검증합니다. 그다음 수동 수집은 일회성 collector 프로필을
사용합니다.

```bash
docker compose --profile manual run --rm --entrypoint /app/.venv/bin/python collector \
  /app/scripts/smoke_test_storage.py --config /app/config.container.yaml

docker compose --profile manual run --rm collector \
  --target-month 2026-07 --company DB --max-versions 1 --no-refresh-active
```

Compose에서 `API_PORT`는 호스트 공개 포트로만 사용합니다. 컨테이너 내부 API는
항상 `8000`에서 대기하므로 `.env`에 `API_PORT`를 지정하면 `호스트포트:8000`으로
연결됩니다. 컨테이너 내부 포트를 변경하지 마세요(healthcheck도 8000을 사용합니다).

고정 기간이 필요하면 `IPR_SCHEDULE_TARGET_MONTH=YYYY-MM` 또는
`IPR_SCHEDULE_START_DATE`와 `IPR_SCHEDULE_END_DATE`를 함께 지정합니다.
`IPR_SCHEDULE_PERIOD_MODE=config`은 **해당 config 파일에 `target_month`가
설정된 경우에만** 사용할 수 있으며, 값이 없으면 scheduler가 시작 단계에서
오류로 종료합니다. 별도 기간을 지정하지 않을 때의 기본값은 `previous_day`입니다.

### 기존 PostgreSQL 연결

의존성은 `pyproject.toml`과 `uv.lock`으로 관리합니다. `uv.lock`을 기준으로
환경을 동기화하므로 설치 시 임의로 버전이 올라가지 않습니다.

```powershell
uv sync --locked
Copy-Item .env.example .env  # .env가 없을 때만
# 기존 외부 DB의 RS_DB_* 접속정보를 .env에 입력
```

API와 수집기는 `.env`의 기존 외부 PostgreSQL에 연결하며, 기존
`rs_disclosure_documents` 카탈로그를 조회하고 UPSERT합니다. 이 단계에서는 DB
스키마나 테이블을 추가하지 않습니다. 현재 런타임 identity는 `DOC_`/`PROD_VER_`
접두사와 Base62 10자리 본문을 사용하는 `identity_version=4`입니다.

스키마 정의와 적용 도구는 `database/schema/`와
`scripts/apply_database_schema.py`에 있으며, 운영 DB 관리자가 필요할 때만
schema 001~007을 순서대로 적용합니다. 런타임 readiness는 필수 컬럼·v4 제약·DB
권한·advisory lock·outbox 쓰기를 수집 전에 확인합니다. `source_metadata`에는
최상위 identity 컬럼을 중복 저장하지 않고 source locator와 실행 provenance만
보존합니다.

운영 상태를 점검할 때는 읽기 전용 도구를 사용합니다.

```powershell
# .env의 RS_DB_*로 접속해 비민감 스키마·상태 요약만 출력
uv run python scripts/inspect_database_state.py

# 로컬 DB outbox를 payload 없이 점검
uv run python scripts/manage_db_outbox.py --path "<outbox.jsonl>" inspect

# 이벤트 격리는 사람 이름 대신 감사 식별자와 사유를 남기는 명시적 조작
uv run python scripts/manage_db_outbox.py --path "<outbox.jsonl>" quarantine `
  --event-id "<event-id>" --reason "<사유>" --approval-id "<run_id>@<computer>:<pid>"
```

`inspect_database_state.py`는 DB를 읽기만 합니다. `manage_db_outbox.py`의
`quarantine`는 pending 이벤트를 변경하므로 승인·사유를 먼저 확인하고 실행하며,
원본 outbox와 감사 기록은 임의로 삭제하지 않습니다.

수집 결과는 파일 서버의 상대경로를 기준으로 기록됩니다. Windows 경로를 코드나
`.env`에 하드코딩하지 말고 Compose의 `/data` bind mount와
`config.container.yaml`의 `output.base_path`를 사용하세요. 로컬 재시도 상태와
DB outbox는 `99_운영/state` 아래에 저장되며, 문서 파일은
`01_문서/{보험사}/{연도}/{월}/{판매상태}__{기준일}_{상품명}/`에 생성됩니다.

## 2. 실행

수집 기간은 반드시 명시해야 합니다. `--start-date`와 `--end-date`를 함께 지정하거나
호환용 단월 옵션 `--target-month`를 사용하세요. 기간 없이 실행하는 명령은 지원하지
않습니다.

```powershell
# 권장: 기간 지정(새로 등록·개정된 버전만 수집)
uv run main.py --start-date 2024-01-01 --end-date 2026-08-20

# 단월 호환 실행
uv run main.py --target-month 2026-07

# 특정 보험사만
uv run main.py --target-month 2026-07 --company DB
uv run main.py --target-month 2026-07 --company DB --company SAMSUNG

# 다운로드 없이 대상만 확인 (권장: 실제 실행 전 항상 먼저)
uv run main.py --start-date 2024-01-01 --end-date 2026-08-20 --dry-run

# 이전 실행에서 실패한 항목만 재시도
uv run main.py --start-date 2024-01-01 --end-date 2026-08-20 --retry-failed

# 테스트용 상한 (KB처럼 전수 조회가 오래 걸리는 사이트용)
uv run main.py --target-month 2026-07 --company KB --dry-run --max-products 50
uv run main.py --target-month 2026-07 --company SAMSUNG --max-versions 2

# 장기 기간 백필: 기간 실행은 다운로드 plan과 월별 인덱스를 자동 생성
uv run main.py --start-date 2024-01-01 --end-date 2026-08-20 --company KB --dry-run

# 생성된 plan으로 목록/상세 재수집 없이 실제 파일 다운로드
uv run main.py --download-plan "<99_운영/state/{범위}/KB/download_plan.v3.jsonl>"
```

### KB 장기 기간 수집

KB 상품 목록에는 날짜가 없으므로 목록 전체와 상품별 상세를 한 번씩 조회합니다. 상세에는
상품의 모든 판매기간·개정 버전과 문서 링크가 있으므로 `--start-date`~`--end-date`가 길어져도
월별로 목록/상세를 반복하지 않습니다. 상세 전체를 한 번 수집한 뒤 공통 기간 필터로 버전을
선정하고 판매개시일 기준 월별 plan 인덱스를 만듭니다.

KB 상세 결과는 범위별 `99_운영/state/{범위}/KB/detail_checkpoint.v2.jsonl`에 상품 단위로 즉시 기록됩니다. 중단 후 같은
기간을 다시 실행하면 일반 수집의 완료 상품은 사이트에 재요청하지 않고 실패·미완료 상품만 이어서 조회합니다.
단, DB에서 `판매중`(`ACTIVE`)으로 남아 있는 상품은 판매상태 재검증을 위해 완료 체크포인트가 있어도
상품 상세를 다시 조회합니다. 상태 재검증을 끄려면 `--no-refresh-active`를 사용합니다.
실제 다운로드는 생성된 plan을 사용하므로 KB 목록과 상세를 다시 조회하지 않습니다.

### 실행 시간 참고 (2026-07 실측)

| 보험사 | 대상 월 조회 | 비고 |
|---|---|---|
| 삼성화재 | 1.4초 | API 1회로 전량(9,404건) 수신 |
| 롯데손해보험 | 3.4초 | 검색 1회로 전량(4,391건) 수신 |
| DB손해보험 | 12초 | 서버가 기간 필터링 지원 |
| 메리츠화재 | 149초 | 브라우저 기동 + 분류별 조회 |
| **KB손해보험** | **약 2시간 30분** | 목록에 날짜가 없어 약 4,000개 상품 상세를 모두 조회 |

문서 다운로드 시간은 별도이며, 대상 문서 수 × (요청 간격 2초 + 전송 시간)입니다.
약관 PDF는 건당 10MB를 넘는 경우가 흔합니다.

### CLI 옵션

| 옵션 | 설명 |
|---|---|
| `--config PATH` | 설정 파일 경로 (기본 프로젝트 루트의 `config.yaml`) |
| `--target-month YYYY-MM` | 호환용 단월 실행. `--start-date`/`--end-date` 대신 사용 |
| `--start-date YYYY-MM-DD` | 권장 기간 수집 시작일. `--end-date`와 함께 사용하며 `--target-month`와 동시 사용 불가 |
| `--end-date YYYY-MM-DD` | 권장 기간 수집 종료일 |
| `--company CODE` | 특정 보험사만 실행 (여러 번 지정 가능) |
| `--dry-run` | 문서 파일과 상태 폴더는 변경하지 않고 대상 상품 수·문서 링크 수·수집 방식·예상 저장 경로·누락 문서 수를 산출. 실행 로그·요약·DB의 `DRY_RUN` 시도·체크포인트/plan은 기록될 수 있음 |
| `--write-plan` | 월 실행에서도 재수집 없는 다운로드 plan과 월별 인덱스를 생성 |
| `--download-plan PATH` | `99_운영/state/{범위}/{보험사코드}/download_plan.v3.jsonl`을 사용해 목록·상세 재수집 없이 파일 다운로드 |
| `--retry-failed` | DB에 기록된 이전 실패 항목만 다시 시도 |
| `--no-refresh-active` | DB의 기존 `판매중` 상품 상태 재확인을 생략 (기본값은 재확인) |
| `--refresh-active-only` | 기존 `판매중` 상품 상태·폴더만 갱신하고 신규 문서는 다운로드하지 않음 |
| `--rename-dry-run` | 판매상태 폴더 이동과 기존 문서 경로는 변경하지 않고 미리보기. 신규 수집 흐름의 DB 상태·로그 등 운영 산출물은 기록될 수 있음 |
| `--max-products N` | 보험사별 **조회할 상품 수** 상한(테스트용). 사용 시 결과에 `coverage_capped` 로 명시 |
| `--max-versions N` | 보험사별 **처리할 상품 버전 수** 상한(테스트용). 사용 시 결과에 `coverage_capped` 로 명시 |
| `--verbose` | 상세 로그 |
| `--lock-status` | 현재 실행 중인 보험사 잠금 확인 후 종료 |
| `--force-unlock CODE` | 비정상 종료로 남은 보험사 잠금을 감사 이력과 함께 명시적으로 해제 |

> `--max-products` / `--max-versions` 로 범위를 제한하면 로그·콘솔 요약·`summary.json` (layout_version=3)에
> 몇 건을 조회하지 않았는지가 함께 남습니다. 조용히 잘라내지 않습니다.

기본 실행은 DB의 기존 판매중 상품을 다시 확인합니다. 상태 재검증 대상은 현재
`DB`, `LOTTE`, `SAMSUNG`, `KB`, `MERITZ`, `MIRAE_LIFE`, `KYOBO_LIFE`, `DB_LIFE`의
8개사입니다. 신규 문서 수집만 하려면 `--no-refresh-active`, 상태 갱신만 하려면
`--refresh-active-only`를 사용합니다. `--rename-dry-run`은 상태 변경 폴더 이동을 미리
보되 기존 상태 폴더와 해당 DB 경로는 바꾸지 않습니다. 일반 신규 문서 수집은
계속 실행되므로 문서 파일 생성을 막으려면 기존 `--dry-run`을 사용합니다. `--dry-run`도
로그·요약·DB 시도 상태·체크포인트·plan 같은 운영 산출물은 기록할 수 있습니다.

활성 상태 재검증은 완전한 목록을 받은 경우에만 기존 `판매중` 행의 상태를 갱신합니다.
상품이 한 번 누락된 것만으로는 즉시 종료 처리하지 않으며, 완전한 목록에서 2회 연속
누락될 때 `상태미상__`으로 전환합니다. 상태가 `판매완료`로 확인되면 해당 상품의 모든
문서 행을 `판매완료__` 폴더로 함께 이동하고 DB의 `saved_relative_path`와
`status_*` 이력을 갱신합니다.

**종료 코드**: `0` 정상 / `1` 실패 항목 있음 / `2` 설정 오류 / `3` 파일 서버 접근 실패 / `4` 보험사 실행 잠금 충돌

---

## 3. 저장 위치와 구조

`config.yaml` 의 `output.base_path`와 `output.root_folder` 아래에 다음 구조로 저장됩니다.

```
{BASE_OUTPUT_PATH}
└── 상품공시실문서
    ├── 01_문서
    │   └── {보험사 한글명}/{YYYY}/{MM}/{판매상태}__{YYYYMMDD}_{상품명}
    │       ├── 약관.pdf
    │       ├── 상품요약서.pdf
    │       └── 사업방법서.pdf
    └── 99_운영
        ├── state/{범위}/{보험사코드}
        │   ├── download_plan.v3.jsonl
        │   ├── download_state.v3.jsonl
        │   ├── detail_checkpoint.v2.jsonl
        │   └── months.v3/
        ├── state/status/{보험사코드}/folder_moves.v2.jsonl
        ├── runs/{YYYY}/{MM}/{DD}/{run_id}
        │   ├── summary.json             # layout_version=3
        │   ├── errors.jsonl
        │   └── events/{보험사코드}.jsonl
        ├── staging/{run_id}/{보험사코드}/.upload_*.{확장자}  # 네트워크 업로드 중간 파일
        └── locks
```

- 문서 경로는 `01_문서/{보험사}/{연도}/{월}/{판매상태}__{YYYYMMDD}_{상품명}`으로 고정합니다.
  기준일이 없으면 `날짜미상/{판매상태}__날짜미상_{상품명}`에 저장합니다.
- 판매상태 접두사는 정규화 값에 따라 `판매중__`, `판매완료__`, `상태미상__` 중 하나입니다.
- 저장 경로 구성요소는 경계 공백을 제거하고, 내부 공백 run은 앞 또는 뒤의 `_`와 인접하면 제거하고
  그렇지 않으면 `_` 하나로 치환합니다(`A _123.pdf` → `A_123.pdf`). 원본 상품명과 원본
  다운로드 파일명은 DB의 `product_name`·`original_filename`에 그대로 보존합니다.
- 문서 폴더와 파일명에는 상품ID·버전ID·해시를 넣지 않습니다. 내부 식별자와 원본 메타데이터는
  PostgreSQL `rs_disclosure_documents`에 기록합니다.
- 문서 파일명은 `약관.pdf`, `상품요약서.pdf`, `사업방법서.pdf`처럼 문서유형만 사용합니다.
  같은 폴더에 같은 유형이 다시 저장되면 기존 파일을 보존하고 `_2`, `_3`을 붙입니다.
- 런타임은 `02_수집목록`, `manifest.csv`, `manifest.json`, `MANIFEST.lock`을 생성하거나 읽지
  않습니다. 수집 상태는 PostgreSQL 카탈로그와 `99_운영/state`의 JSONL 체크포인트에 기록합니다.
- `99_운영`은 재시작 체크포인트, 실행별 업무 오류·이벤트 저널, 잠금을 보관합니다. 애플리케이션
  로그는 이 폴더가 아니라 `IPR_LOG_DIR`의 일별 공통 로그에 기록합니다. 네트워크 파일 서버를
  출력 루트로 사용할 때 다운로드 검증 전 `.part` 파일은 로컬 TEMP 아래 격리 staging에
  저장됩니다. 검증 후 파일서버 `99_운영/staging/{run_id}/{보험사코드}`의
  `.upload_*.pdf` 임시 파일로 복사된 다음 같은 공유 볼륨 안에서 원자적으로 이동합니다.
  로컬 출력 테스트/개발에서는 기존
  `99_운영/staging/{run_id}/{보험사코드}`를 사용합니다. 비정상 종료로 남은 `.part`·`.upload_*`
  파일은 다음 실행에서 해당 staging 경로를 탐지해 로그에 남기며 자동 삭제하지 않습니다.
  `90_기존구조`나 레거시 백업 폴더는 만들지 않습니다.

### 공통 애플리케이션 로거

수집·스케줄러·API·PDF Load는 모두 `app.core.ipr_logger`의 공통 로거를 사용합니다.
`utils/crawler_logger.py`는 기존 import 호환용 인터페이스만 유지합니다. 로그는
`IPR_LOG_DIR/log_YYYY-MM-DD.log`에 KST 날짜 기준으로 기록되며 수집 실행 폴더나
PDF Load 산출물 내부에는 별도 로그 파일을 만들지 않습니다.

- 콘솔과 리다이렉션된 stdout/stderr는 UTF-8로 처리합니다.
- `DEBUG`·`INFO`는 stdout, `WARNING` 이상은 stderr로 분리하며 표준 로그 레벨만 사용합니다.
- ANSI 색상은 실제 TTY 콘솔의 `[INFO]`, `[WARNING]` 같은 로그 레벨에만 적용하고 파일 로그에서는 제거합니다.
- 일별 로그와 `errors.jsonl`은 UTF-8(BOM 없음)으로 저장합니다.
- 수집 로그에는 `run_id`, PDF Load 로그에는 `artifact_id`, API 로그에는 `X-Request-ID`가 trace ID로 포함됩니다.
- 파일 로그 생성에 실패해도 실행은 중단하지 않고 콘솔 로그를 계속 사용합니다.
- 일별 로그는 자동 삭제하지 않습니다.

판매중 상품 재검증에서 명시적인 판매 종료가 확인되면 기존 상품 폴더를
`판매중__...`에서 `판매완료__...`로 이동하고 관련 DB 문서 행의 경로를 함께
갱신합니다. 완전한 목록에서 한 번 보이지 않은 것만으로 종료 처리하지 않으며, 2회 연속
누락이면 `상태미상__...`으로 전환합니다. 조회 제한·접근 거부·응답 해석 실패처럼 목록이
불완전한 실행에서는 기존 상태와 경로를 유지합니다. 폴더 이동은
`99_운영/state/status/{보험사코드}/folder_moves.v2.jsonl`에 기록하고 DB 문서 행이 모두
갱신된 경우에만 확정되며, 중간 종료 시 다음 실행에서 이어서 복구합니다.

### 중복 처리 (기존 파일은 삭제·덮어쓰지 않음)

| 상황 | 처리 |
|---|---|
| 같은 파일명 + SHA-256 동일 | 다운로드 생략, `DUPLICATE_SKIPPED` |
| 같은 문서 폴더·유형 + 내용 다름 | `_2`, `_3` … 로 별도 보관 |
| 이전 실행에서 성공 기록 + 파일·해시 일치 | 재다운로드 생략 (체크포인트) |

### 공동 실행과 보험사 잠금

- 서로 다른 보험사는 동시에 실행할 수 있습니다.
- 같은 보험사는 대상 월이 달라도 동시에 실행할 수 없습니다. 문서 회사 폴더를 공유하기 때문입니다.
- 공동 사용자는 모두 잠금 기능이 포함된 같은 버전의 코드를 사용해야 합니다. 이전 버전 프로세스는 lock 을 인식하지 못합니다.
- 한 프로세스는 보험사 하나의 lock 만 잡고 처리가 끝나면 즉시 해제하므로 여러 보험사 실행에서 교착되지 않습니다.
- 비정상 종료로 lock 이 남으면 `uv run main.py --lock-status` 로 소유자를 확인한 뒤
  `uv run main.py --force-unlock DB` 처럼 명시적으로 해제합니다.
- 사람 이름은 수집 DB·summary·lock·감사 이력에 기록하지 않습니다.
- 잠금 소유자와 강제 해제 이력은 `run_id`, PC, PID, 시작 시각, Git commit으로 식별합니다.
- `.env`는 Git에서 제외하며 PostgreSQL(`RS_DB_*`)뿐 아니라 Compose 파일 서버
  mount(`CRAWLER_OUTPUT_HOST_PATH`), 호스트 API 포트(`API_PORT`), 내장 scheduler
  (`IPR_SCHEDULE_*`), 종료 대기 시간(`*_STOP_GRACE_PERIOD`) 설정에도 사용합니다.

---

## 4. 대상 기간 선정 기준

사이트마다 제공하는 날짜가 다르므로 다음 우선순위로 `target_date` 를 정하고,
어떤 종류를 썼는지 `date_basis` 로 반드시 기록합니다.

1. 문서 적용일 / 개정일 → `revision_date`
2. 상품 판매개시일 → `sale_start_date`
3. 공시일 / 등록일 → `disclosure_date`
4. 위 날짜가 없으면 판매기간 시작일 → `sale_period_start`

대부분의 사이트는 개정일/공시일을 별도로 제공하지 않으므로, 그런 버전은 판매개시일을
`target_date`로 사용하고 `date_basis = sale_start_date`로 기록합니다.

선정 방식은 `config.yaml` 의 `date_selection.mode` 로 바꿉니다.

| mode | 동작 | 비고 |
|---|---|---|
| `new_or_revised` (기본) | 대상 월에 **새로 등록/개정된** 버전만 | 요구사항 §6 단서조항 |
| `overlap` | 판매기간이 대상 월과 **겹치는 모든** 버전 | 건수가 매우 커집니다(삼성화재 기준 수천 건) |

기준 날짜가 없어도 판매종료일이 대상 월보다 이전이면 이미 종료된 상품으로 확정해 제외합니다.
판매종료 여부까지 판단할 수 없는 버전만 제외하지 않고 `MANUAL_REVIEW_REQUIRED` 로 기록합니다.

---

## 5. 문서유형 판별

| 사이트 표시명 | 저장 문서유형 | 폴더명 |
|---|---|---|
| 약관, 보통약관, 특별약관, 보험약관, 상품약관 | `POLICY` | 약관 |
| 상품요약서, 상품요약, 요약서, 요약 | `SUMMARY` | 상품요약서 |
| 사업방법서, 사업방법 | `METHOD` | 사업방법서 |

기본 제외: 보험료 예시 / 가입설계서 / 핵심설명서 / 비교안내서 / 확인서 / 안내장 / 브로슈어 /
**상품설명서** / 청약서.

문서명이 불명확하면 제외하지 않고 `UNKNOWN_DOCUMENT_TYPE` 으로 기록합니다.
키워드는 모두 `config.yaml` 에서 변경할 수 있습니다.

---

## 6. 다운로드 검증

파일 확장자가 `.pdf` 로 표시되어도 실제 응답을 다음 순서로 검증합니다.

1. HTTP 상태 코드 200 (403 은 `ACCESS_DENIED`)
2. Content-Type 이 허용 목록에 포함
3. 파일 크기 0바이트 아님
4. HTML 오류 페이지 아님 (웹방화벽 차단 응답은 `ACCESS_DENIED`)
5. 파일 시그니처 확인 (PDF `%PDF-`, ZIP/HWPX/DOCX `PK`, HWP 5.x/DOC OLE 헤더 또는 HWP 3.x 전체 인식 정보 `HWP Document File V3.00` + 제어 바이트)
6. 저장 후 파일을 다시 열어 크기·헤더 재확인
7. SHA-256 계산
8. 파일 크기 기록

허용 확장자: `.pdf .hwp .hwpx .doc .docx .zip` — PDF 가 아니어도 **원본 형식 그대로** 저장합니다.

---

## 7. 요청 속도 / 재시도 / 접근 제한

```yaml
request_interval_seconds: 2          # 요청 간 최소 간격
max_concurrent_requests_per_domain: 1
request_timeout_seconds: 30
max_retries: 3
retry_backoff_seconds: [3, 10, 30]
retry_status_codes: [408, 429, 500, 502, 503, 504]
```

- `403` 또는 CAPTCHA/웹방화벽 차단이 확인되면 **우회하지 않고** `ACCESS_DENIED` 로 기록합니다.
- 비공개 관리자 API·인증 우회·접근통제 우회 기능은 구현하지 않았습니다.

---

## 8. 실행 결과물

### PostgreSQL 문서 상태

모든 기간·보험사의 최신 문서 상태는 PostgreSQL
`rs_disclosure_documents`가 정본입니다. 링크 없는 항목은 발견 즉시, 실제 다운로드 항목은
redirect 최종 URL을 확정한 직후이자 파일 검증·저장 전에 `PENDING`을 기록합니다. 처리가 끝나면
성공·중복·실패 상태를 문서 한 건의 짧은 transaction으로 즉시 UPSERT합니다. 수집 전체가
끝날 때까지 메모리에 모아 두지 않습니다.

`product_version_key`는 동일 상품의 한 판매 버전을 묶는 상위
`PROD_VER_[Base62 10자리]` 코드이고, `document_key`는 그 상품 버전에 속한 개별 문서를
식별하는 하위 `DOC_[Base62 10자리]` 코드입니다.
두 키는 SHA-256이 아니며, DB의 `document_id`는 내부 행 식별자로 별도 유지합니다.
주요 필드는 `document_key`, `product_version_key`, 보험사·상품·판매기간, 문서 종류와
원본 URL, `saved_relative_path`, `file_size`, `sha256`, `file_status`,
`last_attempt_status`, `last_attempt_at`, 실행 ID입니다. 사이트 원문 판매상태와 비밀값을
제거한 어댑터별 메타데이터도 별도 필드에 보존합니다.

DB 연결이 문서 처리 중 끊기면 1회 재연결을 시도합니다. 그래도 반영되지 않은 결과는
출력 루트별 해시로 격리된 `LOCALAPPDATA/insurance-document-crawler/{output_hash}/state/db_outbox`
아래 로컬 `db_outbox` JSONL에 내구성 있게 기록하고 해당 보험사 수집을 중단합니다.
`LOCALAPPDATA`를 사용할 수 없으면 저장소의 `.local_state`를 fallback으로 사용합니다.
TEMP staging과 분리되어 재부팅·임시파일 정리 뒤에도 보존됩니다. 다음 실행은 새 문서를 처리하기 전에 outbox를 재생하며, 손상된 outbox는
건너뛰지 않고 안전하게 중단합니다. 다른 보험사는 별도 실행 단위이므로 계속 처리할 수
있습니다.
ACK 기록이나 원본 JSONL이 운영 임계값을 넘으면 회사 lock 안에서 ACK 완료 이벤트만
원자적으로 compact합니다. pending 이벤트와 격리된 원본·감사 기록은 보존됩니다.

### 다운로드 상태값

| 상태 | 의미 |
|---|---|
| `SUCCESS` | 정상 다운로드·검증 완료 |
| `DUPLICATE_SKIPPED` | 동일 해시 파일이 이미 있거나 체크포인트로 생략 |
| `NO_DOCUMENT_LINK` | 문서 링크 없음 |
| `INVALID_RESPONSE` | HTTP 오류 / HTML 응답 / Content-Type 불일치 |
| `INVALID_FILE` | 0바이트 / 시그니처 불일치 / 저장 후 검증 실패 |
| `DOWNLOAD_FAILED` | 네트워크 오류, 저장 실패 |
| `ACCESS_DENIED` | 403 또는 웹방화벽 차단 (우회하지 않음) |
| `UNKNOWN_DOCUMENT_TYPE` | 문서유형 판별 불가 (제외하지 않고 기록) |
| `MANUAL_REVIEW_REQUIRED` | 기준 날짜와 유효한 판매종료 정보를 모두 확인할 수 없어 자동 판단 불가 |
| `DRY_RUN` | `--dry-run` 으로 링크만 수집 |

### `summary.json` (layout_version=3)

실행 ID, 대상 기간, 선정 방식, 보험사별 수집 방식·상품 수·버전 수·문서 링크 수·
상태 집계·누락 문서 수·소요 시간과 실행 ID·PC·PID·Git 커밋이 기록됩니다. 최상위에는
`refresh_active`, `refresh_active_only`, `rename_dry_run` 플래그와 함께
`artifact_paths`, `plan_paths`, `companies`, `status_counts`,
`total_records`, `locked_companies`, `failed_companies`, `run_status`가 포함됩니다.
보험사별 `companies.{코드}`에는 `active_status_candidates`, `active_status_observed`,
`active_status_*` 재검증·폴더 이동 집계가 필요할 때 추가됩니다.
경로는 `99_운영/runs/{YYYY}/{MM}/{DD}/{run_id}/summary.json` (layout_version=3)이며 다른 실행이 덮어쓰지 않습니다.

---

## 9. 중단 후 재실행 (체크포인트)

- 성공한 문서 URL 은 재다운로드하지 않습니다.
- DB의 문서 행을 읽고 **파일 존재 여부와 SHA-256** 을 함께 확인합니다.
  (DB에는 성공으로 남아 있어도 파일이 없거나 해시가 다르면 다시 받습니다.)
- 문서 처리 결과는 DB에 즉시 반영하고,
  `99_운영/runs/{YYYY}/{MM}/{DD}/{run_id}/events/{보험사코드}.jsonl`에도 실행 감사
  이벤트를 남깁니다. 이 감사 파일은 DB 복구 정본으로 읽지 않습니다.
- DB 미반영 결과만 영속 로컬 `db_outbox`에 남기며 다음 보험사 실행 시작 전에 재생합니다.
- 문서는 네트워크 출력 시 로컬 TEMP staging의 `.part` 파일에서 검증·SHA-256 계산을 먼저 한 뒤
  파일서버 `99_운영/staging/{run_id}/{보험사코드}`의 `.upload_*` 임시 파일로 복사하고,
  검증이 끝난 파일만
  `01_문서`의 최종 이름으로 같은 공유 볼륨 안에서 원자적으로 이동합니다.
- `--retry-failed` 로 실패 항목만 다시 시도할 수 있습니다.

---

## 10. 테스트

```powershell
# 단위 테스트 (네트워크 불필요)
uv run python -m pytest

# 보험사별 통합 테스트 (실제 사이트 호출)
uv run python -m pytest -m network --run-network
uv run python -m pytest -m network --run-network -k SAMSUNG
```

단위 테스트 범위: 대상 월 계산 / 판매기간 중첩 판정 / 파일명 특수문자 제거 / 문서유형 매핑 /
네트워크 경로 생성 / SHA-256 중복 판정 / HTML 오류 응답 검출 / PDF 헤더 검증 /
기존 파일 덮어쓰기 방지 / 동일 상품의 여러 버전 분리 / DB identity·UPSERT·outbox /
멀티프로세스 보험사 잠금 / 실행 감사 이벤트 / 원자적 저장.

통합 테스트는 보험사별로 상품명·날짜·문서 링크 3종 수집 → 1건 다운로드 → 저장 경로 생성 →
DB 기록 → 파일 열림 → 재실행 시 중복 방지까지 확인합니다.
실제 문서가 없으면 실패로 처리하지 않고 `NO_DOCUMENT_LINK` 가 기록되는지 확인합니다.

pytest 설정은 `pyproject.toml`의 `[tool.pytest.ini_options]`를 사용합니다.

---

## 11. 실행 중 발생 가능한 오류와 대응

| 증상 | 원인 | 대응 |
|---|---|---|
| `[ERROR] 파일 서버에 접근할 수 없습니다.` | SMB/WSL mount 미연결 또는 권한 없음 | Windows는 탐색기에서 UNC 접근을 확인합니다. Docker는 Oracle9에서 `mountpoint /mnt/fileserver`와 `/mnt/fileserver/.../IPR/상품공시실문서`를 확인한 뒤 재실행합니다. **로컬로 대체 저장하지 않습니다.** |
| `ACCESS_DENIED` 가 메리츠화재에 다량 발생 | 웹방화벽이 자동화 트래픽 차단 | 우회하지 말 것. 잠시 후 재시도(`--retry-failed`), 지속되면 해당 사 담당자에게 문의 |
| 메리츠화재 실행 시 브라우저 창이 뜸 | 웹방화벽이 headless 를 차단하여 headful 강제 | 정상 동작입니다. 화면 세션이 있는 환경(콘솔 로그인 상태)에서 실행하세요 |
| 메리츠화재 `Target page… has been closed` | 브라우저 창이 닫힘/크래시 | 재실행. 실행 중 브라우저 창을 닫지 마세요 |
| `playwright._impl…Executable doesn't exist` | 브라우저 미설치 | `playwright install chromium` |
| KB손해보험이 매우 오래 걸림 | 목록에 날짜가 없어 약 4,000개 상품 상세를 모두 조회 (약 2시간 30분) | 정상. 중단해도 체크포인트로 이어받기 가능. 테스트는 `--max-products` 사용 |
| `INVALID_RESPONSE` 다수 | 사이트 점검/일시 오류 | `--retry-failed` 로 재시도 |
| `UNKNOWN_DOCUMENT_TYPE` | 새 문서명 등장 | `config.yaml` 의 `document_types` 에 키워드 추가 |
| DB 연결 오류 후 보험사 중단 | DB 접속 장애 또는 local outbox 재생 실패 | DB 복구 후 같은 보험사를 재실행. outbox 손상 메시지가 있으면 파일을 임의 삭제하지 말고 점검 |
| `MANUAL_REVIEW_REQUIRED` 가 있음 | 기준 날짜가 없고 판매종료 여부도 판단할 수 없는 버전 | DB에서 해당 행을 확인해 수동 판단 |

---

## 12. 실행 결과 예시

`examples/` 폴더에 2026-07 실제 실행 결과가 들어 있습니다.

| 파일 | 내용 |
|---|---|
| `examples/dry_run_output.txt` | 단월 호환 dry-run 콘솔 출력(예시) |
| `examples/crawl_summary_sample.json` | `99_운영/runs/.../summary.json` (layout_version=3) 대표 예시 |
| `examples/README.md` | 실행 검증 요약 |

---

## 13. 프로젝트 구조와 주요 로직 (인수인계용)

### 13.0 현재 범위와 단계별 폴더 계획

현재 프로젝트의 구현 범위는 보험사 공시 문서를 수집하고, 기존 PostgreSQL과
파일 서버에 저장하는 단계입니다. 기존 `crawler/`, `models/`, `utils/`,
`database/`의 import 경로와 저장 구조는 유지합니다.

이번 단계에서는 Docker Desktop의 WSL2 Linux 환경에서 실행할 FastAPI 백엔드에
정기 수집 scheduler를 내장합니다. FastAPI lifespan이 APScheduler cron을
등록하고 `CollectionApplication`을 작업 스레드에서 직접 호출합니다. 수집 실행 중에는 외부 PostgreSQL의
session advisory lock을 유지하며, 기존 보험사별 `CompanyLock`도 그대로
사용합니다. DB schema, job table, 기존 문서 테이블과 데이터 형식은 변경하지
않습니다.

이번 단계에서 구현된 트리:

```
insurance-document-crawler/
├── app/
│   ├── api/
│   │   ├── main.py              # FastAPI lifespan scheduler와 read-only router
│   │   ├── dependencies.py      # config·PathService 의존성
│   │   ├── health.py            # /health/live, /health/ready
│   │   └── routers/
│   │       ├── collectors.py    # GET /api/v1/collectors
│   │       ├── runs.py          # GET /api/v1/runs/latest, /{run_id}
│   │       └── schedule.py      # GET /api/v1/schedule
│   ├── cli.py                   # 애플리케이션 수집 실행 진입점
│   ├── application/             # 수집·보고 유스케이스
│   │   ├── collection.py
│   │   └── reporting.py
│   └── scheduling/
│       └── scheduler.py         # APScheduler에서 CollectionApplication 직접 호출
├── crawler/                     # 기존 수집·검증·저장 로직
├── models/                      # 기존 도메인 모델
├── utils/                       # 기존 공통 유틸리티
├── database/                    # 기존 schema와 적용 스크립트
├── tests/
│   ├── test_api_health.py
│   ├── test_api_readonly.py
│   └── test_scheduler.py
├── docker/
│   ├── Dockerfile
│   └── entrypoints/             # API+Xvfb / 수동 collector+Xvfb
├── config.container.yaml        # config.yaml을 extends하는 Linux 출력 overlay
├── docker-compose.yml           # scheduler 내장 api + manual collector
├── pyproject.toml               # uv 의존성 선언
├── uv.lock                      # uv 해석 결과 잠금
└── .python-version              # 프로젝트 Python 버전
```

개발용 PDF Load는 다음 경계로 구현되어 있습니다.

```
app/
├── application/pdf_load.py      # PDF별 독립 Load 유스케이스
├── domain/pdf_load.py           # 페이지·표·상태 모델
└── infrastructure/
    ├── document_source/         # 현재 로컬 PDF 선택, 추후 DB 선택 확장
    ├── pdf/                     # ProSure 기반 PDF 텍스트·표 처리
    └── artifacts/               # 파일 기반 Load 산출물 저장
```

LLM 추출, 신규 DB 적재, lexical/vector/hybrid 탐색 코드는 아직 구현하지 않았습니다.

FastAPI에 수집 실행 API를 추가하거나 요청의 `BackgroundTasks`로 장시간 수집을
실행하지 않습니다. APScheduler `BackgroundScheduler`가 FastAPI lifespan에서
시작되어 별도 작업 스레드로 수집합니다. 현재 구성은 Uvicorn worker 1개와 API
replica 1개를 전제로 하며, Docker entrypoint도 `--workers 1`로 고정합니다.
실행 중 중복은 PostgreSQL advisory lock으로 한 번 더 차단합니다. 수집 실행 이력을
위한 신규 DB 테이블도 만들지 않으며, 실행 결과는 기존 `99_운영` summary와
기존 DB 흐름을 사용합니다.

운영 API는 조회 전용입니다.

- `GET /health/live`: API 프로세스 상태
- `GET /health/ready`: startup 검증 완료 여부와 scheduler 실행 상태. 시작 이후의 DB·파일 서버 장애는 각 수집 직전 검증에서 처리
- `GET /api/v1/collectors`: 등록 보험사와 Adapter 상태
- `GET /api/v1/runs/latest`, `GET /api/v1/runs/{run_id}`: 기존 summary 조회
- `GET /api/v1/schedule`: scheduler 환경 설정 조회

`POST /crawl`, `POST /jobs`, HTTP Load·검색·RAG API는 구현하지 않습니다.

#### API 로그와 요청 추적

API와 scheduler는 `app.core.settings.get_settings()`가 읽은 공통 설정으로
`app.core.ipr_logger.configure_logging()`을 한 번 구성합니다. 따라서
`uvicorn app.api.main:app`으로 직접 기동해도 애플리케이션 로그 포맷·레벨·파일
출력이 동일하며, uvicorn 기본 핸들러가 중복으로 붙지 않습니다. `IPR_LOG_DIR`은
날짜별 파일 로그(`log_YYYY-MM-DD.log`) 디렉터리이며 로컬 기본값은 프로젝트의
`logs`, Docker Compose 경로는
`/var/log/insurance-document-crawler`입니다. Compose의 `crawler-logs` named
volume에 저장되므로 컨테이너를 교체해도 로그를 보존할 수 있습니다.
로그 레벨은 `LOG_LEVEL`(기본 `INFO`)으로 조정할 수 있습니다.
로그 파일은 자동 삭제하지 않으므로 운영 환경에서 저장 공간을 모니터링해야 합니다.
실행 설정 파일은 `CRAWLER_CONFIG_PATH`(Compose에서는
`/app/config.container.yaml`)로 선택하고, 스케줄·로그 관련 환경 변수는
공통 settings 객체에서 검증·정규화합니다.

`.env`와 운영체제 환경변수는 DB 접속정보, 스케줄, 로그, PDF Load 옵션처럼
서버·배포 환경마다 달라지는 값과 비밀값을 담당합니다. `config.yaml`은 요청 간격,
다운로드 정책, 문서 유형처럼 저장소에서 함께 관리하는 수집 업무 정책의 정본입니다.
같은 설정이 운영체제 환경변수와 `.env`에 모두 있으면 운영체제 값이 우선합니다.

모든 HTTP 요청에는 `X-Request-ID`가 응답으로 돌아옵니다. 요청 헤더에 값이
있으면 앞뒤 공백을 제거하고 영숫자와 `.`, `_`, `:`, `-`만 남겨 최대 128자로
제한합니다. 비어 있거나 허용 문자가 없는 값은 새 UUID(hex)를 발급합니다.
요청 처리 동안 같은 값이 로그 trace context에 설정되며 처리가 끝나거나
예외가 발생하면 반드시 정리됩니다. 장애를 문의할 때 응답의
`X-Request-ID`를 함께 전달하면 해당 요청 로그를 빠르게 찾을 수 있습니다.

관련 환경 변수 예시는 [`.env.example`](.env.example)를 참고하세요.

### 13.1 설계 원칙

**보험사마다 다른 것은 "무엇을 수집했는가"까지고, 그 뒤(검증·명명·중복처리·기록)는 완전히 동일하다.**

그래서 어댑터는 `ProductVersion` 리스트만 만들어 내면 되고,
파일을 어디에 어떤 이름으로 저장할지·중복을 어떻게 처리할지는 **어댑터가 전혀 모릅니다.**
새 보험사를 붙일 때 공통 모듈을 건드릴 일이 없는 이유입니다.

### 13.2 레이어 구조

```
main.py                     app.cli.main()만 호출하는 얇은 실행 진입점
   │
   ▼
app/cli.py                  CLI 인자 해석 · 종료 코드 반환
   │
   ▼
app/application/collection.py  요청 검증 · storage/DB 사전검증 · 전역 실행 잠금
   │
   ▼
crawler/crawler_manager.py  오케스트레이션 (보험사 루프, 기간 필터, 회사 lock, 요약 집계)
   │
   ├── crawler/adapters/*.py ──► 보험사별: "상품 버전 목록 + 문서 링크"만 책임
   │        (crawler/base_adapter.py 의 BaseInsurerAdapter 인터페이스)
   │
   └── crawler/download_service.py   문서 1건 처리 파이프라인 (공통)
            ├── crawler/validators.py       응답 검증 · 문서유형 판별
            ├── crawler/path_service.py     저장 경로 · 파일명 · 중복 회피
            ├── crawler/document_repository.py DB 조회 · 문서별 UPSERT
            ├── crawler/db_outbox.py         DB 장애 결과 보존 · 재생
            ├── crawler/manifest_service.py  호환 DTO · DB 체크포인트 매핑 · 감사 이벤트
            └── crawler/http_client.py      속도제한 · 재시도 · 403 판정

models/    Document · ProductVersion              (데이터 형태)
utils/     date · file · hash · logging          (순수 함수, 단위 테스트 대상)
```

### 13.3 실행 흐름

```
1. app.cli                CLI 인자 해석 → CollectionRequest 생성
2. CollectionApplication config 로드·요청 검증 → PostgreSQL 전역 수집 lock 획득
3.                        파일 서버 실제 write/read/delete probe → 현재 DB v4 계약 검증
                          실패 시 로컬 대체 저장 없이 즉시 종료 (exit 3)
4. crawler_manager.run()  실행별 summary/log 경로 준비
5.   보험사 루프 ───────── 회사 lock 획득 → local DB outbox 재생 → DB 체크포인트 로드
6.                        adapter.open()            (메리츠만 브라우저 기동)
7.                        collect_product_versions(start, end)   ← 어댑터
8.                        select_versions(...)       ← 대상 기간 선정 (공통)
9.     버전 루프 ───────── fetch·최종 URL 확정 → PENDING UPSERT → 검증·저장 → terminal UPSERT + 감사 이벤트
10.                       adapter.close() → DB 연결 종료 → 회사 lock 해제
11. run summary           99_운영/runs/{YYYY}/{MM}/{DD}/{run_id}/summary.json (layout_version=3) 저장
12.                       DB schema 공유 lock과 전역 수집 lock 해제
```

`_run_company()` 가 4~7번을 담당하며, 보험사 하나가 실패해도
`AccessDeniedError` / 일반 예외를 잡아 **그 회사만 `ACCESS_DENIED` 로 기록하고 나머지는 계속** 진행합니다.

### 13.4 어디를 고치면 되나

| 하고 싶은 일 | 고칠 파일 |
|---|---|
| 보험사 추가 / 사이트 구조 변경 대응 | `crawler/adapters/*.py` (+ `adapters/__init__.py` 등록) |
| 대상 월 선정 규칙 변경 | `utils/date_utils.py` 의 `select_versions()` |
| 날짜 우선순위 변경 | `models/product_version.py` 의 `target_date` / `date_basis` |
| 문서유형 키워드 추가 | `config.yaml` 의 `document_types` (코드 수정 불필요) |
| 문서유형 판별 알고리즘 변경 | `crawler/validators.py` 의 `DocumentClassifier` |
| 다운로드 검증 항목 추가 | `crawler/validators.py` 의 `validate_response()` |
| 폴더 구조 / 파일명 규칙 변경 | `crawler/path_service.py` |
| DB 문서 필드 추가 | `database/schema/*.sql` + `crawler/document_repository.py` |
| 요청 속도 / 재시도 정책 | `config.yaml` 의 `crawler` (로직은 `crawler/http_client.py`) |
| 상태값 추가 | `models/document.py` 의 `DownloadStatus` |

### 13.5 주요 로직

#### (1) 날짜 우선순위 — 모델의 계산 속성

요구사항의 우선순위를 데이터에 박아두지 않고 `models/product_version.py` 의 property 로 표현했습니다.

```python
@property
def target_date(self):          # 월 필터에 쓸 날짜
    return self.revision_date or self.sale_start_date or self.disclosure_date

@property
def date_basis(self):           # 어떤 종류를 썼는지 (DB document_date_basis)
    if self.revision_date:   return "revision_date"
    if self.sale_start_date: return "sale_start_date"
    if self.disclosure_date: return "disclosure_date"
    return "NONE"
```

어댑터는 **아는 날짜만 채우면 되고**, 우선순위 판단과 `date_basis` 기록은 자동입니다.
실측상 5개사 모두 개정일/공시일을 따로 주지 않아 전부 `sale_start_date` 로 나옵니다.

#### (2) 대상 월 선정 — 2가지 모드

`utils/date_utils.py` 의 `select_versions()`.

- `new_or_revised` (기본) — `target_date` 가 대상 월 안 → **그 달에 새로 등록/개정된 것만**
- `overlap` — 판매기간이 대상 월과 겹치는 전부 (`시작 ≤ 월말 AND (종료없음 OR 종료 ≥ 월초)`)

기본값을 `new_or_revised` 로 둔 이유는 삼성화재 기준 `overlap` 이면 수천 건이 잡히기 때문입니다.

기준 날짜가 없는 버전 중 판매종료일이 대상 월 이전인 항목은 두 모드 모두 제외합니다.
종료 여부까지 판단할 수 없는 항목만 통과시킨 뒤 다운로드 단계에서
`MANUAL_REVIEW_REQUIRED` 로 기록합니다.

#### (3) 문서유형 판별 — 2중 판정

`crawler/validators.py` 의 `DocumentClassifier`.

1. **제외 키워드 먼저** — 상품설명서·가입설계서 등이면 `None` 을 돌려 아예 문서로 만들지 않음
2. **긴 키워드 우선 매칭** — 규칙을 길이 내림차순 정렬해 `상품요약서` 가 `약관` 보다 먼저 걸리게 함
3. 표시명 → 실패하면 원본 파일명으로 재시도
4. 그래도 실패하면 **버리지 않고** `UNKNOWN_DOCUMENT_TYPE`

어댑터에서는 `self.make_document(label=..., url=..., filename=...)` 한 줄만 부르면 위 판정이 전부 적용됩니다.

#### (4) 다운로드 파이프라인 — 상태 결정 트리

`crawler/download_service.py` 의 `process_document()` 가 문서 1건을 순서대로 판단합니다.

```
링크 없음                          → NO_DOCUMENT_LINK
체크포인트에 성공 + 파일·해시 일치  → DUPLICATE_SKIPPED   (네트워크 호출 안 함)
문서유형 불명                      → UNKNOWN_DOCUMENT_TYPE (다운로드 안 함)
--dry-run                          → DRY_RUN (예상 경로만 계산)
                                   ↓
                adapter.fetch_document()   ← 여기만 보험사별로 다름
                                   ↓
     validate_response()  상태코드 / 0바이트 / HTML / 확장자 / 시그니처
                                   ↓
     sha256 계산 → 같은 이름 파일 존재?
          해시 같음 → DUPLICATE_SKIPPED (덮어쓰지 않음)
          내용 다름 → _2, _3 로 별도 저장 (기존 파일 보존)
                                   ↓
     저장 후 validate_saved_file()  다시 열어 크기·헤더 재확인 → SUCCESS
```

검증 원칙은 **"확장자가 .pdf 라고 표시돼도 믿지 않는다"** 입니다.
HTML 응답이면 `INVALID_RESPONSE`, 본문에 `firewall` 이 있으면 `ACCESS_DENIED` 로 분리합니다.

#### (5) 경로 / 파일명 — 사람이 찾는 문서와 운영 상태 분리

`crawler/path_service.py` 의 `resolve_target_path()`.
모든 문서는 `상품공시실문서/01_문서/{보험사}/{YYYY}/{MM}/{판매상태}__{YYYYMMDD}_{상품명}`
폴더에 저장합니다. 기준일이 없으면 `날짜미상/{판매상태}__날짜미상_{상품명}`을 사용합니다.
경로 구성요소는 경계 공백을 제거하고 내부 공백 run을 `_` 규칙으로 정규화합니다.
파일명은 문서유형(`약관`, `상품요약서`, `사업방법서`)과 실제 확장자만 사용합니다.
상품ID·버전ID·해시는 경로와 파일명에 넣지 않으며 내부 식별자와 원본 상품명·파일명은
PostgreSQL 문서 행에 남습니다. 같은 유형이 충돌하면 `_2`, `_3`을 붙입니다.

파일서버 검증(`verify_base_path()`)은 존재 여부만 보지 않고
**실제 테스트 파일을 쓰고 읽고 지워봅니다.** 실패하면 로컬 대체 저장 없이 종료합니다.

#### (6) 체크포인트 — PostgreSQL과 범위별 상태 저장소

PostgreSQL `rs_disclosure_documents`가 문서 최신 상태의 정본이며, 실행 범위별
`99_운영/state/{범위}/{보험사코드}/download_state.v3.jsonl`가 장기 plan 진행 상태를
보조합니다. 실행별 `events/*.jsonl`은 감사 기록이고, DB 장애 시 미반영 결과 복구는
출력 루트별 로컬 `db_outbox`만 담당합니다.

```python
key = 회사코드|상품ID|상품명|기준일자|문서유형|문서URL
```

중요한 점은 **DB 상태만 믿지 않는다**는 것입니다.
`_previous_file_ok()` 가 실제 파일 존재 + SHA-256 일치까지 확인하고,
파일이 지워졌거나 해시가 다르면 다시 받습니다.
문서 발견과 최종 결과는 짧은 transaction으로 즉시 UPSERT하고, 오래된 실행의 결과가
최신 시각을 역전하지 못하도록 `last_seen_at`·`last_attempt_at` 조건을 사용합니다.
같은 보험사의 writer는 회사 lock으로 하나만 허용됩니다.

#### (7) 속도 제한 — 도메인 단위

`crawler/http_client.py` 의 `RateLimiter.wait()` 가 도메인별 세마포어 + 마지막 요청 시각을 들고 있어
`요청간격 2초 / 도메인당 동시 1` 을 보장합니다.
`request()` 는 408·429·5xx 만 `[3, 10, 30]` 초 백오프로 재시도하고,
**403 은 재시도하지 않고 `AccessDeniedError` 로 즉시 올려보냅니다**(우회 금지).

### 13.6 어댑터가 흡수하는 5개사 차이

| 보험사 | 어댑터가 하는 일 | 재정의한 메서드 |
|---|---|---|
| 삼성화재 | `header=<json>` form POST 1회 → `responseMessage.body.data.list` 파싱 | `collect_product_versions` |
| DB손해보험 | JSON POST 기간검색(415 회피) + 버전별 Step4 로 종료일 보강 | `collect_product_versions` |
| 롯데손해보험 | EUC-KR 수동 인코딩 POST → 응답 JS 의 `innerHTML="..."` 추출 후 표 파싱 | `collect_product_versions` |
| KB손해보험 | 목록 페이지네이션(행 오프셋) + 상품별 상세 POST, `javascript:` 자리표시자 제외 | `collect_product_versions` |
| 메리츠화재 | 헤드풀 브라우저 유지, 페이지 안에서 `bc` / `fileUtil` 직접 호출 | `collect_product_versions` **+ `fetch_document`** |

메리츠화재만 `fetch_document()` 를 재정의합니다.
다운로드 토큰이 세션 종속이라 **목록 수집과 다운로드가 같은 브라우저 세션 안에서** 끝나야 하고,
그래서 `open()` / `close()` 로 브라우저를 보험사 단위 1회만 기동합니다.

나머지 4곳은 `base_adapter.py` 의 기본 `fetch_document()`
(URL GET + Content-Disposition 파일명 추출)를 그대로 씁니다.

### 13.7 이어서 개발할 때 알아둘 것

**사이트별 함정** (전부 실제로 밟아본 것들입니다. 자세한 근거는 [SITE_ANALYSIS.md](SITE_ANALYSIS.md))

| 사이트 | 함정 | 대응 위치 |
|---|---|---|
| DB손해보험 | form 전송하면 **HTTP 415**. `Content-Type: application/json` 필수 | `db_insurance.py` `_post_json()` |
| DB·KB | 다운로드 URL 경로 확장자가 `.do` / `.ec`. 실제 확장자는 쿼리스트링에 있음 | `utils/file_utils.py` `filename_from_url()`, `guess_extension()` |
| 롯데손해보험 | 검색어를 **UTF-8 로 보내면 한글 결과가 항상 0건**. EUC-KR 인코딩 필수 | `lotte_insurance.py` `_search()` |
| 롯데손해보험 | 응답이 JSON 이 아니라 `innerHTML="..."` 를 주입하는 JS | `lotte_insurance.py` `_extract_view()` |
| 삼성화재 | 응답 봉투가 `responseMessage.body` 아래. 파일 없으면 **키 자체가 없음** | `samsung_insurance.py` `_fetch_list()`, `.get()` 접근 |
| KB손해보험 | 문서 없는 칸에도 `<a href="javascript:stop();">` 자리표시자가 있음 | `kb_insurance.py` 에서 `javascript` 시작 href 제외 |
| 메리츠화재 | **headless 차단 + `/hp/fileDownload.do` 외부 호출 차단**(웹방화벽) | `meritz_insurance.py` (headful 강제) |
| 메리츠화재 | `#[E]` 토큰이 세션마다 바뀜 → 목록·다운로드를 같은 세션에서 끝내야 함 | `meritz_insurance.py` `open()` / `fetch_document()` |

**개발 환경**

```powershell
uv sync --locked
uv run playwright install chromium  # 메리츠화재용
uv run python -m pytest              # 네트워크 없는 단위·동시성 테스트
```

**디버깅 팁**

- 사이트 구조가 바뀐 것 같으면 먼저 `--dry-run --company XXX --verbose` 로 확인하세요.
  파일을 받지 않으므로 안전하고, 링크 수집까지의 문제인지 다운로드 문제인지 바로 갈립니다.
- 실패 원인은 `99_운영/runs/{YYYY}/{MM}/{DD}/{run_id}/errors.jsonl` 에 한 줄 JSON 으로 쌓입니다. URL·상태·에러 메시지가 다 들어 있습니다.
- 특정 보험사만 빠르게 돌리려면 `--max-products` / `--max-versions` 를 쓰세요.
  제한을 걸면 콘솔·로그·`summary.json` (layout_version=3)에 `coverage_capped` 로 남습니다.
- 어댑터를 새로 만들 때는 사이트 응답을 파일로 저장해 두고 파서만 반복 실행하는 편이 빠릅니다
  (사이트에 부하를 주지 않습니다).

**지켜야 할 규칙** (코드 리뷰 기준)

- 실제로 확인하지 않은 API 주소·HTML 선택자를 **추정해서 넣지 않습니다.** 확인 결과는 `SITE_ANALYSIS.md` 에 기록합니다.
- 사이트 화면이 실제로 사용하는 공개 요청만 사용합니다. CAPTCHA·접근통제·인증 우회는 구현하지 않습니다.
- 기존 파일을 **삭제하거나 덮어쓰지 않습니다.** 문서 폴더와 유형이 겹치면 `_2`, `_3` 로 보관합니다.
- 수집 범위를 줄이는 처리(상한·샘플링·재시도 생략)를 하면 **반드시 로그와 결과 파일에 남깁니다.**
- 다운로드 성공 여부만 보지 말고 **실제 문서 파일인지 검증**합니다.

---

## 14. 나머지 7개 보험사 추가 방법

1. **사이트 구조 분석** — 개발자도구 Network 탭에서 상품목록/문서 요청을 확인하고
   `SITE_ANALYSIS.md` 에 실측 내용을 추가합니다. **추정한 엔드포인트나 선택자를 넣지 마세요.**

2. **Adapter 작성** — `crawler/adapters/{회사}_insurance.py`

   ```python
   from crawler.base_adapter import BaseInsurerAdapter
   from models.product_version import ProductVersion

   class XxxInsuranceAdapter(BaseInsurerAdapter):
       code = "XXX"
       collection_method = "1순위 - 공시실 화면 JSON API 재현"

       def collect_product_versions(self, start_date, end_date):
           # self.client (속도제한·재시도 내장) 로 사이트 요청
           # 문서는 self.make_document(label=..., url=..., filename=...) 로 생성
           #   -> 문서유형 판별과 제외 대상 필터링이 자동 적용됨
           return [ProductVersion(...), ...]
   ```

   - 문서 링크가 목록과 함께 오면 `collect_documents()` 는 구현하지 않아도 됩니다.
   - URL 다운로드가 아니면(세션 토큰·버튼 클릭 등) `fetch_document()` 만 재정의합니다.
     (메리츠화재 어댑터 참고)
   - 브라우저가 필요하면 `open()` / `close()` 에서 기동·정리하여 **보험사 단위로 1회만** 실행합니다.

3. **등록** — `crawler/adapters/__init__.py` 의 `ADAPTER_REGISTRY` 에 코드 추가

   ```python
   ADAPTER_REGISTRY = { ..., "XXX": XxxInsuranceAdapter }
   ```

4. **보험사 기준정보 추가** — `crawler/company_catalog.py`의 `COMPANIES`에 항목 추가

   ```python
   _company(
       "XXX",
       "XX손해보험",
       InsuranceType.NON_LIFE,
       "https://.../상품공시실",
       options={},  # 필요 시 request_interval_seconds, max_products 등
   )
   ```

5. **검증**

   ```powershell
   uv run main.py --start-date 2026-07-01 --end-date 2026-07-31 --company XXX --dry-run
   uv run python -m pytest -m network --run-network -k XXX
   ```

   `--target-month 2026-07`도 호환되지만, 신규 Adapter 검증과 장기 수집에는
   `--start-date`·`--end-date`를 사용합니다.

공통 모듈(경로·파일명·검증·중복처리·DB 체크포인트·속도제한)은 수정할 필요가 없습니다.
