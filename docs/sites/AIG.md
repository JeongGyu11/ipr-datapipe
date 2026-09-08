# AIG손해보험 상품공시실 분석

## 1. 기본 정보

- 보험사 코드: `AIG`
- 보험사명: AIG손해보험
- 보험 구분: 손해보험(non_life)
- config URL: https://www.aig.co.kr/wm/content.html?contentId=DPWMS701 (상품공시 이용안내 화면)
- 실제 상품 목록 URL: https://www.aig.co.kr/wo/dpwot001.html?menuId=MS702
- 판매 중 상품 URL: https://www.aig.co.kr/wo/dpwot001.html?menuId=MS702
- 판매 중지 상품 URL: https://www.aig.co.kr/wo/dpwot002.html?menuId=MS703
- 확인일: 2026-07-31 (최초) / **2026-08-06 (상품 목록 화면 확인 후 전면 정정 — §12)**

## 2. 사이트 특징

- 렌더링 방식: JAVASCRIPT_RENDERED (초기 HTML 8.6KB 셸)
- 상품 카테고리: 확인 불가
- 판매채널 구분: 확인 불가
- 검색 조건: 확인 불가
- 날짜 제공 방식: 확인 불가
- 페이지네이션 방식: 확인 불가
- 상품 버전 표시 방식: 확인 불가
- 이전 판매기간 제공 여부: 확인 불가
- 팝업 또는 모달 사용 여부: 확인 불가

## 3. 실제 엔드포인트

| 구분 | 메서드 | 엔드포인트 | 주요 파라미터 | 응답 형식 |
|---|---|---|---|---|
| 세션 초기화 | GET | `/wm/content.html?contentId=DPWMS701` | - | HTML(200, 8,595 bytes) |
| 상품 목록 | - | 확인 불가 | - | - |
| 상품 상세 | - | 확인 불가 | - | - |
| 판매기간 | - | 확인 불가 | - | - |
| 첨부파일 목록 | - | 확인 불가 | - | - |
| 파일 다운로드 | - | 확인 불가 | - | - |

## 4. 필수 요청 정보

- Referer: 설정함(config 의 url)
- Origin: 불필요
- User-Agent: config.crawler.user_agent
- Cookie: 불필요
- 세션: 불필요
- CSRF: 없음
- 인코딩: UTF-8
- 기타 헤더: 없음

## 5. 문서 링크 구조

- 약관: 추가 수동 확인 필요
- 사업방법서: 추가 수동 확인 필요
- 상품요약서: 추가 수동 확인 필요
- 상대 URL 여부: 확인 불가
- JavaScript 함수 여부: 확인 불가
- 파일명 획득 방법: 확인 불가
- 한 상품에 여러 문서 존재 여부: 확인 불가

## 6. 구현 방식

- Adapter 파일: `crawler/adapters/aig.py` (`AIGAdapter`)
- 등록: `crawler/adapters/__init__.py` (`"AIG": AIGAdapter`)
- 수집 방식: JSON_API (`/bomservice.do` 목록 API)
- Playwright 사용 여부: 사용 안 함
- 선택한 구현 방식의 이유: 화면이 호출하는 평문 JSON 목록·파일 API를 재현
- 공통 유틸리티 사용 내역: `BaseInsurerAdapter.client`(HttpClient)와 `utils.date_utils.parse_date` 사용

## 7. 테스트 결과

- 대상 월: 2026-07
- 수집 상품 수: 확인 불가
- 상품 버전 수: 확인 불가
- 약관 링크 수: 확인 불가
- 사업방법서 링크 수: 확인 불가
- 상품요약서 링크 수: 확인 불가
- 다운로드 성공 수: 0
- 실패 수: 0
- 중복 수: 0
- 누락 또는 수동 검토 수: 전건 수동 확인 필요

## 8. 제한 사항

- WAF: 관측되지 않음
- CAPTCHA: 관측되지 않음
- 세션 만료: 관측되지 않음
- 조회 범위 제한: 없음
- 날짜 누락: 없음
- 문서 누락: 없음
- 기타 문제: **구형 TLS** — 기본 SSL 컨텍스트로는 `TLS/SSL connection has been closed (EOF)` 로 연결 실패. `options.legacy_ssl: true` 를 config 에 미리 설정해 두었습니다(이 설정으로 HTTP 200 수신 확인). 다만 상품 목록을 만드는 XHR 을 확정하지 못했습니다

## 9. 확인 근거

- 확인한 화면: AIG 상품공시 화면(셸)
- 확인한 Network 요청: legacy TLS 컨텍스트로 `GET /wm/content.html?contentId=DPWMS701` 200 확인
- 테스트 상품: 미검증
- 테스트 파일: 미검증
- 레거시 근거(2026-07-31 수동 조사): `C:/…/scratchpad/net.py` Playwright 네트워크 로깅 출력 — 현재 저장구조/리포지토리에 포함되지 않음

---

## 10. 후속 조사 (2026-08-04)

