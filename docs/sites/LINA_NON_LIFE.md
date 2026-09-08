# 라이나손해보험 상품공시실 분석

## 1. 기본 정보

- 보험사 코드: `LINA_NON_LIFE`
- 보험사명: 라이나손해보험
- 보험 구분: 손해보험(non_life)
- config URL: https://www.chubb.com/kr-kr/disclosure/product-disclosure.html
- 실제 상품 목록 URL: 추가 수동 확인 필요
- 판매 중 상품 URL: 추가 수동 확인 필요
- 판매 중지 상품 URL: 추가 수동 확인 필요
- 확인일: 2026-07-31

## 2. 사이트 특징

- 렌더링 방식: STATIC_HTML(AEM) — 표 없음(`<table>` 0개)
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
| 세션 초기화 | GET | `/kr-kr/disclosure/product-disclosure.html` | - | HTML(200, 130KB) |
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

- Adapter 파일: `crawler/adapters/lina_non_life.py` (`LinaNonLifeAdapter`)
- 등록: `crawler/adapters/__init__.py` (`"LINA_NON_LIFE": LinaNonLifeAdapter`)
- 수집 방식: STATIC_HTML (ACE 공시실 HTML 목록)
- Playwright 사용 여부: 사용 안 함
- 선택한 구현 방식의 이유: 별도 ACE 공시실의 서버 렌더링 목록과 문서 링크를 파싱
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
- 기타 문제: Adobe AEM 기반 안내 페이지로 상품 표가 없습니다. 하위 상품공시 목록 화면 URL 을 확정하지 못했습니다

## 9. 확인 근거

- 확인한 화면: Chubb(라이나손해보험) 보험상품 공시 안내 페이지
- 확인한 Network 요청: 상품 관련 XHR 미관측
- 테스트 상품: 미검증
- 테스트 파일: 미검증
- 레거시 근거(2026-07-31 수동 조사): `C:/…/scratchpad/net.py` Playwright 네트워크 로깅 출력 — 현재 저장구조/리포지토리에 포함되지 않음

---

## 10. 후속 조사 (2026-08-04)

- **최종 분류**: `HTTP_IMPLEMENTABLE_WITH_FIX` → **구현 완료(IMPLEMENTED)**
- **막혀 있던 지점**: 공시실 탐색. config URL(chubb.com AEM)은 **공시 안내 페이지**라 상품 표가 없습니다.
  실제 목록은 `/kr-kr/disclosure/product.html` 의 '판매 중 상품 목록 바로가기' 가 가리키는
  **별도 도메인** 이었습니다.
- **확정한 경로**
  | 구분 | 메서드 | 엔드포인트 |
  |---|---|---|
  | 판매중 목록 | GET | `https://ec.aceinsurance.co.kr/jsp/acelimited/notice/productNoticeV2.jsp?status=Y` |
  | 판매중지 목록 | GET | 같은 URL `status=N` |
  | 파일 다운로드 | GET | `/jsp/file/WebProductFiledown.jsp?fileType=1\|2\|3&fileName=...` |
- **fileType**: `1` 사업방법서 / `2` 약관 / `3` 상품요약서
- **표 구성**: 상품명(rowspan) / 판매기간 / 사업방법서 / 상품약관 / 상품요약서.
  카테고리별로 표가 여러 개(판매 10개 표 · 판매중지 11개 표)이며 페이지네이션은 없습니다.
- **규모(실측)**: 판매 610,757 B(표 10개, 최대 322행) / 판매중지 2,531,527 B(표 11개, 최대 1,239행)
- **검증(2026-08-04)**: 약관 18,605,422 B, 사업방법서 70,718 B, 상품요약서 182,769 B 모두 `%PDF-` 200.
- **Adapter**: `crawler/adapters/lina_non_life.py`
