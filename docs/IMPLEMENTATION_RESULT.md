# IMPLEMENTATION_RESULT.md — 30개사 확장 구현 결과

> **Historical Snapshot — 2026-08-06**
> 이 문서는 해당 날짜의 구현·검증 결과를 보존한 역사 기록입니다. 현재 운영 상태와
> 실행 방법의 정본은 `README.md` 및 `docs/ENDPOINT_MATRIX.md`를 확인하세요.
> 본문에 등장하는 `scratchpad/*`는 저장소 외부의 당시 조사 증적이며 현재 실행할 수 없습니다.

> ⚠️ 역사적 기록 안내: 이 문서는 **과거 layout v1/당시 검증 기록**입니다. 현재 경로와
> 실행 명령은 `README.md`를 참조하세요.

> 작업일: **2026-07-31** (2026-08-04 미구현 14개사 재조사로 8개사 추가 구현 — `docs/UNIMPLEMENTED_COMPANY_ANALYSIS.md`)
> **최종 갱신: 2026-08-06** — AIG·라이나생명 구현 추가, 다운로드 증거 파일 확보,
> 삼성생명 결함 발견, robots.txt 전수 점검 (§16.6 ~ §16.9)
> 대상 월: `2026-07`
> 관련 문서: `docs/BASELINE_RESULT.md`, `docs/ENDPOINT_MATRIX.md`, `docs/SITE_ANALYSIS_30.md`,
> `docs/REGRESSION_TEST_RESULT.md`, `docs/sites/*.md`

---

## 16.1 구현 요약

| 항목 | 건수 |
|---|---:|
| 전체 대상 보험사 | **30** |
| 기존 정상 동작 (EXISTING_WORKING) | **5** |
| 신규 구현 대상 | **25** |
| 신규 구현 완료 (IMPLEMENTED) | **23** (HTTP 22 + HYBRID 1) |
| 부분 구현 (PARTIAL) | **0** |
| 접근 제한 (ACCESS_RESTRICTED) | **2** (FUBON_HYUNDAI_LIFE, HANWHA_FIRE) |
| 문서 미제공 (DOCUMENT_NOT_PROVIDED) | **0** |
| 수동 확인 필요 (MANUAL_REVIEW_REQUIRED) | **0** |

- `config.yaml` 에는 **30개사 전부** 등록되어 있습니다.
- Adapter 가 등록되지 않은 2개사는 실행 시 `Adapter 가 없는 보험사 코드입니다: {코드}` 경고 후 건너뛰며,
  전체 실행은 중단되지 않습니다.
- **추정으로 구현한 Adapter 는 없습니다.** 상품 목록·문서 링크 엔드포인트를 실제 요청으로
  확인하지 못한 사이트는 구현하지 않고 근거를 `docs/sites/{코드}.md` §9 에 남겼습니다.

### 2026-08-06 변경 사항

| 보험사 | 이전 | 현재 | 사유 |
|---|---|---|---|
| **AIG** | `DOCUMENT_NOT_PROVIDED` | **`IMPLEMENTED_HTTP`** | 상품 목록 화면(`/wo/dpwot001.html?menuId=MS702`)이 실제로 존재. 이전 "화면 없음" 결론은 **오판** (`docs/sites/AIG.md` §12) |
| **FUBON_HYUNDAI_LIFE** | `ACCESS_RESTRICTED` (화면 없음) | `ACCESS_RESTRICTED` (**사유 정정**) | 화면·API 모두 존재 확인. 남은 사유는 robots.txt 전면 차단뿐 |
| **LINA_LIFE** | `PARTIAL` | **`IMPLEMENTED_HTTP`** | 상세 API(`product-list-detail`)와 파일 경로 확정. 문서 3종 수집 가능 (`docs/sites/LINA_LIFE.md` §12) |
| **SAMSUNG_LIFE** | `IMPLEMENTED_HYBRID` | `IMPLEMENTED_HYBRID` (**결함 확인**) | 구형 상품 다운로드 404 — §16.7 |

---

## 16.2 보험사별 결과