- **최종 분류**: `NEEDS_NETWORK_ANALYSIS` (변경 없음)
- **현재 실패 단계**: **공시실 탐색 / 목록 조회**
- **정확한 원인**
  - config URL(`contentId=DPWMS701`)은 **'상품공시 이용안내'** 화면입니다.
    본문 표에 '판매중 상품 / 판매중지 상품' 이 나오지만 이는 공시자료 **설명**이며 링크가 아닙니다.
  - 메뉴 트리(`POST /bomservice.do {txCode:DPWMS003, payload:{menuClcd:1}}`)를 받아 확인한 결과
    상품공시실(`menuId=MM701`) 하위에 **'상품공시 이용안내'(MS701) 하나만** 있고
    판매중/판매중지 상품 화면이 메뉴에 없습니다. `menuClcd=2`(기업)·`3` 에도 없습니다.
  - `contentId=DPWMS704/705` 는 렌더링 결과 **'보험안내서(일반보험)'** 화면이었습니다.
  - 메뉴의 `fileNm` 인 `/wo/dpwom001.html` 은 **시스템 에러 페이지**로 이동합니다.
- **중요**: 이 사이트는 단일 게이트웨이 `POST /bomservice.do` 를 쓰며 **요청 본문이 평문 JSON**
  (`{"header":{"txCode":"..."},"payload":{...}}`)입니다. 암호화·WAF·CAPTCHA 는 관측되지 않았습니다.
  즉 **접근 제한이 아니라 화면 경로 미확정** 문제입니다.
- **TLS**: `options.legacy_ssl: true` 로 접속 문제는 이미 해결(200 수신 확인).
- **후속 작업**: 실제 브라우저에서 상품공시실 → 판매중 상품 화면까지 이동해 그때 발생하는
  `txCode` 를 1건만 기록하면 즉시 구현 가능합니다.

---

## 11. 2026-08-04 구현 결과

- **최종 분류**: `NEEDS_NETWORK_ANALYSIS` → **`DOCUMENT_NOT_PROVIDED`**
- **기술적 차단은 없음**: 게이트웨이 `POST /bomservice.do` 의 요청 본문은
  **평문 JSON**(`{"header":{"txCode":"…"},"payload":{…}}`)이며 `options.legacy_ssl: true` 로 접속도 정상입니다.
- **그러나 상품 목록 화면이 사이트에 존재하지 않습니다(2026-08-04 전수 확인)**

  | 확인 | 결과 |
  |---|---|
  | `txCode=DPWMS003` `menuClcd=1/2/3` 전체 메뉴 트리 | 상품공시실(`MM701`) 하위에 `MS701` **'상품공시 이용안내' 1개뿐** |
  | `txCode=DPWMS015, menuId=MM701` | `상품공시실` 만 반환 |
  | `txCode=DPWMS015, menuId=MS701` | `상품공시 이용안내` 만 반환 |
  | `contentId=DPWMS704 / DPWMS705` | 렌더 제목 '보험안내서(일반보험)' |
  | `/wo/dpwom001.html` | 시스템 에러 페이지로 이동 |
  | 메뉴에서 '약관' 검색 | 전자금융거래약관 · 홈페이지 이용약관 등 **이용약관류만** |
  | `contentId=DPWMS701` 본문(`txCode=DPWMS011`) | '판매중 상품 / 판매중지 상품' 은 **설명 텍스트**이며 링크 없음 |

- **결론**: 홈페이지 상품공시실에서 약관·사업방법서·상품요약서 파일에 도달할 수 있는 화면이 제공되지 않습니다.
  "링크를 못 찾음" 이 아니라 **화면 자체가 메뉴에 없음** 입니다.
- **후속 조치**: 손해보험협회 공시 등 외부 채널 게시 여부를 별도 확인해야 합니다.

---

## 12. 2026-08-06 구현 완료 — §10 · §11 결론 정정

### 12.1 이전 결론이 틀렸습니다

§10 `NEEDS_NETWORK_ANALYSIS` / §11 `DOCUMENT_NOT_PROVIDED` 는 **모두 오판입니다.**
상품공시 화면은 존재하며, 약관·사업방법서·상품요약서가 정상 제공됩니다.

**오판 원인**: 메뉴 API(`DPWMS003`, `DPWMS015`)만 조회해 `MS701`(상품공시 이용안내)까지만 확인했고,
`MS702`/`MS703` 이 메뉴 응답에 없다는 이유로 "화면이 존재하지 않는다"고 단정했습니다.
또 `/wo/dpwom001.html` 이 에러 페이지인 것을 보고 `/wo/` 계열 전체를 배제했으나,
실제 화면은 **`dpwom001` 이 아니라 `dpwot001`** 입니다.
**메뉴 API 에 없다는 사실은 화면이 없다는 근거가 되지 못합니다.**

### 12.2 실제 엔드포인트 (2026-08-06 실측)

