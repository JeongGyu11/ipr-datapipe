# UNIMPLEMENTED_COMPANY_ANALYSIS.md — 미구현 14개사 원인 정밀 조사

> **Historical Snapshot — 2026-08-04**
> 이 문서는 해당 날짜의 14개사 조사 결과를 보존한 역사 기록입니다. 현재는 30개사 중
> 28개사에 Adapter가 등록되어 있고, `FUBON_HYUNDAI_LIFE`·`HANWHA_FIRE`만
> `ACCESS_RESTRICTED`입니다. 현재 운영 상태와 실행 방법의 정본은 `README.md` 및
> `docs/ENDPOINT_MATRIX.md`를 확인하세요. `scratchpad/*`는 저장소 외부의 당시 조사
> 증적이며 현재 실행할 수 없습니다.

> ⚠️ 역사적 기록 안내: 이 문서는 **과거 layout v1/당시 검증 기록**입니다. 현재 경로와
> 실행 명령은 `README.md`를 참조하세요.

> 조사일: **2026-08-04**
> 조사 대상: 기존 `MANUAL_REVIEW_REQUIRED` 12개사 + `ACCESS_DENIED` 2개사
> 조사 방법: `config.yaml` URL 확인 → 실제 공시실 URL 탐색 → 화면 조작(분류 선택·조회 클릭·문서 클릭) →
> Playwright 네트워크 로깅(`scratchpad/probe2.py`)으로 요청 기록 → `httpx` 로 재현 → 실제 파일 다운로드 확인
>
> **이번 조사에서 14개사 중 8개사의 전 경로(목록 → 상세/판매기간 → 문서 → 실제 다운로드)를 확정하고
> Adapter 를 구현·검증했습니다.** 나머지 6개사는 막힌 지점을 단계 단위로 특정했습니다.

---

## 1. 보험사별 결과 표

