# SITE_ANALYSIS_30.md — 30개사 사이트 특징 요약

> **Historical Snapshot — 2026-08-20**
> 이 문서는 2026-08-20까지의 사이트 구조 조사 스냅샷입니다. 현재 운영 상태와
> Adapter 등록 현황의 정본은 `README.md`와 `docs/ENDPOINT_MATRIX.md`입니다.
> 본문에 등장하는 외부 조사 도구·`scratchpad/*` 경로는 당시 증적일 뿐 현재 실행할 수 없습니다.

> 확인일: **2026-07-31 (1~6절 역사 분류 기준일)**
> 개별 사이트 상세는 `docs/sites/{코드}.md`, 엔드포인트 표는 `docs/ENDPOINT_MATRIX.md` 를 참고하세요.
>
> **역사 분류 고지:** 아래 1~6절의 표와 분류는 2026-07-31 당시 조사 결과이며,
> 이후 구현·접근 제한 상태가 반영되지 않을 수 있습니다. 현재 Adapter 등록·구현 상태와
> AIG·LINA_LIFE의 최신 엔드포인트는 2026-08-20 갱신된 §7 및
> `docs/ENDPOINT_MATRIX.md`를 정본으로 사용하세요.

---

## 1. 수집 방식별 분류

| 분류 | 건수 | 보험사 코드 |
|---|---:|---|
| **STATIC_HTML** (정적 HTML 파싱) | 4 | `DB_LIFE`, `IBK_LIFE`, `METLIFE` / (참고) `LINA_NON_LIFE` 는 정적이지만 상품 표 없음 |
| **JSON_API** (화면이 호출하는 JSON/XHR 재현) | 8 | `DB`, `SAMSUNG`, `KYOBO_LIFE`, `MIRAE_LIFE`, `KB_LIFE`, `HANA_NON_LIFE`, `HYUNDAI_MARINE`, (부분) `KDB_LIFE` |
| **FORM_POST** (화면 폼 POST 재현) | 5 | `LOTTE`, `KB`, `IM_LIFE`, `HANA_LIFE`, `HEUNGKUK_FIRE` |
| **JAVASCRIPT_RENDERED** (초기 HTML 에 목록 없음) | 8 | `MERITZ`, `ABL_LIFE`, `SAMSUNG_LIFE`, `SHINHAN_LIFE`, `FUBON_HYUNDAI_LIFE`, `AIG`, `HANWHA_FIRE`, (부분) `KB_LIFE` |
| **SESSION_INITIALIZATION_REQUIRED** | 2 | `MERITZ`(WAF 세션), `HANWHA_LIFE`(jsessionid 리다이렉트) |
| **PLAYWRIGHT_REQUIRED** | 3 | `MERITZ`(구현 완료), `SAMSUNG_LIFE`(미구현), `HANWHA_FIRE`(미구현) |
| **MIXED** (목록 HTML + 문서 팝업/별도 API) | 4 | `DB_LIFE`(HTML+약관 팝업), `METLIFE`(HTML+특약 팝업), `KB`(목록+상세), `HYUNDAI_MARINE`(목록 JSON + 파일경로 JSON) |
| **확인 불가** | 6 | `NH_LIFE`, `TONGYANG_LIFE`, `LINA_LIFE`, `HEUNGKUK_LIFE`, `NH_FIRE`, `LINA_NON_LIFE` |

> 한 보험사가 두 분류에 겹쳐 나타날 수 있습니다(예: `KB_LIFE` 는 화면은 JS 렌더링이지만 수집은 JSON_API).

### 1.1 우선순위 적용 결과 (요구사항 §6)

| 우선순위 | 방식 | 채택한 보험사 |
|---|---|---|
| 1 | 공식 화면이 사용하는 JSON·XHR·Fetch | DB, SAMSUNG, KYOBO_LIFE, MIRAE_LIFE, KB_LIFE, HANA_NON_LIFE, HYUNDAI_MARINE |
| 2 | 정적 HTML 파싱 | DB_LIFE, IBK_LIFE, METLIFE |
| 3 | Form POST 재현 | LOTTE, KB, IM_LIFE, HANA_LIFE, HEUNGKUK_FIRE |
| 4 | Playwright 정상 사용자 흐름 | MERITZ (다른 방법이 웹방화벽에 차단되어 불가피) |

---

## 2. 화면 구조별 분류

