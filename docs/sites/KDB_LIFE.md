# KDB생명 상품공시실 분석

## 1. 기본 정보

- 보험사 코드: `KDB_LIFE`
- 보험사명: KDB생명
- 보험 구분: 생명보험(life)
- config URL: https://www.kdblife.com/ajax.do?pcmode=1&scrId=HDLMA002M02P
- 실제 상품 목록 URL: POST `https://www.kdblife.com/ajax.do?scrId=HDLMA002M02P&isJson=1`
- 판매 중 상품 URL: 추가 수동 확인 필요
- 판매 중지 상품 URL: 추가 수동 확인 필요
- 확인일: 2026-07-31

## 2. 사이트 특징

- 렌더링 방식: JSON/AJAX(응답은 EUC-KR HTML 조각)
- 상품 카테고리: `categoryGroup` + `selectCategoryName` (예: `FP/FC/AM보험`) — 전체 목록 미확정
- 판매채널 구분: 확인 불가
- 검색 조건: 확인 불가
- 날짜 제공 방식: 표 머리글에 `판매기간` 존재
- 페이지네이션 방식: 확인 불가
- 상품 버전 표시 방식: 확인 불가
- 이전 판매기간 제공 여부: 확인 불가
- 팝업 또는 모달 사용 여부: 확인 불가

## 3. 실제 엔드포인트

| 구분 | 메서드 | 엔드포인트 | 주요 파라미터 | 응답 형식 |
|---|---|---|---|---|
| 세션 초기화 | GET | `/ajax.do?pcmode=1&scrId=HDLMA002M02P` | - | HTML(EUC-KR) |
| 상품 목록 | POST | `/ajax.do?scrId=HDLMA002M02P&isJson=1` | `paramJson`(이중 URL 인코딩된 JSON: `{pcmode, scrId, reqInfo:{category, searchVal, categoryGroup, selectCategoryName}}`) | HTML 조각(EUC-KR) |
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
- 인코딩: EUC-KR
- 기타 헤더: 없음

## 5. 문서 링크 구조

- 약관: 표 열 `약관` 존재
- 사업방법서: 표 열 `사업방법서` 존재
- 상품요약서: 표 열 `상품요약서` 존재
- 상대 URL 여부: 확인 불가
- JavaScript 함수 여부: 확인 불가
- 파일명 획득 방법: 확인 불가
- 한 상품에 여러 문서 존재 여부: 확인 불가

## 6. 구현 방식

- Adapter 파일: `crawler/adapters/kdb_life.py` (`KDBLifeAdapter`)
- 등록: `crawler/adapters/__init__.py` (`"KDB_LIFE": KDBLifeAdapter`)
- 수집 방식: JSON_API (판매상품·판매중지 AJAX)
- Playwright 사용 여부: 사용 안 함
- 선택한 구현 방식의 이유: 화면의 JSON 응답과 문서 필드를 확인해 AJAX를 재현
- 공통 유틸리티 사용 내역: `crawler/adapters/common.py`의 `absolute`, `decode_body`,
  `soup` 헬퍼와 `utils.date_utils.parse_date` 사용

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
- 기타 문제: 목록 엔드포인트와 파라미터 형식은 확인했으나 `categoryGroup`/`category` 전체 코드값과 파일 다운로드 엔드포인트를 확정하지 못함

## 9. 확인 근거

- 확인한 화면: 상품공시실 화면(표 머리글 `상품명 / 보험료설계(상품설명) / 판매기간 / 약관 / 사업방법서 / 상품요약서`)
- 확인한 Network 요청: `POST /ajax.do?scrId=HDLMA002M02P&isJson=1` (paramJson 이중 인코딩)
- 테스트 상품: 미검증
- 테스트 파일: 미검증
- 레거시 근거(2026-07-31 수동 조사): `C:/…/scratchpad/net.py` Playwright 네트워크 로깅 출력 — 현재 저장구조/리포지토리에 포함되지 않음

---

## 10. 후속 조사 (2026-08-04)

- **최종 분류**: `HTTP_IMPLEMENTABLE_WITH_FIX` → **구현 완료(IMPLEMENTED)**
- **막혀 있던 지점**: 상세·문서 경로. 목록 API 는 알고 있었으나 **응답이 JSON 이라는 점**과
  판매중지 화면 `scrId`, 파일 필드의 실제 의미를 확인하지 못한 상태였습니다.
- **확정한 경로**
  | 구분 | 메서드 | 엔드포인트 | 비고 |
  |---|---|---|---|
  | 판매상품 목록 | POST | `/ajax.do?scrId=HDLMA002M02P&isJson=1` | body `paramJson=<이중 URL 인코딩 JSON>` |
  | 판매중지 목록 | POST | `/ajax.do?scrId=HDLMA002M03P&isJson=1` | 〃 |
  | 파일 다운로드 | GET | `/nKumhoFiles/data_pdf/...pdf` | 정적 |
- **응답 구조**: 앞에 공백/개행이 많은 **JSON**. `resultList` 의 `GP='A'` 는 상품 머리행,
  `GP='B'` 는 판매기간 행입니다(판매중지 화면은 `GP` 없음).
- **필드 의미(주의)**: `PRODUCT_SUMMARY` = **사업방법서**, `PRODUCT_GUIDE` = **상품요약서**,
  `AGREEMENT` = 약관. 약관은 PDF 직접 경로이거나 `...html^720^540^1` 팝업이며,
  팝업 HTML 안에 주계약·제도성 특약 약관 PDF 가 여러 개 들어 있습니다(실측 34건 중 31건이 팝업).
- **카테고리 그룹**: 2 FC/GA보험 · 9 KDB다이렉트보험 · 3 방카슈랑스보험 · 4 단체보험 · 8 퇴직연금
  (판매중지 화면에서만 그룹별로 건수가 달라짐: 218 / 20 / 40 / 21 / 11)
- **검증(2026-08-04)**: 약관 2,334,697 B, 사업방법서 155,609 B, 상품요약서 731,375 B 모두 `%PDF-` 200.
- **Adapter**: `crawler/adapters/kdb_life.py`
- **판매중지 화면의 제한(중요)**: `HDLMA002M03P` 응답은 상품명·카테고리만 반환하고
  **판매기간과 문서 경로가 없습니다**(실측: 218행 전부 `SALE_START_DATE=null`).
  상품별 상세 요청을 아직 확정하지 못해, Adapter 는 날짜도 문서도 없는 행을 건너뛰고
  `stats.stop_sale_detail_missing` 에 건수만 남깁니다.
  → 후속 작업: 판매중지 화면에서 상품을 클릭했을 때 발생하는 상세 요청 1건 기록 필요.
- **수정 후 dry-run(2026-08-04)**: 수집 170건 → 2026-07 대상 50건 / 문서 3,575건 /
  `MANUAL_REVIEW_REQUIRED` 0건.
