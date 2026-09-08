# REMAINING_14_IMPLEMENTATION_RESULT.md — 미구현 14개사 구현 결과

> **Historical Snapshot — 2026-08-04**
> 이 문서는 해당 날짜의 중간 구현 결과를 보존한 역사 기록입니다. 현재 운영 상태와
> 실행 방법의 정본은 `README.md` 및 `docs/ENDPOINT_MATRIX.md`를 확인하세요.
> 본문에 등장하는 `scratchpad/*`는 저장소 외부의 당시 조사 증적이며 현재 실행할 수 없습니다.

> ⚠️ 역사적 스냅샷: 이 문서는 **2026-08-04 조사 당시의 중간 결과**를 보존합니다.
> 이후 AIG·LINA_LIFE가 구현 완료되었으므로 현재 상태와 집계는
> [`IMPLEMENTATION_RESULT.md`](IMPLEMENTATION_RESULT.md) 및 [`ENDPOINT_MATRIX.md`](ENDPOINT_MATRIX.md)를 기준으로 합니다.
> 이 문서의 `ACCESS_DENIED` 표기는 현재의 `ACCESS_RESTRICTED`에 해당하는 당시 용어입니다.

> 작업일: **2026-08-04**
> 대상: 기존 `MANUAL_REVIEW_REQUIRED` 12개사 + `ACCESS_DENIED` 2개사
> 관련 문서: `docs/UNIMPLEMENTED_COMPANY_ANALYSIS.md`(원인 조사), `docs/ENDPOINT_MATRIX.md`,
> `docs/IMPLEMENTATION_RESULT.md`, `docs/REGRESSION_TEST_RESULT.md`, `docs/sites/*.md`
>
> **작업 착수 시점 정정**: 요청서에는 "16개사 구현 완료" 로 되어 있으나, 직전 회차에서
> 8개사(ABL_LIFE, KDB_LIFE, NH_LIFE, TONGYANG_LIFE, SHINHAN_LIFE, HEUNGKUK_LIFE,
> LINA_NON_LIFE, NH_FIRE)를 이미 구현·검증 완료해 **24개사** 상태였습니다.
> 따라서 이번 회차의 실제 대상은 **남은 6개사**였습니다.

---

## 1. 보험사별 결과 표