| 코드 | 보험사 | 실제 상품공시실 URL | 공시실 접근 | 상품 목록 확인 | 목록 요청 확인 | 상세·판매기간 확인 | 문서 3종 링크 확인 | 실제 다운로드 확인 | 직접 HTTP 구현 가능성 | Playwright 필요 여부 | 현재 실패 단계 | 정확한 원인 | 확인 근거 | 후속 작업 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ABL_LIFE | ABL생명 | `abllife.co.kr/st/pban/prdtPban/whlPrdt/whlPrdt{1\|2}/whlPrdt{1\|2}{1..8}?page=index` | 성공 | 화면 + HTML 파싱 | ✅ GET | ✅ 상세 `/st/pban/prdtPban/whlPrdt?page={id}` 표 | ✅ 약관·사업방법서·상품요약서 | ✅ 약관 13,461,120 B `%PDF-1.6` | **가능(구현 완료)** | 분석용으로만 필요 | 없음(해결) | 기존 config URL 이 상품 목록이 아니라 **공시실 허브 화면**이어서, 실제 목록 화면 8개(판매)·8개(판매중지) 를 찾지 못하고 있었음. 목록은 `<table>` 이 아니라 `ul > li.fss_box` 라 표 기준 탐색으로는 보이지 않았음 | `docs/sites/ABL_LIFE.md` §10, 허브 화면의 '바로가기' 링크, `abl_list.html`/`abl_detail.html` | (완료) 전량 dry-run 및 대상 월 검증 |
| KDB_LIFE | KDB생명 | `kdblife.com/ajax.do?pcmode=1&scrId=HDLMA002M02P`(판매) / `HDLMA002M03P`(판매중지) | 성공 | API 응답에서 확인 | ✅ POST `/ajax.do?scrId=…&isJson=1` | ✅ 응답의 GP='B' 행이 판매기간 | ✅ AGREEMENT/PRODUCT_SUMMARY/PRODUCT_GUIDE | ✅ 약관 2,334,697 B `%PDF-` | **가능(구현 완료)** | 분석용으로만 필요 | 없음(해결) | 이전 조사에서는 목록 API 만 알고 **응답이 JSON 인 것을 놓쳤음**(응답 앞에 공백/개행이 많아 HTML 로 오인). 또 판매중지 화면 `scrId` 와 파일 필드 의미(PRODUCT_SUMMARY=사업방법서, PRODUCT_GUIDE=상품요약서)가 확인되지 않았음 | `docs/sites/KDB_LIFE.md` §10, `kdb_list.html` | (완료) 약관이 HTML 팝업인 건의 특약 약관 수집까지 구현 |
| NH_LIFE | NH농협생명 | `nhlife.co.kr/ho/on/HOON0004M00.nhl` (config URL 이 정확함) | 성공 | 화면 + HTML 파싱 | ✅ POST 폼 | ✅ 팝업 POST `/ho/on/HOON0004P10.nhl` | ✅ 상품요약서·사업방법서·보험약관 | ✅ 약관 4,947,364 B `%PDF-` | **가능(구현 완료)** | 분석용으로만 필요 | 없음(해결) | 이전 조사는 **페이지 최초 로드만** 관측해 "상품 XHR 없음"으로 판단했음. 실제로는 화면 `#frm` 폼을 **자기 자신에게 POST** 하는 서버 렌더링 방식이라 XHR 이 없는 것이 정상이었음 | `docs/sites/NH_LIFE.md` §10, `nh_life_list.html`/`nh_life_pop.html` | (완료) 전량 dry-run |
| TONGYANG_LIFE | 동양생명 | `pbano.myangel.co.kr/paging/WE_AC_WEPAAP020100L`(판매) / `…020201L`(판매중지) | 성공 | 화면 + HTML 파싱 | ✅ POST 폼 | ✅ 목록 행에 판매기간(시작/종료) 포함 | ✅ 상품요약서·사업방법서·보험약관 | ✅ 약관 29,530,578 B `%PDF-` | **가능(구현 완료)** | 분석용으로만 필요 | 없음(해결) | config URL 이 공시실 진입 화면이고 '보험상품공시' 가 `javascript:void(0)` 메뉴라, 실제 목록 화면 URL 을 찾지 못하고 있었음. 메뉴 버튼의 `value` 속성에 경로가 들어 있었음 | `docs/sites/TONGYANG_LIFE.md` §10, 메뉴 HTML 의 `value="/paging/WE_AC_WEPAAP020100L"` | (완료) 페이지네이션(PP_Query) 재현까지 구현 |
| LINA_LIFE | 라이나생명 | **미확정** (config URL 은 실제로 '판매중지 상품' 화면을 렌더링함) | 성공 | 미확인(판매중 목록) | 부분 — 특약 목록만 확인 | 미확인 | 미확인 | 미확인 | 추가 분석 필요 | 분석용으로 필요 | **목록 조회** | 상품공시실 화면에는 접속되지만, 좌측 메뉴의 '판매중인상품' 이 `href` 없는 JS 메뉴여서 클릭 경로를 재현하지 못했고, 초기 로드에서 호출되는 API 는 **특약(`mtrtDcd=R`) 목록 15건뿐**임. 주계약 목록·문서 다운로드 요청은 사용자가 보종 탭을 고른 뒤에 발생하는 것으로 보이나 아직 기록하지 못함 | `docs/sites/LINA_LIFE.md` §10, `GET api.lina.co.kr/public/contents/v1/disclosure/end-product?mtrtDcd=R&KcisInsKcd=02…` 200/JSON(15건), `mtrtDcd=M` 은 `resultCode=-1` | 브라우저에서 '판매중인상품' 진입 → 보종 탭 선택 → 조회 → 문서 클릭까지 수행하며 Network 기록. `api.lina.co.kr` 는 평문 JSON 이라 확정만 되면 즉시 구현 가능 |
| SHINHAN_LIFE | 신한라이프 | `shinhanlife.co.kr/hp/cdhi0030.do`(판매중) / `/hp/cdhi0040t01.do`(판매중지) | 성공 | API 응답에서 확인(112건) | ✅ POST `/co/wcms/nodeInfoListPage.pwkjson` | ✅ 목록 응답에 meta07/meta08 판매기간 포함 | ✅ meta09 요약서 / meta10 방법서 / meta11 약관 | ✅ 약관 4,140,783 B `%PDF-` | **가능(구현 완료)** | 분석용으로만 필요 | 없음(해결) | ① config URL 이 공시실 메인이라 목록 화면(`cdhi0030`)을 못 찾고 있었음 ② 목록 API 는 찾더라도 **`x-ajax-call: true`, `proworks-body: Y` 헤더가 없으면 `ERROR.SYS.002`** 로 실패함 ③ 문서 경로(`/repo/DigitalPlattform/...`)를 그대로 GET 하면 404 이고, `POST /bizxpress{경로에서 /repo/DigitalPlattform 제거}` 여야 함 | `docs/sites/SHINHAN_LIFE.md` §10, Playwright 요청 헤더 캡처, 다운로드 새 창의 `POST /bizxpress/...` | (완료) 전량 dry-run |
| FUBON_HYUNDAI_LIFE | 푸본현대생명 | **미확정** | 성공(홈) | 미확인 | 미확인 | 미확인 | 미확인 | 미확인 | 추가 분석 필요 | 분석용으로 필요 | **공시실 탐색** | config URL 이 회사 홈페이지임. 홈에서 공시실 메뉴(`goMenu('CUSI150000000000')`)를 열어 하위 메뉴를 받아봤으나 **공시이용 매뉴얼 / 보험가격공시실 / 경영공시실 / 금융기관보험대리점공시실 / 기타공시실** 5개뿐이고 '보험상품공시실' 항목이 노출되지 않음 | `docs/sites/FUBON_HYUNDAI_LIFE.md` §10, `POST /menu/viewPage/cmmn/CUSI150000000000` 응답(3,376 B) | 실제 브라우저에서 공시실 전체 메뉴를 펼쳐 상품공시 메뉴 존재 여부 확인. 없으면 생명보험협회 공시 등 대체 경로 검토 |
| HANWHA_LIFE | 한화생명 | **미확정** | 리다이렉트 | 미확인 | 미확인 | 미확인 | 미확인 | 미확인 | 추가 분석 필요 | 분석용으로 필요 | **공시실 탐색** | config URL 의 옛 ASP 경로(`/announce/goods/goods/goodlist01.asp`)가 더 이상 존재하지 않아 `index.jsp;jsessionid=…` 로 리다이렉트됨. 홈 화면을 렌더링해도 '공시' 를 포함한 링크가 하나도 잡히지 않아 새 공시실 URL 을 확정하지 못함. 구형 TLS 문제는 `legacy_ssl` 로 이미 해결되어 접속 자체는 됨 | `docs/sites/HANWHA_LIFE.md` §10, `GET /announce/goods/goods/goodlist01.asp` → `index.jsp` 리다이렉트(200/50,171 B) | 브라우저에서 전체메뉴/사이트맵을 열어 현행 상품공시실 URL 확인 후 `resolved_disclosure_url` 갱신 |
| HEUNGKUK_LIFE | 흥국생명 | `heungkuklife.co.kr/front/public/saleProduct.do?searchFlgSale=Y` (config URL 이 정확함) | 성공 | API 응답에서 확인 | ✅ POST `/front/public/saleProductAjax.do` | ✅ 같은 엔드포인트에 상품명을 넣으면 판매기간 행 반환 | ✅ 약관·사업방법서·상품요약서 | ✅ 약관 2,092,006 B `%PDF-` | **가능(구현 완료)** | 분석용으로만 필요 | 없음(해결) | 초기 GET 응답의 상품 표가 비어 있어(0행) "조회 폼 파라미터 미확인" 으로 두었으나, 실제로는 화면의 `doSearch()` → `doSearchAjax()` 가 별도 엔드포인트를 호출하는 구조였음. 응답이 JSON/HTML 이 아니라 `%||%`·`%|%`·`%,%` **커스텀 구분자 텍스트(EUC-KR)** 라 파싱 방식도 달랐음 | `docs/sites/HEUNGKUK_LIFE.md` §10, 페이지 인라인 `doSearchAjax()` 정의, 실측 응답 | (완료) 카테고리 I101~I103 · I201~I209 순회 구현 |
| LINA_NON_LIFE | 라이나손해보험 | `ec.aceinsurance.co.kr/jsp/acelimited/notice/productNoticeV2.jsp?status=Y\|N` | 성공 | 화면 + HTML 파싱 | ✅ GET | ✅ 표에 판매기간 포함 | ✅ 사업방법서·상품약관·상품요약서 | ✅ 약관 18,605,422 B `%PDF-` | **가능(구현 완료)** | 분석용으로만 필요 | 없음(해결) | config URL 은 Chubb 본사 AEM 의 **공시 안내 페이지**라 상품 표가 없음. 실제 목록은 `/kr-kr/disclosure/product.html` 의 '판매 중 상품 목록 바로가기' 가 가리키는 **별도 도메인(ec.aceinsurance.co.kr)** 이었음 | `docs/sites/LINA_NON_LIFE.md` §10, `chubb_p_p2_load.html` 의 바로가기 링크, `chubb_list_Y.html`(610,757 B) | (완료) 판매/판매중지 전량 파싱 구현 |
| AIG | AIG손해보험 | **미확정** (config URL 은 '상품공시 이용안내' 화면) | 성공(legacy TLS) | 미확인 | 미확인 | 미확인 | 미확인 | 미확인 | 추가 분석 필요 | 분석용으로 필요 | **공시실 탐색 / 목록 조회** | 화면이 단일 게이트웨이 `POST /bomservice.do` 로 동작하고 **요청 본문은 평문 JSON**(`{"header":{"txCode":"…"},"payload":{…}}`)이라 재현 자체는 가능함. 그러나 메뉴 트리(`txCode=DPWMS003`)를 받아 확인한 결과 상품공시실(MM701) 하위에 **'상품공시 이용안내'(MS701) 하나만** 있고 '판매중 상품'·'판매중지 상품' 화면이 메뉴에 없음. `contentId=DPWMS704/705` 는 보험안내서 화면이었고 `/wo/dpwom001.html` 은 시스템 에러 | `docs/sites/AIG.md` §10, `POST /bomservice.do {txCode:DPWMS003}` 메뉴 트리, `DPWMS704` 렌더 제목 '보험안내서(일반보험)' | 실제 브라우저에서 상품공시실 → 판매중 상품 화면까지 이동해 그때 발생하는 `txCode` 기록. 게이트웨이가 평문이라 txCode 만 확정되면 즉시 구현 가능 |
| NH_FIRE | NH농협손해보험 | `nhfire.co.kr/announce/productAnnounce/retrieveInsuranceProductsAnnounce.nhfire` (config URL 이 정확함) | 성공 | API 응답에서 확인 | ✅ POST `/front/announce/retrievePdtDcd.ajax` → `retrievePdtCd.ajax` | ✅ `retrievePdtInfo.ajax` 가 판매기간+파일ID 반환 | ✅ 약관·상품요약서·사업방법서 | ✅ 약관 878,751 B `%PDF-` | **가능(구현 완료)** | 분석용으로만 필요 | 없음(해결) | 초기 로드에 상품 XHR 이 없어 "조회 엔드포인트 미확인" 으로 두었으나, 화면 인라인 스크립트의 `devon.xSync('/front/announce/…')` 호출부에 엔드포인트가 그대로 적혀 있었음. 응답이 JSON 이 아니라 **xSync XML(`<태그><![CDATA[값]]>`)** 이라 태그별 값이 순서대로 나열되는 형태 | `docs/sites/NH_FIRE.md` §10, 인라인 `fnRetrievePdtDcd`/`fnRetrievePdtCd` 정의, 실측 XML | (완료) 3단계 순회 구현 |
| SAMSUNG_LIFE | 삼성생명 | `samsunglife.com/individual/products/disclosure/sales/PDO-PRPRI010110M` (config URL 이 정확함) | 성공 | 미확인 | 부분 — URL 은 확인, 파라미터 재현 불가 | 미확인 | 미확인 | 미확인 | 어려움 | **수집에도 필요** | **목록 조회** | 상품 목록 API(`POST /gw/api/display/board/content/list/full`)는 확인했으나, 요청 본문이 Yettiesoft VestWeb 으로 **클라이언트에서 암호화**되어 `g=…&b=…` 형태로 전송됨. 평문/빈 본문으로 호출하면 `code:9999 UNKNOWN ERROR` 가 반환됨(실측). 암호화 로직 역산은 접근통제 우회 소지가 있어 시도하지 않음 | `docs/sites/SAMSUNG_LIFE.md` §10, 빈 본문·`g=&b=`·평문 JSON 3가지 모두 `code 9999` 응답 | Playwright 로 화면을 정상 조작(분류 선택 → 목록 → 다운로드 클릭)하고 `expect_download` 로 수집하는 방식 설계 |
| HANWHA_FIRE | 한화손해보험 | **미확정** | 성공 | 미확인 | 미확인 | 미확인 | 미확인 | 미확인 | 어려움 | **수집에도 필요** | **목록 조회** | 화면 진입은 되지만 상품 표가 초기 HTML 에 없고(`<table>` 0개), 관측된 자사 XHR 의 본문이 모두 `Dowz0Lw=…` 로 **클라이언트 암호화**되어 있음(`/notice/ir/product-main.do?evfw=…` 스크립트가 생성). 상품 목록 요청 자체도 아직 관측하지 못함 | `docs/sites/HANWHA_FIRE.md` §10, `POST /popup/global_popup_list.json` 본문 암호문 | Playwright 로 상품공시 화면 조작 경로 확정 후 브라우저 기반 수집 설계 |