| 코드 | 보험사 | Adapter | Dry-run | 실제 다운로드 | 문서 3종 확인 | 최종 상태 | 비고 |
|---|---|---|---|---|---|---|---|
| DB | DB손해보험 | `db_insurance.py` (기존) | ✅ 6버전/18링크 | ✅ | ✅ | EXISTING_WORKING | 코드 미변경 |
| LOTTE | 롯데손해보험 | `lotte_insurance.py` (기존) | ✅ 49버전/145링크 | ✅ | ✅ | EXISTING_WORKING | 코드 미변경 |
| MERITZ | 메리츠화재 | `meritz_insurance.py` (기존) | ✅ 183버전/495링크 | ✅ | ✅ | EXISTING_WORKING | 코드 미변경, 헤드풀 Playwright |
| KB | KB손해보험 | `kb_insurance.py` (기존) | ✅ (전량 약 2시간 30분) | ✅ | ✅ | EXISTING_WORKING | 코드 미변경 |
| SAMSUNG | 삼성화재 | `samsung_insurance.py` (기존) | ✅ 137버전/387링크 | ✅ | ✅ | EXISTING_WORKING | 코드 미변경 |
| KYOBO_LIFE | 교보생명 | `kyobo_life.py` | ✅ 표본(상품 25건 → 74버전/112링크) | ✅ 2건 | 약관·방법서 ✅ / 요약서 표본 내 없음 | IMPLEMENTED | 전량은 약 40분 소요 |
| MIRAE_LIFE | 미래에셋생명 | `mirae_life.py` | ✅ 5,539버전 → 대상 294 | ✅ 3건 | ✅ | IMPLEMENTED | `Accept` 헤더 필수 |
| DB_LIFE | DB생명 | `db_life.py` | ✅ 62버전 → 대상 26 | ✅ 3건 | ✅ | IMPLEMENTED | legacy TLS, 약관 1,463개(특약 포함) |
| ABL_LIFE | ABL생명 | `abl_life.py` | ✅ 표본 28버전/62문서 | ✅ 3건 | ✅ | IMPLEMENTED | config URL→resolved 교체 |
| IBK_LIFE | IBK연금보험 | `ibk_life.py` | ✅ 571버전 → 대상 **0** | ✅ 3건 | ✅ | IMPLEMENTED | 2026-07 판매개시 상품이 실제로 0건 |
| IM_LIFE | iM라이프 | `im_life.py` | ✅ 1,595버전 → 대상 9 | ✅ 3건 | ✅ | IMPLEMENTED | |
| KB_LIFE | KB라이프생명 | `kb_life.py` | ✅ 1,247버전 → 대상 110 | ✅ 3건 | ✅ | IMPLEMENTED | |
| KDB_LIFE | KDB생명 | `kdb_life.py` | ✅ 170버전 → 대상 50 | ✅ 3건 | ✅ | IMPLEMENTED | 판매중지 상세 미확정(§10) |
| NH_LIFE | NH농협생명 | `nh_life.py` | ✅ 표본 7버전/17문서 | ✅ 3건 | ✅ | IMPLEMENTED | |
| TONGYANG_LIFE | 동양생명 | `tongyang_life.py` | ✅ 609버전 → 대상 22 | ✅ 3건 | ✅ | IMPLEMENTED | |
| LINA_LIFE | 라이나생명 | `lina_life.py` | ✅ 3,455버전 → 대상 1 | ✅ 2건 | 약관·방법서 ✅ / 요약서는 종속특약이라 사이트가 미제공 | **IMPLEMENTED_HTTP** | 목록 + 상세 지연 조회 |
| METLIFE | 메트라이프생명 | `metlife.py` | ✅ 690버전 → 대상 39 | ✅ 3건 | ✅ | IMPLEMENTED | 특약 약관 포함 312링크 |
| SAMSUNG_LIFE | 삼성생명 | `samsung_life.py` | ✅ 표본 3페이지 30버전 | ⚠️ 신규 상품만 | 약관·방법서 ⚠️ | IMPLEMENTED_HYBRID | Playwright 목록 + HTTP 다운로드. **구형 상품 404 — §16.7** |
| SHINHAN_LIFE | 신한라이프 | `shinhan_life.py` | ✅ 1,646버전 → 대상 90 | ✅ 3건 | ✅ | IMPLEMENTED | proworks 헤더 필수 |
| FUBON_HYUNDAI_LIFE | 푸본현대생명 | 미구현 | ❌ | ❌ | ❌ | ACCESS_RESTRICTED | robots.txt 전면 차단. **화면·API 는 존재**(§16.8) — 운영 정책 판단 대기 |
| HANA_LIFE | 하나생명 | `hana_life.py` | ✅ 40버전(판매중) → 대상 11 | ✅ 3건 | ✅ | IMPLEMENTED | |
| HANWHA_LIFE | 한화생명 | `hanwha_life.py` | ✅ 표본 4버전/16문서 | ✅ 3건 | ✅ | IMPLEMENTED | legacy TLS, 파일 전용 도메인 |
| HEUNGKUK_LIFE | 흥국생명 | `heungkuk_life.py` | ✅ 표본 18버전/52문서 | ✅ 3건 | ✅ | IMPLEMENTED | |
| LINA_NON_LIFE | 라이나손해보험 | `lina_non_life.py` | ✅ 3,379버전 → 대상 59 | ✅ 3건 | ✅ | IMPLEMENTED | 별도 도메인 |
| HANA_NON_LIFE | 하나손해보험 | `hana_non_life.py` | ✅ 3,078버전 → 대상 60 | ✅ 3건 | ✅ | IMPLEMENTED | STEP4 지연 조회로 32분 |
| HYUNDAI_MARINE | 현대해상 | `hyundai_marine.py` | ✅ 6,873버전 → 대상 69 | ✅ 3건 | ✅ | IMPLEMENTED | |
| HEUNGKUK_FIRE | 흥국화재 | `heungkuk_fire.py` | ✅ 2,348버전 | ✅ 3건 | ✅ | IMPLEMENTED | |
| AIG | AIG손해보험 | `aig.py` | ✅ 2,026버전 → 대상 42 | ✅ 3건 | ✅ | **IMPLEMENTED_HTTP** | legacy TLS, `bomservice.do` 평문 JSON. robots.txt 없음 |
| NH_FIRE | NH농협손해보험 | `nh_fire.py` | ✅ 표본 33버전/99문서 | ✅ 3건 | ✅ | IMPLEMENTED | |
| HANWHA_FIRE | 한화손해보험 | 미구현 | ❌ | ❌ | ❌ | ACCESS_RESTRICTED | robots 미허용 + 요청 암호화 |

