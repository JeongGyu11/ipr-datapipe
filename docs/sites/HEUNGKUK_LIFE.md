# 흥국생명 상품공시실 분석

## 1. 기본 정보

- 보험사 코드: `HEUNGKUK_LIFE`
- 보험사명: 흥국생명
- 보험 구분: 생명보험(life)
- config URL: https://www.heungkuklife.co.kr/front/public/saleProduct.do?searchFlgSale=Y
- 실제 상품 목록 URL: 추가 수동 확인 필요
- 판매 중 상품 URL: `?searchFlgSale=Y`
- 판매 중지 상품 URL: `searchFlgSale` 다른 값으로 추정되나 미확정
- 확인일: 2026-07-31

## 2. 사이트 특징

- 렌더링 방식: STATIC_HTML + 폼 POST(`frmPage`)
- 상품 카테고리: 확인 불가
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
| 세션 초기화 | GET | `/front/public/saleProduct.do?searchFlgSale=Y` | - | HTML(EUC-KR, 200) |
| 상품 목록 | POST | `/front/public/saleProduct.do` (폼 `frmPage`) | 확인 불가 | HTML |
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

- 약관: 표 열 `상품약관` 존재
- 사업방법서: 표 열 `사업방법서` 존재
- 상품요약서: 표 열 `상품요약서` 존재
- 상대 URL 여부: 확인 불가
- JavaScript 함수 여부: 확인 불가
- 파일명 획득 방법: 확인 불가
- 한 상품에 여러 문서 존재 여부: 확인 불가

## 6. 구현 방식

- Adapter 파일: `crawler/adapters/heungkuk_life.py` (`HeungkukLifeAdapter`)
- 등록: `crawler/adapters/__init__.py` (`"HEUNGKUK_LIFE": HeungkukLifeAdapter`)
- 수집 방식: FORM_POST (판매중·판매중지 폼 POST)
- Playwright 사용 여부: 사용 안 함
- 선택한 구현 방식의 이유: 화면의 판매상태·상품분류 폼 요청을 그대로 재현
- 공통 유틸리티 사용 내역: `crawler/adapters/common.py`의 `clean`, `decode_body`,
  `parse_period` 사용

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
- 기타 문제: 초기 GET 응답의 상품 표는 `tbody` 가 비어 있어(0행) 조회 조건 POST 가 필요합니다. 폼 `frmPage` 의 필수 파라미터를 확정하지 못했습니다. nProtect(`nppfs-1.9.0.js`) 스크립트가 로드됩니다

## 9. 확인 근거

- 확인한 화면: 공시실 > 상품공시 > 판매상품
- 확인한 Network 요청: `POST /nProtect/jsps/nppfs.key.jsp` 외 상품 관련 XHR 미관측
- 테스트 상품: 미검증
- 테스트 파일: 미검증
- 레거시 근거(2026-07-31 수동 조사): `C:/…/scratchpad/net.py` Playwright 네트워크 로깅 출력 — 현재 저장구조/리포지토리에 포함되지 않음

---

## 10. 후속 조사 (2026-08-04)

- **최종 분류**: `HTTP_IMPLEMENTABLE` → **구현 완료(IMPLEMENTED)**
- **막혀 있던 지점**: 목록 조회. 초기 GET 응답의 표가 0행이라 "조회 폼 파라미터 미확인" 으로 두었으나,
  화면의 `doSearch()` → `doSearchAjax()` 가 **별도 엔드포인트**를 호출하는 구조였습니다.
- **확정한 경로**
  | 구분 | 메서드 | 엔드포인트 |
  |---|---|---|
  | 상품명 목록 / 상품 상세 | POST | `/front/public/saleProductAjax.do` |
  | 파일 다운로드 | POST | `/servlet/DownLoadEnc.do` `{encValue=<암호화 토큰>, + 조회 폼 필드}` |
- **파라미터**
  - `searchFlgSale` : `Y` 판매 / `N` 판매중지
  - `searchCdPublicPrtType1` : `I101` 개인 / `I102` 단체 / `I103` 방카슈랑스
  - `searchCdPublicPrtType2` : `I201` 연금 · `I202` 보장성 · `I203` 생사혼합 · `I204` 저축 ·
    `I205` 개인연금 · `I206` 교육 · `I207` 양로 · `I208` 변액 · `I209` 기타
  - `searchCdPublicPrtType3` : 상품명(선택 시 상세 조회). **`escape(encodeURIComponent(x))`** 로 이중 인코딩 필요
- **응답 형식**: JSON/HTML 이 아니라 **커스텀 구분자 텍스트(EUC-KR)**
  `블록0 %||% 블록1 %||% 블록2`, 행 구분 `%|%`, 열 구분 `%,%`
  - 블록0 = 상품명 목록
  - 블록2 = 판매개시일 · 판매종료일 · 보장명 · 순번 · **약관토큰 · 약관파일명 · 방법서토큰 · 방법서파일명 · 요약서토큰 · 요약서파일명**
- **규모(실측)**: 판매 개인 29 · 단체 7 · 방카 4 / 판매중지 217(카테고리 무관 동일)
- **검증(2026-08-04)**: 상품 4건 표본 → 18버전 / 52문서.
  약관 2,092,006 B, 사업방법서 488,055 B, 상품요약서 105,437 B 모두 `%PDF-` 200.
- **Adapter**: `crawler/adapters/heungkuk_life.py`