| 구조 | 보험사 코드 |
|---|---|
| **목록에서 문서 직접 다운로드** | `DB`, `LOTTE`, `SAMSUNG`, `MIRAE_LIFE`, `IM_LIFE`, `KB_LIFE`, `HANA_LIFE`, `IBK_LIFE`, `HEUNGKUK_FIRE`, `HYUNDAI_MARINE`(파일경로 1회 변환) |
| **상품 상세에서 다운로드** | `KB`(`CG802030002.ec`), `KYOBO_LIFE`(상세 API), `HANA_NON_LIFE`(STEP4) |
| **판매기간 팝업에서 다운로드** | `KYOBO_LIFE`(기간별 다운로드 모달) |
| **이전 판매기간 펼치기** | `METLIFE`(HTML 에 포함), `KB_LIFE`(아코디언), `KYOBO_LIFE`(상세 목록) |
| **카테고리별 별도 페이지** | `MERITZ`(분류 16종), `HEUNGKUK_FIRE`(장기/일반/자동차), `IBK_LIFE`(개인연금/퇴직연금), `HANA_NON_LIFE`(자동차/일반/장기) |
| **판매 중·판매 중지 별도 페이지** | `DB_LIFE`(`sale`/`sold_out`), `IBK_LIFE`(`SP`/`NSP`), `HANA_LIFE`(`status=on/off`), `HANA_NON_LIFE`(`saleProduct`/`saleStopProduct`), `HEUNGKUK_FIRE`(`mode=go/stop`), `IM_LIFE`(`sellType=1/0`), `KB_LIFE`(`tabType=1/2`), `MIRAE_LIFE`(시트 2종) |
| **주계약·특약 별도 관리** | `METLIFE`(특약보기 팝업), `DB_LIFE`(주계약 및 특약 약관 팝업), `IM_LIFE`(독립특약 표) |
| **판매중지 전용 화면 없음** | `METLIFE`(이전 판매기간으로만 제공) |

---

## 3. 공통화 가능한 요소 → `crawler/adapters/common.py`

기존 5개사 Adapter 는 이 모듈을 import 하지 않으므로 변경의 영향을 받지 않습니다.

| 공통 요소 | 함수 | 사용 보험사 |
|---|---|---|
| **상품 목록 파서**(표 행 추출) | `soup()`, `table_rows()`, `clean()` | DB_LIFE, IBK_LIFE, IM_LIFE, METLIFE, HANA_LIFE, HEUNGKUK_FIRE |
| **판매기간 파서** | `parse_period()` — `2026.07.01 ~`, `2026-05-06 ~ 2026-06-30`, `20260701~현재` 모두 처리 | DB_LIFE, IBK_LIFE, KB_LIFE, METLIFE, HANA_LIFE, HEUNGKUK_FIRE |
| **문서 링크 파서 / JavaScript 링크 해석** | `js_call_args()` — `fn_filedownX('/a/','b.pdf','c.pdf')`, `onDownload('X','675','#3')`, `fileDownload('/Download/…')` | IBK_LIFE, IM_LIFE, HEUNGKUK_FIRE |
| **페이지네이션** | 사이트마다 규칙이 달라 공통 함수 대신 각 Adapter 의 `_collect()` 루프로 처리(중복 코드 없음) | DB_LIFE, KB_LIFE, HEUNGKUK_FIRE |
| **파일명 추출** | 기존 `utils/file_utils.filename_from_content_disposition()` 재사용(신규 추가 없음) | 전 신규 Adapter |
| **세션 초기화** | `BaseInsurerAdapter.client` 프로퍼티(기존) + `legacy_ssl` 옵션 | DB_LIFE, HANWHA_LIFE·AIG |
| **문서유형 매핑** | 기존 `crawler/validators.DocumentClassifier` 재사용(config 의 `document_types`) | 전 신규 Adapter |
| **상대 URL → 절대 URL** | `absolute()` | DB_LIFE, METLIFE, HANA_LIFE |
| **EUC-KR / UTF-8 인코딩 처리** | `decode_body()` | IBK_LIFE, KDB_LIFE, HEUNGKUK_LIFE |
| **JSON POST 헬퍼** | `json_post()` | KYOBO_LIFE, HANA_NON_LIFE, HYUNDAI_MARINE |
| **공백 정리** | `clean()` | 전 HTML 파싱 Adapter |

---

## 4. 인코딩 분포

| 인코딩 | 보험사 |
|---|---|
| UTF-8 | DB, MERITZ, SAMSUNG, KYOBO_LIFE, MIRAE_LIFE, DB_LIFE, KB_LIFE, METLIFE, HANA_LIFE, HANA_NON_LIFE, HYUNDAI_MARINE, HEUNGKUK_FIRE, IM_LIFE |
| EUC-KR | LOTTE, KB, IBK_LIFE, KDB_LIFE, HEUNGKUK_LIFE |

---

## 5. 접근 제한 / 특이사항