| 구분 | 메서드 | 엔드포인트 | 요청 | 응답 |
|---|---|---|---|---|
| 목록 | POST | `/bomservice.do` | `{"header":{"txCode":"DPWOS002"},"payload":{"useYn":"Y\|N","pancLrgCfcd":"01","pancMdimCfcd":"","prodCd":"","pdnm":""}}` | JSON `payload.prodDisclosureList` |
| 다운로드 | GET | `/downLoadFiles.do` | `fileId`, `fileSeq`, `fileType=`, `fileGb=`, `viewType=` | `application/octet-stream` + PDF |

- `Content-Type: application/json; charset=UTF-8`, 성공 시 `header.RESULT_CODE == "0"`
- **암호화·CAPTCHA·WAF 없음**. 요청 본문은 평문 JSON입니다.
- TLS 는 `options.legacy_ssl: true` 필요(기존 설정 유지)
- 발견 경로: 화면 인라인 스크립트 `getProdList()` → `$.fn.ajaxCall(txCode, prod, cb)`,
  게이트웨이는 `/js/commonfnc.js` 의 `$.ajaxSetup({url: HONE_CHANNEL_URL + "/bomservice.do"})`
- 다운로드 함수는 `/js/commonfnc.js` 의 `fileDownLoad(fileId, fileSeq, fileType, fileGb, viewType)`

### 12.3 응답 필드 → 수집 항목

표 헤더: `보험종류 / 상품명 / 판매기간 / 상품설명서 / 상품요약서 / 사업방법서 / 약관`

| 수집 항목 | 필드 |
|---|---|
| 상품 분류 | `mclfNm` |
| 상품명 | `pdnm` |
| 판매기간 | `stDt` ~ `endt` (`"2021-08-01 00:00:00"` 형식, 앞 10자리 사용) |
| 약관 | `clauFileId` + `clauFileSeqn` |
| 사업방법서 | `bzMthdFileId` + `bzMthdFileSeqn` |
| 상품요약서 | `prodSmryFileId` + `prodSmryFileSeqn` |
| (상품설명서) | `prodMadcFileNm` + `prodMadcFileSeqn` — **수집 대상 3종이 아니므로 제외** |

`useYn=Y` 판매중 / `useYn=N` 판매중지. 두 화면은 이 값만 다르고 나머지 파라미터가 같습니다.

### 12.4 수집 규모 (실측)

| 구분 | 건수 | 약관 | 사업방법서 | 상품요약서 | 판매개시일 |
|---|---|---|---|---|---|
| 판매중 (`useYn=Y`) | 345 | 345 | 345 | 207 | 345 |
| 판매중지 (`useYn=N`) | 1,681 | 1,680 | 1,680 | 1,630 | 1,681 |

### 12.5 검증 결과

**Dry-run** (`--company AIG --dry-run --target-month 2026-07`, 44.4초)

```
[AIG] 판매중 -> 345건 / 판매중지 -> 1681건 / 상품 버전 2026건 수집
대상 버전 수 : 42 / 전체 수집 2026
문서 링크 수 : 125
누락 문서    : {"POLICY": 0, "SUMMARY": 1, "METHOD": 0}
MANUAL_REVIEW_REQUIRED : 0
```

**실제 다운로드** (상품 `무배당 AIG 든든한 간편암보험2604(305간편심사형)`)

| 문서 | HTTP | 크기 | 매직 | 원본 파일명 |
|---|---|---|---|---|
| 약관 | 200 | 6,905,681 B | `%PDF-` | `L0528-2.pdf` |
| 사업방법서 | 200 | 954,574 B | `%PDF-` | `1. 사방_..._26년7월 적용.pdf` |
| 상품요약서 | 200 | 540,207 B | `%PDF-` | `5. 상품요약서_..._26년7월 적용.pdf` |

`Content-Disposition` 의 `fileName` 은 퍼센트 인코딩된 UTF-8 이며
공통 파서 `filename_from_content_disposition()` 이 `re.I` + `unquote()` 로 그대로 처리합니다.

### 12.6 robots.txt

`https://www.aig.co.kr/robots.txt` → **404 (파일 없음). 수집 제한이 없습니다.**

### 12.7 알려진 제약

- **드라이런 미리보기의 확장자가 `.do` 로 표시됩니다.** 목록 API 가 파일명을 주지 않아
  `guess_extension()` 이 URL 경로(`/downLoadFiles.do`)에서 확장자를 뽑기 때문입니다.
  **실제 다운로드는 `Content-Disposition` 을 우선하므로 `.pdf` 로 저장됩니다**
  (`crawler/download_service.py:151-155`). 미리보기 표시만의 문제이며 저장 결과에는 영향이 없습니다.
  파일명을 임의로 지어내지 않기 위해 추정값을 넣지 않았습니다.
- 페이지네이션이 없어 한 번의 요청으로 전량이 옵니다(판매중지 1,681건 포함 321KB).

### 12.8 최종 분류

`DOCUMENT_NOT_PROVIDED` → **`IMPLEMENTED_HTTP`**

- Adapter: `crawler/adapters/aig.py`
- 등록: `crawler/adapters/__init__.py` (`"AIG": AIGAdapter`)
- config: `resolved_disclosure_url` 추가, `options.legacy_ssl: true` 유지