---

## 2. 최종 분류

| 분류 | 건수 | 보험사 |
|---|---:|---|
| `HTTP_IMPLEMENTABLE` | 3 | NH_LIFE, HEUNGKUK_LIFE, NH_FIRE (config URL 이 이미 정확했고, 요청 규격만 확정하면 되는 곳) |
| `HTTP_IMPLEMENTABLE_WITH_FIX` | 5 | ABL_LIFE, KDB_LIFE, TONGYANG_LIFE, SHINHAN_LIFE, LINA_NON_LIFE (config URL 교체 또는 필수 헤더 추가가 필요했던 곳) |
| `NEEDS_NETWORK_ANALYSIS` | 2 | LINA_LIFE, AIG |
| `PLAYWRIGHT_REQUIRED` | 0 | - |
| `ACCESS_RESTRICTED` | 2 | SAMSUNG_LIFE, HANWHA_FIRE |
| `DOCUMENT_NOT_PROVIDED` | 0 | - |
| `INVALID_CONFIG_URL` | 2 | FUBON_HYUNDAI_LIFE, HANWHA_LIFE (실제 공시실 URL 자체를 아직 못 찾음) |
| **합계** | **14** | |

> `INVALID_CONFIG_URL` 은 "URL 만 고치면 되는" 5개사(ABL/TONGYANG/SHINHAN/LINA_NON_LIFE/KYOBO 계열)와 구분하기 위해,
> **아직 대체 URL 조차 확정하지 못한** 2개사에만 부여했습니다. URL 을 찾아 교체한 5개사는
> `HTTP_IMPLEMENTABLE_WITH_FIX` 로 분류하고 이번에 구현까지 마쳤습니다.

