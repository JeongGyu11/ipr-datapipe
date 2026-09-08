# 삼성생명 상품공시실 분석

## 1. 기본 정보

- 보험사 코드: `SAMSUNG_LIFE`
- 보험사명: 삼성생명
- 보험 구분: 생명보험(life)
- config URL: https://www.samsunglife.com/individual/products/disclosure/sales/PDO-PRPRI010110M
- 실제 상품 목록 URL: POST `https://www.samsunglife.com/gw/api/display/board/content/list/full`
- 판매 중 상품 URL: 추가 수동 확인 필요
- 판매 중지 상품 URL: 추가 수동 확인 필요
- 확인일: 2026-07-31

## 2. 사이트 특징

- 렌더링 방식: JAVASCRIPT_RENDERED (초기 HTML 3.6KB 셸) + **요청 파라미터 클라이언트 암호화**
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
| 세션 초기화 | GET | `/individual/products/disclosure/sales/PDO-PRPRI010110M` | - | HTML(셸) |
| 상품 목록 | POST | `/gw/api/display/board/content/list/full` | `g=…&b=…` (Yettiesoft VestWeb 으로 암호화된 파라미터) | JSON |
| 상품 상세 | - | 확인 불가 | - | - |
| 판매기간 | - | 확인 불가 | - | - |
| 첨부파일 목록 | - | 확인 불가 | - | - |
| 파일 다운로드 | - | 확인 불가 | - | - |

## 4. 필수 요청 정보

- Referer: 설정함(config 의 url)
- Origin: 불필요
- User-Agent: config.crawler.user_agent
- Cookie: 불필요
- 세션: 암호화 키가 세션에 종속
- CSRF: 요청 본문 자체가 `g`/`b` 로 암호화됨(VestWeb `/gw/solution/yettiesoft/vestweb/vest/submit`)
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

- Adapter 파일: `crawler/adapters/samsung_life.py` (`SamsungLifeAdapter`)
- 등록: `crawler/adapters/__init__.py` (`"SAMSUNG_LIFE": SamsungLifeAdapter`)
- 수집 방식: HYBRID (Playwright 목록 응답 가로채기 + HTTP 파일 다운로드)
- Playwright 사용 여부: 사용 (암호화 요청은 역산하지 않고 정상 화면 이동만 수행)
- 선택한 구현 방식의 이유: 평문 응답을 Playwright에서 수집하고 인증 없는 정적 파일은 HTTP로 다운로드
- 공통 유틸리티 사용 내역: `utils.date_utils.parse_date` 사용; 목록 수집은
  `playwright.sync_api`, 파일 URL 조립은 사이트 전용 `_file_url()` 구현

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
- 기타 문제: 파라미터 암호화로 인해 `PLAYWRIGHT_REQUIRED` 로 분류

## 9. 확인 근거

- 확인한 화면: 개인 > 상품공시 > 판매상품
- 확인한 Network 요청: `POST /gw/api/display/board/content/list/full` (본문 `g=…&b=…`)
- 테스트 상품: 미검증
- 테스트 파일: 미검증
- 레거시 근거(2026-07-31 수동 조사): `C:/…/scratchpad/net.py` Playwright 네트워크 로깅 출력 — 현재 저장구조/리포지토리에 포함되지 않음

---

## 10. 후속 조사 (2026-08-04)

- **최종 분류**: `ACCESS_RESTRICTED` (기존 `ACCESS_DENIED` 와 동일 의미, 명칭 정정)
- **현재 실패 단계**: **목록 조회**
- **정확한 원인**: 상품 목록 API 의 **요청 본문이 클라이언트에서 암호화**됩니다.
  차단(403)이나 CAPTCHA·로그인 요구가 아니라, 서버가 암호화된 파라미터만 해석합니다.
- **확인한 요청**
  ```
  POST https://www.samsunglife.com/gw/api/display/board/content/list/full
  Content-Type: application/x-www-form-urlencoded;charset=UTF-8
  body: g=aDYYSEaDIVGiOaWbqK3B0NxIyDHx3bFHNV6efdwhat2v…&b=NWJiNzJjMWI2ODViNDRhY2FmNDc0OGU5…
  ```
  암호화 모듈: Yettiesoft VestWeb (`/gw/solution/yettiesoft/vestweb/vest/submit`)
- **평문 재현 시도 결과(2026-08-04 실측)** — 3가지 모두 동일 오류
  | 본문 | 응답 |
  |---|---|
  | (빈 본문) | 200 `{"code":"9999","message":"서비스 처리중 오류가 발생했습니다…","response":{"code":"9999","message":"UNKNOWN ERROR"}}` |
  | `g=&b=` | 동일 |
  | `{"boardId":""}` | 동일 |
- **판단 근거**: 요청 본문 암호문을 직접 관측했고, 평문 호출이 일관되게 오류를 반환하는 것까지 확인했습니다.
  암호화 로직 역산은 접근통제 우회에 해당할 소지가 있어 **시도하지 않았습니다.**
- **후속 작업**: 기존 메리츠화재와 같은 방식으로 Playwright 에서 화면을 정상 조작하고
  `expect_download` 로 파일을 받는 수집기를 설계해야 합니다.

---

## 11. 2026-08-04 구현 결과

- **최종 분류**: `ACCESS_RESTRICTED` → **`IMPLEMENTED_HYBRID`**
- **핵심 발견**: 목록 API 의 **요청은 암호화**되지만 **응답은 평문 JSON** 이고,
  문서 파일은 **인증 없는 정적 경로**로 제공됩니다.
  → 암호화를 역산하지 않고, Playwright 로 화면의 페이지 이동만 수행하며 **응답을 가로채** 목록을 얻고
    파일은 기존 `HttpClient` 로 내려받는 **하이브리드** 방식으로 구현했습니다.
- **엔드포인트**
  | 구분 | 메서드 | 엔드포인트 | 비고 |
  |---|---|---|---|
  | 상품 목록 | POST | `/gw/api/product/disclosure/product/prdt/salesAllPrdtList` | 요청 `g=…&b=…` 암호화 / 응답 평문 JSON |
  | 문서 뷰어 | GET | `https://pcms.samsunglife.com/partnerpage/CustomerPage_Unit.jsp?goodsCode&docType&saleDate&pageGubun=prdt` | 뷰어 HTML |
  | **실제 파일** | GET | `https://pcms.samsunglife.com/uploadDir/doc/{YYYY}/{MMDD}/{goodsCode}/{docType}/{filename}.pdf` | 인증 불필요 |
- **응답 필드**: `goodsCode, goodsName, fromdate, todate, lCode(판매중/판매중지), gubun, filename1~3, totalRows=6565, pageSize=10, pageNo`
- **docType 매핑(팝업 URL 실측)**: `filename1`→`201` 상품요약서 / `filename2`→`401` 사업방법서 / `filename3`→`301` 보험약관
- **경로 규칙**: `{YYYY}/{MMDD}` 는 `filename`(epoch ms)의 업로드 일자. 실측 검증 완료.
- **검증(2026-08-04)**: 3페이지 표본 → 30버전 / 문서 53건.
  보험약관 1,028,052 B · 사업방법서 163,221 B 모두 `%PDF-1` 200.
  상품요약서는 표본 3페이지(오래된 판매중지 상품)에 없어 미검증.
- **규모**: 전체 6,565건 / 657페이지. `options.max_pages` 로 상한 지정 가능(사용 시 `coverage_capped`).
- **Adapter**: `crawler/adapters/samsung_life.py`