| 코드 | 보험사 | 구현 방식 | 상품 목록 | 판매기간 | 문서 3종 | 실제 다운로드 | 전체 Dry-run | 실행 시간 | 최종 상태 | 남은 문제 |
|---|---|---|---|---|---|---|---|---|---|---|
| ABL_LIFE | ABL생명 | HTTP (STATIC_HTML) | ✅ 판매/판매중지 × 8분류 | ✅ 상세 표 | ✅ | ✅ 3종 | 표본(상품 6건→28버전) | 표본 40초 | `IMPLEMENTED_HTTP` | 전량 dry-run 미실시(상품 수 많음) |
| KDB_LIFE | KDB생명 | HTTP (JSON_API) | ✅ 판매/판매중지 × 5그룹 | ✅ GP='B' 행 | ✅ | ✅ 3종 | ✅ 170버전→대상 50 | 약 3분 | `IMPLEMENTED_HTTP` | 판매중지 화면 상세 요청 미확정(§4.2) |
| NH_LIFE | NH농협생명 | HTTP (FORM_POST) | ✅ 페이지네이션 | ✅ 팝업 | ✅ | ✅ 3종 | 표본(상품 3건→7버전) | 표본 1분 | `IMPLEMENTED_HTTP` | 전량 dry-run 미실시 |
| TONGYANG_LIFE | 동양생명 | HTTP (FORM_POST) | ✅ 판매/판매중지 | ✅ 목록 행 | ✅ | ✅ 3종 | ✅ 609버전→대상 22 | 약 2분 | `IMPLEMENTED_HTTP` | 없음 |
| LINA_LIFE | 라이나생명 | HTTP (JSON_API) | ✅ 403건 | ✅ sellOpnDt/sellEndDt | ❌ **미제공** | ❌ | ✅ 403버전→대상 1 | 약 3분 | **`PARTIAL`** | 문서 반환 요청 미확정(§4.1) |
| SHINHAN_LIFE | 신한라이프 | HTTP (JSON_API) | ✅ 1,646건 | ✅ meta07/08 | ✅ | ✅ 3종 | ✅ 대상 90 | 약 2분 | `IMPLEMENTED_HTTP` | 없음 |
| FUBON_HYUNDAI_LIFE | 푸본현대생명 | — | ❌ | ❌ | ❌ | ❌ | ❌ | — | **`ACCESS_RESTRICTED`** | robots.txt 전면 차단(§4.3) |
| HANWHA_LIFE | 한화생명 | HTTP (JSON_API 3단계) | ✅ 분류→상품 | ✅ PType=3 | ✅ | ✅ 3종 | 표본(상품 4건→4버전/16문서) | 표본 1분 | `IMPLEMENTED_HTTP` | 전량 dry-run 미실시 |
| HEUNGKUK_LIFE | 흥국생명 | HTTP (FORM_POST) | ✅ 판매/판매중지 × 분류 | ✅ 상세 조회 | ✅ | ✅ 3종 | 표본(상품 4건→18버전) | 표본 1분 | `IMPLEMENTED_HTTP` | 전량 dry-run 미실시 |
| LINA_NON_LIFE | 라이나손해보험 | HTTP (STATIC_HTML) | ✅ 3,379건 | ✅ 표 | ✅ | ✅ 3종 | ✅ 대상 59 | 약 1분 | `IMPLEMENTED_HTTP` | 없음 |
| AIG | AIG손해보험 | — | ❌ | ❌ | ❌ | ❌ | ❌ | — | **`DOCUMENT_NOT_PROVIDED`** | 홈페이지 공시실에 상품 목록 화면 자체가 없음(§4.4) |
| NH_FIRE | NH농협손해보험 | HTTP (XML_AJAX 3단계) | ✅ 4상품군 | ✅ retrievePdtInfo | ✅ | ✅ 3종 | 표본(정책보험 33버전) | 표본 1분 | `IMPLEMENTED_HTTP` | 전량 dry-run 미실시 |
| SAMSUNG_LIFE | 삼성생명 | **HYBRID** (Playwright 목록 + HTTP 다운로드) | ✅ 6,565건 | ✅ fromdate/todate | 약관·방법서 ✅ / 요약서 표본 내 없음 | ✅ 2종 | 표본(3페이지→30버전/53문서) | 표본 1분 | **`IMPLEMENTED_HYBRID`** | 전량은 657페이지(§4.5) |
| HANWHA_FIRE | 한화손해보험 | — | ❌ | ❌ | ❌ | ❌ | ❌ | — | **`ACCESS_RESTRICTED`** | robots.txt 상 공시실 경로 미허용(§4.6) |

### 집계

| 최종 상태 | 건수 | 보험사 |
|---|---:|---|
| `IMPLEMENTED_HTTP` | 10 | ABL_LIFE, KDB_LIFE, NH_LIFE, TONGYANG_LIFE, SHINHAN_LIFE, HANWHA_LIFE, HEUNGKUK_LIFE, LINA_NON_LIFE, NH_FIRE, (직전 회차 포함) |
| `IMPLEMENTED_HYBRID` | 1 | SAMSUNG_LIFE |
| `IMPLEMENTED_PLAYWRIGHT` | 0 | — (기존 MERITZ 는 이번 대상 아님) |
| `PARTIAL` | 1 | LINA_LIFE |
| `ACCESS_RESTRICTED` | 2 | FUBON_HYUNDAI_LIFE, HANWHA_FIRE |
| `DOCUMENT_NOT_PROVIDED` | 1 | AIG |
| **합계** | **14** | |

---

## 2. 이번 회차(2026-08-04)에 새로 구현한 3개사 상세

### 2.1 한화생명 (HANWHA_LIFE) — `IMPLEMENTED_HTTP`

