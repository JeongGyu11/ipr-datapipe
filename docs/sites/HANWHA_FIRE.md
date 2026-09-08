# 한화손해보험 상품공시실 분석

## 1. 기본 정보

- 보험사 코드: `HANWHA_FIRE`
- 보험사명: 한화손해보험
- 보험 구분: 손해보험(non_life)
- config URL: https://www.hwgeneralins.com/notice/ir/product-main.do?mtoh=Y
- 실제 상품 목록 URL: 추가 수동 확인 필요
- 판매 중 상품 URL: 추가 수동 확인 필요
- 판매 중지 상품 URL: 추가 수동 확인 필요
- 확인일: 2026-07-31

## 2. 사이트 특징

- 렌더링 방식: JAVASCRIPT_RENDERED + **요청 파라미터 클라이언트 암호화**
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
| 세션 초기화 | GET | `/notice/ir/product-main.do?mtoh=Y` | - | HTML(200, 286KB) |
| 상품 목록 | - | 확인 불가 | - | - |
| 상품 상세 | - | 확인 불가 | - | - |
| 판매기간 | - | 확인 불가 | - | - |
| 첨부파일 목록 | - | 확인 불가 | - | - |
| 파일 다운로드 | - | 확인 불가 | - | - |
| (참고) 공통 XHR | POST | `/popup/global_popup_list.json`, `/my/bookmark/bookmark-list-data.json` | 본문이 `Dowz0Lw=…` 로 **암호화**되어 있음 | JSON |

## 4. 필수 요청 정보

- Referer: 설정함(config 의 url)
- Origin: 불필요
- User-Agent: config.crawler.user_agent
- Cookie: 불필요
- 세션: 불필요
- CSRF: 요청 본문이 클라이언트 측에서 암호화됨(`Dowz0Lw` 파라미터, `/notice/ir/product-main.do?evfw=…` 스크립트)
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

- Adapter 파일: 없음 (접근 제한으로 구현하지 않음)
- 등록 상태: `crawler/adapters/__init__.py`에 등록하지 않음
- 수집 상태: `ACCESS_RESTRICTED` — 전체 실행에서는 제외되며, 명시적으로 선택해도
  수집 시작 전에 검증 오류로 거부됩니다.
- Playwright 사용 여부: 필요하지만 접근 제한으로 실행하지 않음
- 선택한 구현 방식의 이유: 요청 본문이 암호화되어 httpx 로 재현 불가. 암호화 역산은 접근통제 우회 소지가 있어 시도하지 않음. 정식 경로는 Playwright 화면 조작이나 목록 조회 경로를 확정하지 못함
- 공통 유틸리티 사용 내역: 해당 없음

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
- 기타 문제: 초기 로드 시 상품 표가 렌더되지 않았습니다(`<table>` 0개)

## 9. 확인 근거

- 확인한 화면: 상품공시실 안내 화면
- 확인한 Network 요청: `POST /popup/global_popup_list.json` 등 — 본문 `Dowz0Lw=…` 암호화 확인
- 테스트 상품: 미검증
- 테스트 파일: 미검증
- 레거시 근거(2026-07-31 수동 조사): `C:/…/scratchpad/net.py` Playwright 네트워크 로깅 출력 — 현재 저장구조/리포지토리에 포함되지 않음

---

## 10. 후속 조사 (2026-08-04)

- **최종 분류**: `ACCESS_RESTRICTED` (기존 `ACCESS_DENIED` 와 동일 의미, 명칭 정정)
- **현재 실패 단계**: **목록 조회**
- **정확한 원인**
  - 화면 진입은 정상(200 / 286,047 B)이나 **상품 표가 초기 HTML 에 없습니다**(`<table>` 0개).
  - 관측된 자사 XHR 의 본문이 모두 `Dowz0Lw=…` 형태로 **클라이언트 암호화**되어 있습니다.
    암호화 스크립트는 `/notice/ir/product-main.do?evfw=…` 로 로드됩니다.
  - 상품 목록 요청 자체는 아직 관측하지 못했습니다(조회 조건 선택 이후 발생 추정).
- **확인한 요청**
  ```
  POST /popup/global_popup_list.json      body: Dowz0Lw=x2eJfTfVxlfCjBxdmdgyPdxHPygjrymvACyvPC7xjBxWfTf17zP6MCmvPs7…
  POST /my/bookmark/bookmark-list-data.json  body: limitNum=5&Dowz0Lw=0zxRMdeHrRgSfpgKQtgIwsg2FpWVousdxze4…
  ```
- **판단 근거**: 암호문을 직접 관측했습니다. 다만 **상품 목록 엔드포인트 자체를 아직 못 봤으므로**,
  "상품 목록도 반드시 암호화된다" 는 것은 확정 사실이 아니라 강한 추정입니다.
- **후속 작업**: 브라우저에서 상품공시 화면의 조회 조건을 선택하고 조회를 눌러 목록 요청을 먼저 기록.
  그 요청도 암호화되어 있으면 Playwright 기반 수집으로 전환해야 합니다.

---

## 11. 2026-08-04 구현 결과

- **최종 분류**: `ACCESS_RESTRICTED` (유지, 근거 보강)
- **근거 1 — robots.txt 상 공시실 경로 미허용(2026-08-04 확인)**
  - `Disallow: /` 이며 개별 `Allow` 가 **364건** 나열되어 있습니다.
  - 그 목록에 **상품공시실 경로(`/notice/ir/product-main.do` 등)는 포함되어 있지 않습니다.**
    (`/intro/ir/...`, `/product/catalog/product-info.do?insGdcd=...` 등 다른 경로만 허용)
- **근거 2 — 요청 본문 암호화**
  - 화면의 자사 XHR 본문이 모두 `Dowz0Lw=…` 로 클라이언트 암호화되어 있습니다.
    (`/notice/ir/product-main.do?evfw=…` 스크립트가 생성)
- **화면 구조 확인**: config URL 은 **'상품공시실 안내'** 화면입니다.
  정적 HTML 에서 `/notice/ir/` 하위 경로를 전수 추출한 결과 `product-main.do` **한 개뿐**이며
  하위 상품 목록 화면이 없습니다.
- **결론**: robots.txt 미허용 + 요청 암호화 두 가지가 겹쳐 자동 수집이 제한됩니다.
  **Adapter 를 구현하지 않았습니다.**
- **후속 조치**: 수집이 필요하면 한화손해보험과 별도 협의가 필요합니다.