| 유형 | 보험사 | 내용 |
|---|---|---|
| **웹방화벽(WAF)** | MERITZ | 파일 다운로드 경로 차단. 우회하지 않고 헤드풀 브라우저의 정상 클릭 흐름 사용 |
| **요청 파라미터 암호화** | SAMSUNG_LIFE, HANWHA_FIRE | 목록 요청 본문이 클라이언트에서 암호화(`g`/`b`, `Dowz0Lw`). 역산은 접근통제 우회 소지가 있어 시도하지 않음 |
| **구형 TLS 스택** | DB_LIFE, HANWHA_LIFE, AIG | 기본 SSL 컨텍스트로 연결 실패. `options.legacy_ssl: true` 로 **연결 호환성만** 낮춤(인증·통제 우회 아님) |
| **특정 헤더 필수** | MIRAE_LIFE | `Accept: application/json…` 없으면 HTTP 404 |
| **`Content-Type: application/json` 필수** | DB | 폼 인코딩 시 HTTP 415 |
| **EUC-KR 폼 인코딩 필수** | LOTTE | UTF-8 로 보내면 한글 검색 0건 |
| **키보드보안 스크립트** | NH_LIFE(AhnLab AOS2), HEUNGKUK_LIFE(nProtect) | 조회 자체를 막지는 않으나 화면이 스크립트에 의존 |
| **CAPTCHA** | 없음 | 30개사 어디에서도 관측되지 않음 |

---

## 6. 소요 시간(실측)

| 보험사 | 전량 목록 수집 시간 | 요청 수(개략) |
|---|---:|---|
| SAMSUNG | 1.4초 | 1 |
| LOTTE | 3.4초 | 1 |
| HANA_LIFE | 3.1초 | 2 |
| HYUNDAI_MARINE | 6.1초 | 2 |
| KB_LIFE | 6.7초 | 약 26 |
| IBK_LIFE | 6.3초 | 4 |
| DB | 12초 | 1 + 버전당 1 |
| IM_LIFE | 약 12초 | 2 |
| METLIFE | 1.5초(+선정 버전당 특약 팝업 1회) | 1 + N |
| DB_LIFE | 76~108초 | 약 50 + 약관 팝업 |
| MIRAE_LIFE | 114초 | 약 60 |
| MERITZ | 149초 | 약 40 |
| HEUNGKUK_FIRE | 497초 | 약 240 |
| KYOBO_LIFE | 약 40분(추정, 상품 1,119건) | 약 1,131 |
| HANA_NON_LIFE | 약 2시간(추정) | 약 4,000 |
| KB | 약 2시간 30분 | 약 4,400 |

> 요청 간격은 전 사 공통 `request_interval_seconds: 2`, 도메인당 동시요청 1 입니다.

---

## 7. 2026-08-20 갱신 — 30개사 최종 수집 방식 (현재 정본)

이 절의 분류와 `crawler/company_catalog.py`·`crawler/adapters/__init__.py` 등록 상태가
현재 운영 기준입니다. 1~6절의 2026-07-31 역사 분류와 다를 경우 이 절을 따릅니다.

| 수집 방식 | 건수 | 보험사 |
|---|---:|---|
| **STATIC_HTML** | 5 | DB_LIFE, IBK_LIFE, METLIFE, ABL_LIFE, LINA_NON_LIFE |
| **JSON_API** | 12 | DB, SAMSUNG, KYOBO_LIFE, MIRAE_LIFE, KB_LIFE, KDB_LIFE, LINA_LIFE, SHINHAN_LIFE, HANWHA_LIFE, HANA_NON_LIFE, HYUNDAI_MARINE, AIG |
| **FORM_POST** | 8 | LOTTE, KB, IM_LIFE, NH_LIFE, TONGYANG_LIFE, HANA_LIFE, HEUNGKUK_LIFE, HEUNGKUK_FIRE |
| **XML_AJAX** | 1 | NH_FIRE |
| **PLAYWRIGHT (수집)** | 1 | MERITZ (헤드풀, 웹방화벽) |
| **HYBRID (Playwright 목록 + HTTP 다운로드)** | 1 | SAMSUNG_LIFE (요청 암호화) |
| **ACCESS_RESTRICTED — 외부 제한** | 2 | FUBON_HYUNDAI_LIFE·HANWHA_FIRE(robots.txt/접근 정책, 명시 선택도 사전 거부) |

### robots.txt 점검 결과 (2026-08-04, 30개사 전수)

| 상태 | 보험사 |
|---|---|
| `*` 에이전트 전면 차단(예외 없음) | **FUBON_HYUNDAI_LIFE** |
| `Disallow: /` + 개별 Allow (공시실 경로 미포함) | **HANWHA_FIRE** |
| `Disallow: /` + 개별 Allow (목록 경로 `/BA/` 는 허용, 다운로드 `/www/` 는 미포함) | **IM_LIFE** — 운영 정책 판단 필요 |
| 제한 없음 / robots.txt 없음(404) | 나머지 27개사 |

### 구형 TLS(`options.legacy_ssl: true`) 필요

`DB_LIFE`, `HANWHA_LIFE`, `AIG`