| 항목 | 값 |
|---|---|
| 실제 상품공시실 URL | `https://www.hanwhalife.com/main/disclosure/goods/disclosurenotice/DF_GDDN000_P10000.do?MENU_ID1=DF_GDGL000&MENU_ID2=DF_GDGL000_P10000` |
| URL 발견 경로 | `robots.txt` → `sitemap_index.jsp` → `sitemap_pc.jsp` → `/static/main/disclosure/fund/DC_FD00000_P10000.htm` 의 '공시실' 링크 → 공시실 메인의 '판매상품' 링크 |
| 목록 API | `POST /main/disclosure/goods/goodslist/getList.do` |
| 파라미터 | `PType=1` 분류 / `PType=2 + sellType,goodsType` 상품 / `PType=3 + goodsIndex` 판매기간·파일명, `sellFlag=Y\|N`, `__MENU_ID=DF_GDGL000` |
| 필수 헤더 | `Referer`, `X-Requested-With: XMLHttpRequest`, `Content-Type: application/x-www-form-urlencoded; charset=UTF-8` |
| Cookie/세션 | 화면 1회 GET 으로 세션 확보 |
| 다운로드 | `POST https://file.hanwhalife.com/www/announce/goods/download_chk.asp`, body `file_name=<EUC-KR URL 인코딩>` — **본 사이트가 아닌 파일 전용 도메인** |
| TLS | 구형 스택 → `options.legacy_ssl: true` 필요 |
| 응답 필드 | `SELL_START_DT`, `SELL_END_DT`, `FILE_NAME1` 상품요약서 / `FILE_NAME2` 사업방법서 / `FILE_NAME3~` 약관(복수) |
| 표본 결과 | 상품 4건 → 4버전 / 문서 16건 |
| 실제 다운로드 | 약관 30,532,753 B · 사업방법서 775,855 B · 상품요약서 7,369,817 B — 모두 `%PDF-1` |
| Playwright | 분석용으로만 사용(수집은 순수 HTTP) |

### 2.2 삼성생명 (SAMSUNG_LIFE) — `IMPLEMENTED_HYBRID`

| 항목 | 값 |
|---|---|
| 실제 상품공시실 URL | `https://www.samsunglife.com/individual/products/disclosure/sales/PDO-PRPRI010110M` (config URL 정확) |
| 목록 API | `POST /gw/api/product/disclosure/product/prdt/salesAllPrdtList` |
| **요청** | Yettiesoft VestWeb 으로 **암호화**(`g=…&b=…`) → httpx 로 생성 불가 |
| **응답** | **평문 JSON** — `response[]` = `{goodsCode, goodsName, fromdate, todate, lCode, gubun, filename1~3, totalRows, pageSize, pageNo}` |
| 채택 방식 | **HYBRID** — Playwright 로 화면을 열고 페이지 이동만 수행하면서 **응답을 가로채** 목록을 얻고, 파일은 기존 `HttpClient` 로 다운로드 |
| 문서 URL | `https://pcms.samsunglife.com/uploadDir/doc/{YYYY}/{MMDD}/{goodsCode}/{docType}/{filename}.pdf` |
| docType 매핑 | `filename1`→`201` 상품요약서 / `filename2`→`401` 사업방법서 / `filename3`→`301` 보험약관 (팝업 URL 클릭으로 실측) |
| 경로 규칙 | `{YYYY}/{MMDD}` 는 `filename`(epoch ms)의 업로드 일자. 실측 검증 완료 |
| 규모 | 전체 6,565건 / 페이지당 10건 → 657페이지 |
| 표본 결과 | 3페이지 → 30버전 / 문서 53건 |
| 실제 다운로드 | 보험약관 1,028,052 B · 사업방법서 163,221 B — 모두 `%PDF-1` |
| 미검증 | 상품요약서(`filename1`)는 표본 3페이지(모두 오래된 판매중지 상품) 범위에 없었음 |
| 암호화 처리 | **역산·우회하지 않음.** 사이트가 의도한 화면 동작(페이지 이동)만 수행 |