---

## 3. 최종 요약

### 3.1 직접 HTTP Adapter 로 구현 가능한 보험사 — **8개사 (모두 이번에 구현 완료)**

`ABL_LIFE`, `KDB_LIFE`, `NH_LIFE`, `TONGYANG_LIFE`, `SHINHAN_LIFE`, `HEUNGKUK_LIFE`,
`LINA_NON_LIFE`, `NH_FIRE`

### 3.2 추가 Network 분석이 필요한 보험사 — **2개사**

`LINA_LIFE`(주계약 목록 API 미확정), `AIG`(상품 목록 화면 txCode 미확정)
— 두 곳 모두 **요청이 평문**이므로, 화면 조작 후의 요청 1~2건만 기록하면 바로 구현 가능합니다.

### 3.3 Playwright 수집 방식이 필요한 보험사 — **2개사**

`SAMSUNG_LIFE`, `HANWHA_FIRE` — 요청 본문이 클라이언트에서 암호화되어 `httpx` 로 동일한 값을
만들 수 없습니다. 기존 `MERITZ` 와 같은 헤드풀 브라우저 수집 방식이 필요합니다.

### 3.4 URL 수정이 필요한 보험사 — **7개사**

| 보험사 | 조치 |
|---|---|
| ABL_LIFE | `resolved_disclosure_url` 추가 → **완료** |
| TONGYANG_LIFE | `resolved_disclosure_url` 을 실제 목록 화면으로 교체 → **완료** |
| SHINHAN_LIFE | `resolved_disclosure_url` 추가 → **완료** |
| LINA_NON_LIFE | `resolved_disclosure_url` 추가(별도 도메인) → **완료** |
| LINA_LIFE | config URL 이 판매중지 화면을 렌더링 → 판매중 화면 URL 확인 필요 |
| FUBON_HYUNDAI_LIFE | 홈페이지 URL → 공시실 URL 탐색 필요 |
| HANWHA_LIFE | 폐기된 ASP 경로 → 현행 공시실 URL 탐색 필요 |

