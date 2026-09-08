# 신한라이프 상품공시실 분석

## 1. 기본 정보

- 보험사 코드: `SHINHAN_LIFE`
- 보험사명: 신한라이프
- 보험 구분: 생명보험(life)
- config URL: https://www.shinhanlife.co.kr/hp/cdhi0010.do
- 실제 상품 목록 URL: 추가 수동 확인 필요
- 판매 중 상품 URL: 추가 수동 확인 필요
- 판매 중지 상품 URL: 추가 수동 확인 필요
- 확인일: 2026-07-31

## 2. 사이트 특징

- 렌더링 방식: JAVASCRIPT_RENDERED (`*.pwkjson` XHR 기반)
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
| 세션 초기화 | GET | `/hp/cdhi0010.do` | - | HTML |
| 상품 목록 | - | 확인 불가 | - | - |
| 상품 상세 | - | 확인 불가 | - | - |
| 판매기간 | - | 확인 불가 | - | - |
| 첨부파일 목록 | - | 확인 불가 | - | - |
| 파일 다운로드 | - | 확인 불가 | - | - |
| (참고) 메뉴 조회 | POST | `/co/nvi/getMenuNavi.pwkjson` | JSON `{elData:{dpMenuId,channelDiv,scrnId}, userHeader:{scrnId}}` | JSON |

## 4. 필수 요청 정보

- Referer: 설정함(config 의 url)
- Origin: 불필요
- User-Agent: config.crawler.user_agent
- Cookie: 불필요
- 세션: 불필요
- CSRF: 없음
- 인코딩: UTF-8
- 기타 헤더: 전문 규격 `{elData:{…}, userHeader:{scrnId, appliDtptDutjCd}}`

## 5. 문서 링크 구조

- 약관: 추가 수동 확인 필요
- 사업방법서: 추가 수동 확인 필요
- 상품요약서: 추가 수동 확인 필요
- 상대 URL 여부: 확인 불가
- JavaScript 함수 여부: 확인 불가
- 파일명 획득 방법: 확인 불가
- 한 상품에 여러 문서 존재 여부: 확인 불가

## 6. 구현 방식

- Adapter 파일: `crawler/adapters/shinhan_life.py` (`ShinhanLifeAdapter`)
- 등록: `crawler/adapters/__init__.py` (`"SHINHAN_LIFE": ShinhanLifeAdapter`)
- 수집 방식: JSON_API (필수 헤더를 포함한 목록·상세 API)
- Playwright 사용 여부: 사용 안 함
- 선택한 구현 방식의 이유: 화면의 JSON API 요청과 필수 헤더를 재현
- 공통 유틸리티 사용 내역: `BaseInsurerAdapter.client`(HttpClient),
  `utils.date_utils.parse_date`, `utils.file_utils.filename_from_content_disposition` 사용

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
- 기타 문제: config URL(`cdhi0010.do`)은 공시실 메인 화면이며 상품 목록 표가 없습니다(초기 HTML `<table>` 0개). 상품공시 목록 화면의 `scrnId` 를 확정하지 못함

## 9. 확인 근거

- 확인한 화면: 신한라이프 공시실 메인
- 확인한 Network 요청: `POST /co/dag/dutjAsrtGrouDetList.pwkjson`, `POST /co/nvi/getMenuNavi.pwkjson`
- 테스트 상품: 미검증
- 테스트 파일: 미검증
- 레거시 근거(2026-07-31 수동 조사): `C:/…/scratchpad/net.py` Playwright 네트워크 로깅 출력 — 현재 저장구조/리포지토리에 포함되지 않음

---

## 10. 후속 조사 (2026-08-04)

- **최종 분류**: `HTTP_IMPLEMENTABLE_WITH_FIX` → **구현 완료(IMPLEMENTED)**
- **막혀 있던 지점 3가지**
  1. config URL(`cdhi0010.do`)이 공시실 메인이라 목록 화면을 못 찾음
  2. 목록 API 를 찾아도 **필수 헤더가 없으면 실패**
  3. 문서 경로를 그대로 GET 하면 404
- **확정한 경로**
  | 구분 | 메서드 | 엔드포인트 |
  |---|---|---|
  | 판매중 화면 | GET | `/hp/cdhi0030.do` |
  | 판매중지 화면 | GET | `/hp/cdhi0040t01.do` |
  | 상품 목록 | POST | `/co/wcms/nodeInfoListPage.pwkjson` |
  | 파일 다운로드 | POST | `/bizxpress{경로에서 `/repo/DigitalPlattform` 제거}` |
- **필수 헤더**: `x-ajax-call: true`, `proworks-body: Y` (없으면 `resCode=ERROR.SYS.002`, 실측)
- **요청 본문**
  ```json
  {"elData":{"catId":"M160991914330045272","pageSize":100,"pageIndex":1,
             "method":"selectListGoods","meta06":"TRUE","scrnId":"cdhi0030"},
   "userHeader":{"scrnId":"cdhi0030","appliDtptDutjCd":"DH"}}
  ```
  `meta06`: `TRUE`=판매중 / `FALSE`=판매중지 (catId 는 동일)
- **응답 필드**: meta02 판매채널 · meta03 구분 · meta04 상품코드 · meta05 상품명 ·
  meta07 판매개시일시 · meta08 판매종료일시 · meta09 상품요약서 · meta10 사업방법서 · meta11 약관
- **규모**: 판매중 `listCount = 112`
- **검증(2026-08-04)**: 약관 4,140,783 B, 사업방법서 95,295 B, 상품요약서 160,305 B 모두 `%PDF-` 200.
- **Adapter**: `crawler/adapters/shinhan_life.py`