`options.max_pages` 로 페이지 상한을 둘 수 있으며 사용 시 `coverage_capped` 로 기록됩니다.

### 2.3 라이나생명 (LINA_LIFE) — `PARTIAL`

| 항목 | 값 |
|---|---|
| 실제 화면 | `https://www.lina.co.kr/disclosure/product-public-announcement/product-on-sales` (기본 렌더는 **판매중지** 탭) |
| 판매중 목록 | `GET https://api.lina.co.kr/public/contents/v1/disclosure/product-list` |
| 판매중지 목록 | `GET https://api.lina.co.kr/public/contents/v1/disclosure/end-product` |
| 파라미터 | `mtrtDcd=B`(주보험) / `R`(특약), `KliaProdClcd`(주보험 분류 01~12), `KcisInsKcd`, `searchKey`, `inscd`, `prodPbanGrpCd`, `tabTitle` |
| 응답 | `listDisclosure[]` = `{inscd, insureCd, insNm, sellOpnDt, sellEndDt, kcisInsKcd, prodPbanGrpCd, kliaProdClcd}` |
| 수집 결과 | **403버전**(판매중 93 / 판매중지 310), 2026-07 대상 1건 |
| **문서** | **응답에 파일 정보가 없음.** 문서를 반환하는 요청을 확정하지 못함 |
| 미확정 사유 | 화면이 headless 브라우저에서 상품 행을 렌더링하지 않아(`table` 0개, "직접검색을 원하시면 상품명을 입력 후 검색") 문서 버튼 클릭 경로를 재현하지 못함. `inscd`/`prodPbanGrpCd` 를 목록 API 에 넣어도 응답 구조가 동일해 문서 필드가 나오지 않음(실측) |
| 조치 | **추정 URL 을 만들지 않고** 상품·판매기간까지만 수집. `stats.document_endpoint_unconfirmed = True` 로 표시 |

---

## 3. 구현하지 않은 3개사와 근거

### 3.1 푸본현대생명 (FUBON_HYUNDAI_LIFE) — `ACCESS_RESTRICTED`

```
$ curl https://www.fubonhyundai.com/robots.txt
User-agent: Yeti
Disallow:

User-agent: *
Disallow:/
```

- 네이버 검색봇(Yeti) 외 **모든 크롤러를 전면 차단**하며 예외 경로가 없습니다.
- 사이트 운영자가 자동 수집을 명시적으로 거부한 상태이므로 **Adapter 를 구현하지 않았습니다.**
- 부수 확인: 공시실 메뉴(`POST /menu/viewPage/cmmn/CUSI150000000000`)에도
  '보험상품공시실' 항목이 없고 5개(공시이용 매뉴얼·보험가격·경영·금융기관보험대리점·기타)만 존재합니다.
- **후속 조치**: 수집이 필요하면 푸본현대생명과 별도 협의(수집 허용 또는 자료 직접 제공)가 필요합니다.

### 3.2 한화손해보험 (HANWHA_FIRE) — `ACCESS_RESTRICTED`

- `robots.txt` 가 `Disallow: /` 이며, 개별 `Allow` 364건 중
  **상품공시실 경로(`/notice/ir/product-main.do` 등)는 포함되어 있지 않습니다.**
- 추가로 화면의 자사 XHR 본문이 `Dowz0Lw=…` 로 클라이언트 암호화되어 있습니다.
- config URL 은 '상품공시실 안내' 화면이며, 하위 상품 목록 화면은 `/notice/ir/` 하위 링크에
  존재하지 않았습니다(정적 HTML 에 `/notice/ir/product-main.do` 하나뿐).
- 두 근거(robots 미허용 + 요청 암호화) 모두 자동 수집을 제한하므로 **구현하지 않았습니다.**

### 3.3 AIG손해보험 (AIG) — `DOCUMENT_NOT_PROVIDED`

