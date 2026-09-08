# ABL생명 상품공시실 분석

## 1. 기본 정보

- 보험사 코드: `ABL_LIFE`
- 보험사명: ABL생명
- 보험 구분: 생명보험(life)
- config URL: https://abllife.co.kr/st/custDesk/cspCntr/fncLvngInfo/fncLvngInfo3?page=index
- 실제 상품 목록 URL: 추가 수동 확인 필요
- 판매 중 상품 URL: 추가 수동 확인 필요
- 판매 중지 상품 URL: 추가 수동 확인 필요
- 확인일: 2026-07-31

## 2. 사이트 특징

- 렌더링 방식: JAVASCRIPT_RENDERED (상품 목록이 초기 HTML 에 없음 — `<table>` 0개)
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
| 세션 초기화 | GET | `/st/custDesk/cspCntr/fncLvngInfo/fncLvngInfo3?page=index` | - | HTML(200, 139KB) |
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

- Adapter 파일: `crawler/adapters/abl_life.py` (`ABLLifeAdapter`)
- 등록: `crawler/adapters/__init__.py` (`"ABL_LIFE": ABLLifeAdapter`)
- 수집 방식: STATIC_HTML (허브 JS 진입 후 판매중·판매중지 목록과 상세 HTML 파싱)
- Playwright 사용 여부: 사용 안 함
- 선택한 구현 방식의 이유: 공시실 목록·상세 화면의 서버 렌더링 HTML과 문서 링크를 직접 파싱
- 공통 유틸리티 사용 내역: `crawler/adapters/common.py`의 `absolute`, `clean`,
  `parse_period`, `soup`, `table_rows` 사용

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
- 기타 문제: 페이지 로드시 관측된 자사 XHR 은 `/cms/prdt/ItemInformation01.json`, `/api/WN/popword`, `/common/sigungu` 뿐이며 상품공시 목록 데이터가 아님. 목록은 사용자가 분류를 선택해야 조회되는 것으로 보이나 클릭 경로를 확정하지 못함

## 9. 확인 근거

- 확인한 화면: 상품 공시실 화면(제목: `상품 공시실 < ABL`)
- 확인한 Network 요청: Playwright 네트워크 로깅 — 위 3개 XHR 만 관측됨
- 테스트 상품: 미검증
- 테스트 파일: 미검증
- 레거시 근거(2026-07-31 수동 조사): `C:/…/scratchpad/net.py` Playwright 네트워크 로깅 출력 — 현재 저장구조/리포지토리에 포함되지 않음

---

## 10. 후속 조사 (2026-08-04)

- **최종 분류**: `HTTP_IMPLEMENTABLE_WITH_FIX` → **구현 완료(IMPLEMENTED)**
- **막혀 있던 지점**: 공시실 탐색. config URL 이 상품 목록이 아니라 공시실 허브 화면이었습니다.
- **확정한 경로**
  | 구분 | 메서드 | 엔드포인트 |
  |---|---|---|
  | 판매상품 목록 | GET | `/st/pban/prdtPban/whlPrdt/whlPrdt1/whlPrdt1{1..8}?page=index` |
  | 판매중지 목록 | GET | `/st/pban/prdtPban/whlPrdt/whlPrdt2/whlPrdt2{1..8}?page=index` |
  | 상품 상세 | GET | `/st/pban/prdtPban/whlPrdt?page={id}` (표: 판매기간/사업방법서/상품요약서/약관) |
  | 파일 다운로드 | GET | `/cms/pban/prdtPban/whlPrdt/__icsFiles/afieldfile/...pdf` (정적) |
- **카테고리(끝자리)**: 1 종신 · 2 변액 · 3 연금 · 4 보장 · 5 저축 · 6 단체보험 · 7 방카슈랑스 · 8 제도성특약
- **주의**: 목록이 `<table>` 이 아니라 `ul > li.fss_box > a[href*="whlPrdt?page="]` 입니다.
  표만 찾으면 "상품 목록 없음" 으로 잘못 판단하게 됩니다.
- **검증(2026-08-04)**: 상품 6건 표본 → 28버전 / 62문서.
  약관 13,461,120 B `%PDF-1.6`, 사업방법서 115,212 B, 상품요약서 395,540 B 모두 200 성공.
- **Adapter**: `crawler/adapters/abl_life.py`