### 3.5 접근 제한이 확인된 보험사 — **2개사**

`SAMSUNG_LIFE`, `HANWHA_FIRE`. WAF·CAPTCHA·로그인이 아니라 **요청 파라미터 암호화**입니다.
암호화 역산은 시도하지 않았습니다.

### 3.6 보험사별 다음 작업 우선순위

| 우선순위 | 보험사 | 작업 | 예상 난이도 |
|---|---|---|---|
| 1 | LINA_LIFE | 브라우저에서 '판매중인상품' 진입 후 목록 API 1건 기록 | 낮음(API 평문) |
| 2 | AIG | 상품공시실 → 판매중 상품 화면의 `txCode` 1건 기록 | 낮음(게이트웨이 평문) |
| 3 | HANWHA_LIFE | 현행 공시실 URL 확인 후 구조 분석 | 중간 |
| 4 | FUBON_HYUNDAI_LIFE | 상품공시 메뉴 존재 여부 확인 | 중간 |
| 5 | SAMSUNG_LIFE | Playwright 화면 조작 수집 설계 | 높음 |
| 6 | HANWHA_FIRE | Playwright 화면 조작 수집 설계 | 높음 |

### 3.7 기존 분류에서 변경해야 할 보험사

| 보험사 | 기존 | 변경 후 | 사유 |
|---|---|---|---|
| ABL_LIFE | MANUAL_REVIEW_REQUIRED | **IMPLEMENTED** | 전 경로 확정 + 3종 다운로드 검증 |
| KDB_LIFE | MANUAL_REVIEW_REQUIRED | **IMPLEMENTED** | 〃 |
| NH_LIFE | MANUAL_REVIEW_REQUIRED | **IMPLEMENTED** | 〃 |
| TONGYANG_LIFE | MANUAL_REVIEW_REQUIRED | **IMPLEMENTED** | 〃 |
| SHINHAN_LIFE | MANUAL_REVIEW_REQUIRED | **IMPLEMENTED** | 〃 |
| HEUNGKUK_LIFE | MANUAL_REVIEW_REQUIRED | **IMPLEMENTED** | 〃 |
| LINA_NON_LIFE | MANUAL_REVIEW_REQUIRED | **IMPLEMENTED** | 〃 |
| NH_FIRE | MANUAL_REVIEW_REQUIRED | **IMPLEMENTED** | 〃 |
| LINA_LIFE | MANUAL_REVIEW_REQUIRED | MANUAL_REVIEW_REQUIRED (유지) | 목록 API 미확정 |
| AIG | MANUAL_REVIEW_REQUIRED | MANUAL_REVIEW_REQUIRED (유지) | 목록 화면 미확정 |
| FUBON_HYUNDAI_LIFE | MANUAL_REVIEW_REQUIRED | MANUAL_REVIEW_REQUIRED (유지) | 공시실 URL 미확정 |
| HANWHA_LIFE | MANUAL_REVIEW_REQUIRED | MANUAL_REVIEW_REQUIRED (유지) | 공시실 URL 미확정 |
| SAMSUNG_LIFE | ACCESS_DENIED | **ACCESS_RESTRICTED** (동일 의미, 명칭만 정정) | 접근 차단이 아니라 파라미터 암호화 |
| HANWHA_FIRE | ACCESS_DENIED | **ACCESS_RESTRICTED** (동일 의미, 명칭만 정정) | 〃 |