---

## 16.3 변경 파일

| 파일 | 신규·수정 | 변경 내용 | 기존 5개사 영향 |
|---|---|---|---|
| `crawler/adapters/common.py` | **신규** | 신규 Adapter 전용 공통 유틸(HTML 표 파싱, 판매기간 파서, JS 인자 파서, 인코딩 디코드, JSON POST, 절대 URL) | **없음** — 기존 5개 Adapter 는 import 하지 않음 |
| `crawler/adapters/kyobo_life.py` | 신규 | 교보생명 Adapter | 없음 |
| `crawler/adapters/mirae_life.py` | 신규 | 미래에셋생명 Adapter | 없음 |
| `crawler/adapters/db_life.py` | 신규 | DB생명 Adapter | 없음 |
| `crawler/adapters/ibk_life.py` | 신규 | IBK연금보험 Adapter | 없음 |
| `crawler/adapters/im_life.py` | 신규 | iM라이프 Adapter | 없음 |
| `crawler/adapters/kb_life.py` | 신규 | KB라이프생명 Adapter | 없음 |
| `crawler/adapters/metlife.py` | 신규 | 메트라이프생명 Adapter | 없음 |
| `crawler/adapters/hana_life.py` | 신규 | 하나생명 Adapter | 없음 |
| `crawler/adapters/hana_non_life.py` | 신규 | 하나손해보험 Adapter | 없음 |
| `crawler/adapters/hyundai_marine.py` | 신규 | 현대해상 Adapter | 없음 |
| `crawler/adapters/heungkuk_fire.py` | 신규 | 흥국화재 Adapter | 없음 |
| `crawler/adapters/abl_life.py` | 신규(2026-08-04) | ABL생명 Adapter | 없음 |
| `crawler/adapters/kdb_life.py` | 신규(2026-08-04) | KDB생명 Adapter | 없음 |
| `crawler/adapters/nh_life.py` | 신규(2026-08-04) | NH농협생명 Adapter | 없음 |
| `crawler/adapters/tongyang_life.py` | 신규(2026-08-04) | 동양생명 Adapter | 없음 |
| `crawler/adapters/shinhan_life.py` | 신규(2026-08-04) | 신한라이프 Adapter | 없음 |
| `crawler/adapters/heungkuk_life.py` | 신규(2026-08-04) | 흥국생명 Adapter | 없음 |
| `crawler/adapters/lina_non_life.py` | 신규(2026-08-04) | 라이나손해보험 Adapter | 없음 |
| `crawler/adapters/nh_fire.py` | 신규(2026-08-04) | NH농협손해보험 Adapter | 없음 |
| `crawler/adapters/lina_life.py` | 신규(2026-08-04) → **개편(2026-08-06)** | 라이나생명 Adapter. 목록을 `get-` 계열로 교체하고 상세 지연 조회·문서 다운로드 추가 | 없음 |
| `crawler/adapters/samsung_life.py` | 신규(2026-08-04) | 삼성생명 Adapter(HYBRID) | 없음 |
| `crawler/adapters/hanwha_life.py` | 신규(2026-08-04) | 한화생명 Adapter | 없음 |
| `crawler/adapters/aig.py` | **신규(2026-08-06)** | AIG손해보험 Adapter | 없음 |
| `crawler/adapters/__init__.py` | 수정 | 신규 Adapter **23종** 레지스트리 등록 | **없음** — 기존 5개 매핑 유지 |
| `crawler/http_client.py` | 수정 | `legacy_ssl` 키워드(기본 `False`) + `legacy_ssl_context()` 추가 | **없음** — 기본값에서 종전과 동일(`verify=False`) |
| `crawler/base_adapter.py` | 수정 | `_build_client()` 에 `legacy_ssl` 전달, `_legacy_ssl()` 추가 | **없음** — 기존 5개사는 미지정이라 `False` |
| `crawler/config.py` | 수정 | `CompanyConfig.insurance_type`, `resolved_disclosure_url` 추가(기본값 `""`) | **없음** — 기본값 존재 |
| `config.yaml` | 수정 | 30개사 등록, 기존 5개사에 `insurance_type` 추가, ABL/동양/신한/라이나손보/**AIG** `resolved_disclosure_url` 추가 | **없음** — 기존 5개사의 code/name/url/options 그대로 |
| `tests/test_adapter_common.py` | 신규 | 공통 유틸 테스트 | 없음 |
| `docs/**` | 신규 | 분석·결과 문서 | 없음 |

**기존 5개 Adapter 파일(`db_insurance.py`, `lotte_insurance.py`, `meritz_insurance.py`,
`kb_insurance.py`, `samsung_insurance.py`)은 한 줄도 수정하지 않았습니다.**
공통 다운로드/저장/manifest/중복판정/재시도/체크포인트 로직도 재작성하지 않고 그대로 재사용했습니다.

---

## 16.4 공통 모듈 변경

### 변경한 공통 모듈

1. **`crawler/http_client.py`**
   - 추가: `legacy_ssl_context()`, `HttpClient(..., legacy_ssl: bool = False)`
   - **이유**: DB생명·한화생명·AIG손해보험은 구형 TLS 스택이라 기본 SSL 컨텍스트로 **연결 자체가 실패**합니다.
     - DB생명: `[SSL: WRONG_SIGNATURE_TYPE] wrong signature type`
     - 한화생명: `[SSL: UNSAFE_LEGACY_RENEGOTIATION_DISABLED] unsafe legacy renegotiation disabled`
     - AIG: `TLS/SSL connection has been closed (EOF)`
   - 이 옵션은 **연결 호환성만** 낮춥니다. 인증·접근통제·WAF·CAPTCHA 를 우회하지 않습니다.

2. **`crawler/base_adapter.py`**
   - 추가: `_legacy_ssl()` — 클래스 속성 `legacy_ssl` 또는 `config.companies[].options.legacy_ssl` 로 제어
   - **이유**: 위 옵션을 보험사 단위로 켜기 위함

3. **`crawler/config.py`**
   - 추가: `CompanyConfig.insurance_type`, `CompanyConfig.resolved_disclosure_url`
   - **이유**: 요구사항 §4 의 생명/손보 구분과 §4.1 의 "초기 URL vs 실제 공시 URL" 분리 기록

4. **`crawler/adapters/__init__.py`**
   - 신규 Adapter 등록만 추가

### 하위 호환성 확인 결과

| 확인 항목 | 결과 |
|---|---|
| 신규 인자 기본값 | `legacy_ssl=False`, `insurance_type=""`, `resolved_disclosure_url=""` — 기존 호출부 전부 그대로 동작 |
| 기존 `config.yaml` 로드 | 신규 키가 없어도 `load_config()` 정상 동작(`.get()` 기본값 사용) |
| manifest 컬럼 | **변경 없음**(28개 그대로) |
| 파일 저장 구조 | **변경 없음** |
| 기존 Adapter 인터페이스 | `BaseInsurerAdapter` 의 기존 메서드 시그니처 변경 없음. 신규 Adapter 는 `fetch_document()` 를 **재정의**(오버라이드)만 함 |

### 기존 5개사 회귀 테스트 결과

`docs/REGRESSION_TEST_RESULT.md` 참조. 요약:

- `pytest`: **119 passed / 5 skipped / 0 failed** (변경 전과 동일)
- DB / LOTTE / SAMSUNG: 수집 버전 수·문서 링크 수·저장 경로 **완전 일치**
- MERITZ: 수집 버전 183건 동일

---

## 16.5 미해결 문제

> **2026-08-04 재조사 결과**: 아래 (4) 의 12개사 중 **8개사를 해결해 구현 완료**했습니다.
> 남은 6개사의 단계별 원인은 `docs/UNIMPLEMENTED_COMPANY_ANALYSIS.md` 에 정리했습니다.

### (1) SAMSUNG_LIFE (삼성생명) — **구현됨(HYBRID), 다만 구형 상품 다운로드 실패**

- **2026-08-04 해결**: 요청은 암호화되어 있으나 **응답이 평문 JSON** 이고 파일이 인증 없는 정적 경로에
  올라가 있어, Playwright 로 목록을 받고 문서는 HTTP 로 내려받는 HYBRID 로 구현했습니다.
  **암호화 로직은 역산하지 않았습니다.**
- **2026-08-06 발견된 결함**: 파일 URL 을 서버가 주지 않고 `filename`(밀리초 타임스탬프)에서
  날짜 경로를 역산해 조립하는 방식이라, **구형 상품에서 404** 가 납니다. 상세는 §16.7.

### (2) HANWHA_FIRE (한화손해보험) — ACCESS_RESTRICTED

- **문제 1 (정책)**: robots.txt 가 `Disallow: /` 이고 개별 `Allow` 364건 중
  **상품공시실 경로(`/notice/ir/product-main.do`)가 없습니다.**
  다른 경로(`/intro/ir/...`, `/product/catalog/product-info.do`)는 허용되어 있어 누락이 아닌
  의도적 제외로 보입니다.
- **문제 2 (기술)**: 공통 XHR 본문이 `Dowz0Lw=…` 로 암호화되어 있고 상품 표가 초기 HTML 에 없습니다.
- **재현 방법**: `python scratchpad/net.py HANWHA_FIRE "https://www.hwgeneralins.com/notice/ir/product-main.do?mtoh=Y"`
- **확인한 응답**: HTML 286KB(표 0개), `POST /popup/global_popup_list.json` 본문 암호문
- **확인/추정 구분**: 암호문은 직접 관측했으나 **상품 목록 요청 자체는 아직 관측하지 못했습니다.**
  "목록도 반드시 암호화된다" 는 확정 사실이 아니라 추정입니다. 다만 문제 1 만으로도 미구현 사유가 됩니다.
- **필요한 후속 조치**: 수집이 필요하면 한화손해보험과 별도 협의

### (3) HANA_NON_LIFE (하나손해보험) — **해결됨 (PARTIAL → IMPLEMENTED)**

- **초기 문제**: 첫 구현은 `collect_product_versions()` 안에서 **판매기간마다 STEP4 를 호출**했습니다.
  그 결과 24분 동안 22개 세부분류 중 4개(상품 15건)밖에 처리하지 못해 전량 실행을 중단했습니다.
- **원인**: STEP3 응답에 이미 `sSaleStrDt`/`sSaleEndDt` 가 들어 있어 **대상 월 판정에 STEP4 가 필요 없는데도**
  전 버전에 대해 STEP4 를 호출한 설계 문제였습니다(사이트 문제가 아님).
- **조치**: STEP4 를 `collect_documents()` 로 옮겨 `CrawlerManager` 가 **대상 월로 선정한 버전에 대해서만**
  호출하도록 변경했습니다. 요청 수 약 4,000회 → **약 972회**(STEP1 2 + STEP2 22 + STEP3 888 + STEP4 60).
- **검증 결과 (2026-08-04)**
  - 전량 dry-run: **3,078버전 수집 → 2026-07 대상 60버전 / 문서 178건 / 실패 0건 / 1,944.9초(약 32분)**
  - 실제 다운로드 3종: 약관 5,519,191 bytes, 사업방법서 448,296 bytes, 상품요약서 350,311 bytes (모두 `%PDF-`)
  - 테스트 상품: `무배당 하나더퍼스트 3.0.5 간편 건강보험(간편심사형)(2601) 1종(암집중형)` (2026-07-01, nSeqNo 3402)
- **남은 사항**: 상품요약서 2건은 사이트가 `sSummaryFileID` 를 제공하지 않아 링크 없음(수집 누락 아님).

### (4) 목록·문서 경로 미확정 12개사 — **11개사 해결됨**

원래 목록: `ABL_LIFE`, `KDB_LIFE`, `NH_LIFE`, `TONGYANG_LIFE`, `LINA_LIFE`, `SHINHAN_LIFE`,
`FUBON_HYUNDAI_LIFE`, `HANWHA_LIFE`, `HEUNGKUK_LIFE`, `LINA_NON_LIFE`, `AIG`, `NH_FIRE`

| 상태 | 보험사 |
|---|---|
| 구현 완료 | `ABL_LIFE` `KDB_LIFE` `NH_LIFE` `TONGYANG_LIFE` `SHINHAN_LIFE` `HANWHA_LIFE` `HEUNGKUK_LIFE` `LINA_NON_LIFE` `NH_FIRE` (2026-08-04), **`AIG`** **`LINA_LIFE`** (2026-08-06) |
| 미구현 | `FUBON_HYUNDAI_LIFE`, `HANWHA_FIRE` — robots.txt/접근 정책으로 차단(§16.8) |

- **원래 공통 문제**: 초기 화면에 상품 표가 없고, 목록을 만드는 요청이 사용자의 분류 선택/조회 클릭
  이후 발생합니다. 첫 회차의 Playwright 로깅이 페이지 로드 시점까지만 관측한 것이 원인이었습니다.
- **얻은 교훈**: **"초기 로드에 XHR 이 없다"는 "API 가 없다"가 아닙니다.** NH생명·흥국생명·NH손보는
  모두 인라인 스크립트 안에 엔드포인트가 있었습니다.
  마찬가지로 **"메뉴 API 에 없다"는 "화면이 없다"가 아닙니다** — AIG 오판의 원인이었습니다(§16.8).
- **재현 방법**: `python scratchpad/net.py {코드} {URL}` (`scratchpad/net.py` 는 클릭 인자도 받습니다)

### (5) HANA_LIFE 원본 파일명 인코딩

- **문제**: 약관 다운로드(`/anm/product/download.do`)의 `Content-Disposition` 이 EUC-KR 바이트를
  그대로 흘려보내 `R(¹«)ÇÏ³ª·Î …` 처럼 깨져 보입니다.
- **영향 범위**: 저장 파일명은 크롤러가 조립하므로 **저장에는 영향 없음**. manifest 의
  `original_filename` 컬럼만 깨진 문자열이 들어갑니다.
- **조치**: 요약서·방법서는 URL 의 `downFileName` 파라미터로 정상 파일명을 사용하도록 처리했습니다.
  약관은 해당 파라미터가 없어 현재 상태를 유지했습니다(공통 `filename_from_content_disposition()` 을
  고치면 기존 5개사에 영향이 가므로 변경하지 않음).

---

## 16.6 다운로드 증거 검증 (2026-08-06)

### 배경 — 이전 "실제 다운로드 ✅" 의 한계

§16.2 표의 `실제 다운로드 ✅` 는 `fetch_document()` 로 바이트를 **메모리에 받아**
HTTP 200 / 크기 / 매직바이트(`%PDF-`)만 확인하고 **파일을 남기지 않은** 결과였습니다.
따라서 나중에 다시 열어볼 증거물이 없었습니다. 이를 보완하기 위해 파일을 실제로 저장하는
재검증을 수행했습니다.

### 방법

- 스크립트: `scratchpad/evidence_dl.py`
- 대상: Adapter 가 등록된 28개사 (`AIG`, `LINA_LIFE` 포함)
- 표본: **보험사당 상품 2건**, 상품마다 약관·사업방법서·상품요약서
- 선정 기준: 사이트가 목록에 반환하는 **순서대로 앞에서 문서가 있는 상품 2건**
  (대상 월 필터 없음 — 목적이 "다운로드 배관이 동작하는가" 이므로 의도적으로 제외)
- 저장: `{output.base_path}/_verification/2026-08-06/{보험사}/{상품}/{버전}/{문서유형}/파일`
  - 운영 폴더 `insurance_product_documents` 와 **분리**하되 `PathService` 를 그대로 재사용해
    폴더 구조·파일명·경로 축약 규칙은 운영과 동일
- 검증 대장: 같은 폴더의 `verification.csv`
  (`company_code, document_type, document_url, http_status, status, file_size, sha256, magic, original_filename, saved_path, error`)

### 결과

**26개 보험사 폴더 / PDF 175개 저장** — 약관 88 · 사업방법서 45 · 상품요약서 37

| 보험사 | 약관 | 방법서 | 요약서 | 보험사 | 약관 | 방법서 | 요약서 |
|---|---:|---:|---:|---|---:|---:|---:|
| DB손해보험 | 2 | 2 | 2 | 메트라이프생명 | 12 | 2 | 2 |
| 롯데손해보험 | 2 | 2 | 2 | 신한라이프 | 2 | 2 | 2 |
| 메리츠화재 | 2 | 2 | 2 | 하나생명 | 2 | 2 | 2 |
| 미래에셋생명 | 2 | 2 | 2 | 흥국생명 | 2 | 2 | 2 |
| ABL생명 | 2 | 2 | 2 | 라이나손해보험 | 2 | 2 | 2 |
| IBK연금보험 | 2 | 2 | 2 | 하나손해보험 | 2 | 2 | 2 |
| iM라이프 | 2 | 2 | 2 | NH농협손해보험 | 2 | 2 | 2 |
| KB라이프생명 | 2 | 2 | 2 | **AIG손해보험** | 2 | 2 | 1 |
| KDB생명 | 9 | 2 | 2 | 현대해상 | 2 | 2 | 1 |
| NH농협생명 | 2 | 2 | 2 | 흥국화재 | 2 | 2 | 1 |
| 동양생명 | 2 | 2 | 2 | 한화생명 | 2 | 1 | 1 |

3종을 채우지 못한 6개사:

| 보험사 | 결과 | 원인 | 결함 여부 |
|---|---|---|---|
| **삼성생명** | 약관 1 · 방법서 1 · **404 2건** | 조립식 URL 이 구형 상품에서 어긋남 | **결함 — §16.7** |
| KB손해보험 | 버전 0건 | 검증용 `max_products: 8` 캡 때문에 앞 8개 상품에 문서가 없었음 | 검증 방법 한계 |
| 라이나생명 | 문서 링크 0 | 검증 시점에는 문서 요청 미확정(`PARTIAL`)이었음. **2026-08-06 해결 — §16.9** | 해결됨 |
| 삼성화재 | 요약서 0 | 뽑힌 2개 상품에 요약서가 없음 | 표본 특성 |
| DB생명 | 약관 26 · 요약서 0 | 상품 1건에 특약 약관이 다수 딸림 / 요약서 없음 | 표본 특성 |
| 교보생명 | 약관 2 · 방법서 1 · 요약서 0 | 2개 상품 중 1개만 문서 보유 | 표본 특성 |

> **표본 특성** 은 사이트가 해당 상품에 문서를 제공하지 않는 경우로 수집 누락이 아닙니다.
> 다만 선정 기준상 30년 전 상품(롯데 1989-06-29, 교보 1998-04-01)도 표본에 들어가므로
> **운영 실행이 실제로 수집하는 상품과는 다릅니다.** 대상 월 기준 재검증은 별도 과제입니다.

---

## 16.7 SAMSUNG_LIFE 다운로드 결함 (2026-08-06 발견)

### 증상

```
404  https://pcms.samsunglife.com/uploadDir/doc/2017/0124/20470/301/1485248184711.pdf   (약관)
404  https://pcms.samsunglife.com/uploadDir/doc/2017/0124/20470/401/1485248184812.pdf   (사업방법서)
```

### 원인

삼성생명 목록 API 는 파일 URL 을 주지 않고 `filename`(밀리초 타임스탬프)만 줍니다.
`crawler/adapters/samsung_life.py` 는 여기서 날짜 경로를 **역산해 조립**합니다.

```python
stamp = datetime.datetime.fromtimestamp(int(file_name) / 1000)
return f"{FILE_BASE}/{stamp:%Y}/{stamp:%m%d}/{goods_code}/{doc_type}/{file_name}.pdf"
```

2026년 신규 상품에서는 맞지만 **2017년 구형 상품에서는 실제 저장 경로와 어긋납니다.**
§16.2 의 `실제 다운로드 ✅ 2건` 은 신규 상품만 확인한 결과였습니다.

### 영향 범위

- 대상 월(`new_or_revised`) 기준 실행은 신규·개정 상품이 대상이므로 **영향이 제한적**입니다.
- 다만 `overlap` 모드나 구형 상품 재수집 시 실패합니다.

### 필요한 후속 조치

Playwright 로 다운로드를 클릭해 **실제 파일 URL 을 관측**하고 규칙을 다시 확정해야 합니다.
현재 조립 규칙은 관측 표본이 신규 상품에 치우쳐 있었습니다. **추정 규칙을 확대 적용하지 않습니다.**

---

## 16.8 robots.txt 점검 결과 (2026-08-06)

구현된 전 Adapter 의 **실제 호출 URL(목록·다운로드) 53건**을 RFC 9309 규칙
(최장 일치 우선, 동률이면 Allow)으로 대조했습니다. 감사 스크립트: `scratchpad/robots_audit2.py`.

> Python 표준 `urllib.robotparser` 는 **파일에 먼저 나온 규칙**을 적용하므로
> `Disallow: /` 다음에 `Allow: /BA/` 가 오는 형태를 잘못 판정합니다. 별도 구현으로 재검증했습니다.

| 상태 | 개수 | 보험사 |
|---|---:|---|
| robots.txt 없음(제한 없음) | 11 | 메리츠·DB생명·ABL·KDB·동양·라이나생명·메트라이프·신한·하나생명·라이나손보·**AIG** |
| 전체 허용 | 12 | 그 외 대부분 |
| **부분 미허용** | 3 | iM라이프 · 삼성생명 · 한화생명 |
| **전면 차단** | 2 | 푸본현대생명 · 한화손해보험 |

### 부분 미허용 3사 — 목록은 허용, 다운로드만 미허용

| 보험사 | 목록 | 다운로드 | 다운로드 호스트 |
|---|---|---|---|
| iM라이프 | 허용 (`Allow: /BA/`) | **미허용** (`/www/downloadChk.do`) | `www.imlifeins.co.kr` |
| 삼성생명 | 허용 (`www.samsunglife.com`) | **미허용** | `pcms.samsunglife.com` (`Disallow: /`) |
| 한화생명 | 허용 (`www.hanwhalife.com`) | **미허용** | `file.hanwhalife.com` (`Disallow: /`) |

삼성생명·한화생명은 다운로드가 **본 사이트가 아닌 별도 파일 서버**로 가기 때문에
본 도메인만 점검했을 때는 드러나지 않았습니다.

### 전면 차단 2사

```
# 푸본현대생명 — 네이버 검색봇만 허용, 예외 경로 없음
User-agent: Yeti
Disallow:
User-agent: *
Disallow:/
```

**푸본현대생명은 화면·API 가 존재합니다(2026-08-06 확인).**
목록 `POST /cusinfo/publicRoom/findGoodsList.do` → `goodsList[]`
(`regPath` 약관 / `bizPath` 사업방법서 / `goodsPath` 상품요약서, `sttDtm`~`endDtm` 판매기간),
다운로드 `POST /common/docDown.do` (`fType`, `bjTitle`, `docuKbn`). 모두 평문입니다.
**기술적으로는 구현 가능하나 robots.txt 상 거부 의사가 명확해 구현하지 않았습니다.**
(사용자가 지정한 화면의 정적 HTML 만 확인했고 목록·다운로드 요청은 보내지 않았습니다.)

한화손해보험은 §16.5 (2) 참조.

### 판단이 필요한 사항

robots.txt 는 기술적 접근통제가 아니라 **운영자의 의사 표시**이며, 지킬지 여부는 운영 정책 판단입니다.
현재 5개사(iM라이프·삼성생명·한화생명·푸본현대생명·한화손해보험)가 **판단 대기 상태**이며,
어느 것도 임의로 중단하거나 강행하지 않았습니다. 선택지:

1. 현행 유지 — 리스크를 감수
2. 해당 3사는 목록만 수집하고 다운로드는 `ACCESS_RESTRICTED` 로 기록
3. `enabled: false`
4. **각 보험사에 수집 목적·범위를 알리고 허용 확인** (권장 — 공개 의무 자료이고 월 1회 수집)
5. 생명보험협회·손해보험협회 공시 등 대체 경로 검토

---

## 16.9 LINA_LIFE 구현 완료 (2026-08-06) — PARTIAL 해소

### 이전 결론과 실제

§16.5 (4) 와 `docs/sites/LINA_LIFE.md` §11 은 "목록 응답에 파일 정보가 없고 문서 요청을 확정하지 못했다"
로 남아 있었습니다. **문서 요청은 존재하며, 상품을 펼칠 때 호출됩니다.**

**놓친 이유 3가지**

1. 초기 로드 API(`product-list`)에는 파일 필드가 없어 여기서 탐색을 멈췄습니다.
   실제 목록은 검색 버튼을 눌러야 호출되는 **`get-product-list`** 이고 건수도 훨씬 많습니다
   (특약 15건 → **2,264건**).
2. 목록이 `<table>` 이 아니라 `<li class="list">` **아코디언 카드**라 행 탐색에 실패했습니다.
3. 문서는 **상품을 펼친 뒤에만** 표로 나타납니다. 접힌 상태에는 상품명과 화살표뿐입니다(화면 캡처로 확인).

### 확정된 엔드포인트 (2026-08-06 실측)

| 구분 | 판매중 | 판매중지 |
|---|---|---|
| 목록 | `GET .../disclosure/get-product-list` | `GET .../disclosure/get-product-endlist` |
| 상세 | `GET .../disclosure/product-list-detail` | `GET .../disclosure/end-product-detail` |

- 공통 host: `https://api.lina.co.kr/public/contents/v1/`
- 목록 파라미터: `mtrtDcd`(`B` 주보험 / `R` 특약), `KliaProdClcd`(주보험 분류), `KcisInsKcd`(특약 보종)
- 상세 파라미터: `insureCd`, `prodPbanGrpCd` (판매중지는 `insRenwPrcsPsbYn` 추가)
- 인증 없는 평문 JSON. robots.txt 없음.

**문서 다운로드**

```
GET https://www.lina.co.kr/cms/upload/upload/docs/disclosure/{파일명}
```

화면 스크립트(`_nuxt/a41423a464e92deb0f8c.js`)에서 확인했습니다.

```javascript
openFile: function(e) {
    var t = this.currentUrl + "/cms/upload/upload/docs/disclosure/" + e;
    window.open(t, "_blank");
}
```

### 상세 응답 → 수집 항목

```json
{ "sellOpnDt": "20260401", "sellEndDt": "99991231",
  "productSumary":    "B00312011_1_S.pdf",   // 상품요약서
  "productMethod":    "B00312011_0_B.pdf",   // 사업방법서
  "productProvision": "B00312011_1_P.pdf",   // 약관
  "itemSection": "최초계약", "trtTpCd": "01" }
```

**상세는 판매기간별로 여러 행을 돌려줍니다.** 목록은 현재 판매기간 1건만 주므로
판매기간 이력도 상세에서만 얻을 수 있습니다.

### 파일명을 계산할 수 없는 이유

파일명 앞부분은 `inscd` 와 같지만 가운데 번호가 개정 이력마다 달라집니다(실측).

| 판매기간 | 요약서 | 방법서 | 약관 |
|---|---|---|---|
| 2026-04-01 ~ | `_0_S` | `_2_B` | (없음) |
| 2025-09-01 ~ 2026-03-31 | (없음) | `_2_B` | `_3_P` |
| 2025-04-01 ~ 2025-08-31 | (없음) | `_2_B` | `_2_P` |
| 2024-06-01 ~ 2025-03-31 | (없음) | `_1_B` | `_1_P` |

**규칙으로 조립하지 않고 서버가 준 파일명을 그대로 씁니다.**
(조립식 URL 이 구형 상품에서 깨지는 사례가 §16.7 삼성생명입니다.)

### 상세 조회를 `collect_documents()` 에 둔 이유

상품이 3,455건이라 전량 상세 조회 시 요청 간격 2초 기준 약 2시간입니다.
`CrawlerManager` 가 대상 월로 선정한 버전에 대해서만 호출하도록 배치했습니다(하나손해보험과 동일).

- **제약**: 대상 월 판정에 목록의 `sellOpnDt`(현재 판매기간)를 쓰므로,
  **과거 판매기간 버전은 후보에 포함되지 않습니다.** 현재 `new_or_revised` 모드에서는 문제가 없으나
  과거 이력까지 수집하려면 전량 상세 조회가 필요합니다.

### 종속특약의 `-` 표기

`trtTpCd` 가 `02` 면 상품요약서·사업방법서가, `03` 이면 상품요약서가 화면에 `-` 로 표시되고
"함께 가입하신 주보험에서 확인할 수 있습니다" 안내가 붙습니다.
응답이 빈 값이거나 `-` 면 문서를 만들지 않습니다. **수집 누락이 아니라 사이트 정책입니다.**

### `sellEndDt: "99991231"`

무기한 판매중 표기입니다. 그대로 두면 전 상품이 `판매중지` 로 분류되므로 `None` 으로 변환합니다.

### 검증 결과

**Dry-run** (`--company LINA_LIFE --dry-run --target-month 2026-07`, 74.1초)

```
3,455버전 수집 → 대상 1건 / 문서 링크 2건 / MANUAL_REVIEW_REQUIRED 0
대상 상품: 대리청구인지정서비스특약 (2026-07-01 판매개시)
```

대상이 1건인 것은 라이나생명의 2026-07 판매개시 상품이 실제로 1건이기 때문입니다.

**실제 다운로드**

| 문서 | HTTP | 크기 | 매직 | 파일명 |
|---|---|---|---|---|
| 약관 | 200 | 270,338 B | `%PDF-` | `R00804009_0_P.pdf` |
| 사업방법서 | 200 | 5,336,746 B | `%PDF-` | `R00804009_0_B.pdf` |
| 상품요약서 | — | — | — | 종속특약(`trtTpCd=03`)이라 사이트 미제공 |

### 최종 분류

`PARTIAL` → **`IMPLEMENTED_HTTP`**