- 게이트웨이 `POST /bomservice.do` 는 **평문 JSON** 이라 재현 가능하며, `legacy_ssl` 로 접속도 정상입니다.
  즉 기술적 차단은 없습니다.
- 그러나 메뉴 트리를 전수 조회한 결과 **판매중/판매중지 상품 목록 화면이 사이트에 없습니다.**

| 확인 | 결과 |
|---|---|
| `txCode=DPWMS003, menuClcd=1/2/3` 전체 메뉴 | 상품공시실(`MM701`) 하위에 `MS701` 상품공시 이용안내 **1개뿐** |
| `txCode=DPWMS015, menuId=MM701` | `상품공시실` 만 반환 |
| `contentId=DPWMS704 / DPWMS705` | 렌더 결과 '보험안내서(일반보험)' 화면 |
| `/wo/dpwom001.html` | 시스템 에러 페이지로 이동 |
| 메뉴에서 '약관' 검색 | 전자금융거래약관·홈페이지 이용약관 등 **이용약관류만** 존재 |
| `contentId=DPWMS701` 본문 | '판매중 상품 / 판매중지 상품' 은 **설명 텍스트**이며 링크 없음 |

- **후속 조치**: AIG손해보험은 손해보험협회 공시 등 외부 채널로 자료를 게시할 가능성이 있어
  별도 확인이 필요합니다. 홈페이지만으로는 수집 대상 문서에 도달할 수 없습니다.

---

## 4. 남은 문제

### 4.1 라이나생명 문서 요청 미확정
- 목록/판매기간은 확보. 문서 반환 요청 1건만 기록하면 즉시 완성 가능합니다.
- 재현: 실제 브라우저에서 판매중인상품 → 주보험 탭 → 상품 행 클릭 → 문서 버튼 클릭 시 Network 기록.

### 4.2 KDB생명 판매중지 상세
- `HDLMA002M03P` 응답은 상품명만 반환(218행 전부 `SALE_START_DATE=null`).
- 현재 Adapter 는 날짜·문서가 모두 없는 행을 건너뛰고 `stats.stop_sale_detail_missing` 에 건수만 기록합니다.

### 4.3 삼성생명 전량 수집 시간
- 657페이지 페이지 이동이 필요합니다(요청 간격 2초 기준 약 22분 + 렌더 대기).
- `options.max_pages` 로 조절할 수 있으나, 대상 월 상품이 목록 앞쪽/뒤쪽 어디에 있는지에 따라
  상한을 걸면 누락이 생깁니다. 전량 실행 권장.

### 4.4 iM라이프 robots.txt 확인 필요 (기존 구현분)
- 이번에 전 30개사 `robots.txt` 를 점검하면서 발견했습니다.

```
User-Agent: *
Disallow: /
Allow: /BA/    ← 목록 경로(/BA/BA_A020.do)는 허용
...
(다운로드 경로 /www/downloadChk.do 는 Allow 목록에 없음)
```

- **목록 수집 경로는 명시적으로 허용**되어 있으나, **다운로드 경로는 허용 목록에 없습니다.**
- 기존에 동작 중인 Adapter 라 임의로 중단하지 않았습니다. **운영 정책 판단이 필요합니다.**

### 4.5 전량 Dry-run 미실시 보험사
`ABL_LIFE`, `NH_LIFE`, `HANWHA_LIFE`, `HEUNGKUK_LIFE`, `NH_FIRE`, `SAMSUNG_LIFE` 는
상품별 상세 요청이 필요해 표본으로 검증했습니다. 전량 실행 명령은 아래와 같습니다.

```bash
python main.py --target-month 2026-07 --company ABL_LIFE --dry-run
python main.py --target-month 2026-07 --company NH_LIFE --dry-run
python main.py --target-month 2026-07 --company HANWHA_LIFE --dry-run
python main.py --target-month 2026-07 --company HEUNGKUK_LIFE --dry-run
python main.py --target-month 2026-07 --company NH_FIRE --dry-run
python main.py --target-month 2026-07 --company SAMSUNG_LIFE --dry-run
```