---

## 4. 이번 조사로 구현한 8개사 — Adapter 및 검증 결과

| 코드 | Adapter 파일 | 수집 방식 | 표본 수집 결과 | 실제 다운로드(약관 / 사업방법서 / 상품요약서) |
|---|---|---|---|---|
| ABL_LIFE | `crawler/adapters/abl_life.py` | STATIC_HTML | 상품 6건 표본 → 28버전 / 62문서 | 13,461,120 / 115,212 / 395,540 B — 모두 `%PDF-` |
| KDB_LIFE | `crawler/adapters/kdb_life.py` | JSON_API | 판매 70행 · 판매중지 310행 | 2,334,697 / 155,609 / 731,375 B |
| NH_LIFE | `crawler/adapters/nh_life.py` | FORM_POST | 상품 3건 표본 → 7버전 / 17문서 | 4,947,364 / 303,687 / 380,403 B |
| TONGYANG_LIFE | `crawler/adapters/tongyang_life.py` | FORM_POST | 판매 56건(6페이지) | 29,530,578 / 296,265 / 4,137,265 B |
| SHINHAN_LIFE | `crawler/adapters/shinhan_life.py` | JSON_API | 판매중 112건 | 4,140,783 / 95,295 / 160,305 B |
| HEUNGKUK_LIFE | `crawler/adapters/heungkuk_life.py` | FORM_POST | 상품 4건 표본 → 18버전 / 52문서 | 2,092,006 / 488,055 / 105,437 B |
| LINA_NON_LIFE | `crawler/adapters/lina_non_life.py` | STATIC_HTML | 판매 표 10개 / 판매중지 표 11개 | 18,605,422 / 70,718 / 182,769 B |
| NH_FIRE | `crawler/adapters/nh_fire.py` | XML_AJAX | 정책보험 표본 33버전 / 99문서 | 878,751 / 84,220 / 163,232 B |

