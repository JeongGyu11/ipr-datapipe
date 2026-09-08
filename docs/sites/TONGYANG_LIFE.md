# 동양생명 상품공시실 분석

## 1. 기본 정보

- 보험사 코드: `TONGYANG_LIFE`
- 보험사명: 동양생명
- 보험 구분: 생명보험(life)
- config URL: https://pbano.myangel.co.kr/
- 실제 상품 목록 URL: https://pbano.myangel.co.kr/notice/product/WE_PA_AP_01_00_00.jsp (resolved_disclosure_url)
- 판매 중 상품 URL: 추가 수동 확인 필요
- 판매 중지 상품 URL: 추가 수동 확인 필요
- 확인일: 2026-07-31

## 2. 사이트 특징

- 렌더링 방식: STATIC_HTML(초기 HTML 에 상품 표 없음)
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
| 세션 초기화 | GET | `/` | - | HTML |
| 상품 목록 | - | `/notice/product/WE_PA_AP_01_00_00.jsp` 진입은 확인(200/35KB)했으나 상품 표는 렌더되지 않음 | - | HTML |
| 상품 상세 | - | 확인 불가 | - | - |
| 판매기간 | - | 확인 불가 | - | - |
| 첨부파일 목록 | - | 확인 불가 | - | - |
| 파일 다운로드 | POST | `/process/CO_ComDownload` | `_biz_op_code=FDL`,`FILE_GRP_ID`,`FILE_PATH`,`FILE_NAME`,`USER_FILE_NM` | 파일 |

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
- JavaScript 함수 여부: `Filedownload('_F','filedir/notice/','파일명.pdf','표시명.pdf')`
- 파일명 획득 방법: 확인 불가
- 한 상품에 여러 문서 존재 여부: 확인 불가

## 6. 구현 방식

- Adapter 파일: `crawler/adapters/tongyang_life.py` (`TongyangLifeAdapter`)
- 등록: `crawler/adapters/__init__.py` (`"TONGYANG_LIFE": TongyangLifeAdapter`)
- 수집 방식: FORM_POST (판매상품·판매중지 페이지 POST)
- Playwright 사용 여부: 사용 안 함
- 선택한 구현 방식의 이유: 메뉴 버튼의 실제 POST 경로와 폼 파라미터를 재현
- 공통 유틸리티 사용 내역: `crawler/adapters/common.py`의 `clean`, `js_call_args`,
  `soup`, `table_rows` 헬퍼 사용

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
- 기타 문제: config URL 은 공시실 진입 화면이며 보험상품공시 메뉴는 `javascript:void(0)` 하위 메뉴. `resolved_disclosure_url` 로 확인한 화면을 기록했으나 이 화면에도 상품 표가 없어 하위 조회 화면을 확정하지 못함. 다운로드 폼(`CO_ComDownload`) 규격만 확인

## 9. 확인 근거

- 확인한 화면: 공시실 메인 / 보험상품공시 안내 화면
- 확인한 Network 요청: Playwright 네트워크 로깅 — 상품 관련 XHR 미관측
- 테스트 상품: 미검증
- 테스트 파일: 미검증
- 레거시 근거(2026-07-31 수동 조사): `C:/…/scratchpad/net.py` Playwright 네트워크 로깅 출력 — 현재 저장구조/리포지토리에 포함되지 않음

---

## 10. 후속 조사 (2026-08-04)

- **최종 분류**: `HTTP_IMPLEMENTABLE_WITH_FIX` → **구현 완료(IMPLEMENTED)**
- **막혀 있던 지점**: 공시실 탐색. '보험상품공시' 메뉴가 `javascript:void(0)` 라 하위 화면 URL 을
  찾지 못했습니다. 실제 경로는 메뉴 **버튼의 `value` 속성**에 들어 있었습니다.
- **확정한 경로**
  | 구분 | 메서드 | 엔드포인트 |
  |---|---|---|
  | 판매상품 목록 | POST | `/paging/WE_AC_WEPAAP020100L` |
  | 판매중지상품 목록 | POST | `/paging/WE_AC_WEPAAP020201L` |
  | 파일 다운로드 | POST | `/process/CO_ComDownload` `{_biz_op_code=FDL, FILE_GRP_ID=<토큰>}` |
- **페이지네이션**: 화면의 `PP_Query('mainform','dw_99',N)`(`/js/frameplus/pageprocess.js`)이
  `_biz_op_code=_Q`, `_paging_action=PP`, `_paging_dw_name=dw_99`, `_paging_page_idx=N` 을 세팅합니다.
  단순히 `pagenum=2` 만 보내면 **0행**이 돌아옵니다(실측).
- **표 구성**: 번호 / 판매채널 / 구분 / 상품명 / 판매기간(시작) / 판매기간(종료) / 상품요약서 / 사업방법서 / 보험약관
- **문서 링크**: `javascript:MasFiledownload('_N','<FILE_GRP_ID>')` (`/js/common.js`)
- **검증(2026-08-04)**: 판매 56건(6페이지) 순회 확인.
  약관 29,530,578 B, 사업방법서 296,265 B, 상품요약서 4,137,265 B 모두 `%PDF-` 200.
- **Adapter**: `crawler/adapters/tongyang_life.py`