- `pytest`: **149 passed / 5 skipped / 0 failed** (기존 테스트 무변경)
- 전체 Adapter 수: 16 → **24개** (30개사 중 24개사 구현)
- 남은 미구현: **6개사** (LINA_LIFE, AIG, FUBON_HYUNDAI_LIFE, HANWHA_LIFE, SAMSUNG_LIFE, HANWHA_FIRE)

---

## 5. 조사 과정에서 확인한 일반화 가능한 교훈

1. **"페이지 최초 로드에 XHR 이 없다" ≠ "API 가 없다"**
   NH농협생명·흥국생명·NH농협손보 3곳 모두 초기 로드에는 상품 요청이 없었지만,
   화면 인라인 스크립트(`doSearchAjax`, `devon.xSync`, `#frm.submit()`)에 엔드포인트가 그대로 있었습니다.
2. **config URL 이 '공시실 안내' 화면인 경우가 많음**
   ABL생명·동양생명·신한라이프·라이나손보 4곳은 URL 교체만으로 해결됐습니다.
   안내 화면의 '바로가기' 링크나 메뉴 버튼의 `value` 속성을 먼저 확인해야 합니다.
3. **응답이 JSON/HTML 이 아닐 수 있음**
   흥국생명은 `%||%` 구분자 텍스트, NH농협손보는 xSync XML 이었습니다.
4. **필수 헤더가 응답을 가른다**
   신한라이프는 `x-ajax-call`/`proworks-body`, 미래에셋생명은 `Accept`, DB손해보험은 `Content-Type` 이 없으면 실패합니다.
5. **암호화는 명확한 근거가 있을 때만 결론**
   삼성생명·한화손보는 요청 본문 암호문을 직접 관측하고, 평문 호출이 오류를 반환하는 것까지 확인했습니다.
