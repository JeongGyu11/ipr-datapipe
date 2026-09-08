# 메트라이프생명 상품공시실 분석

## 1. 기본 정보

- 보험사 코드: `METLIFE`
- 보험사명: 메트라이프생명
- 보험 구분: 생명보험(life)
- config URL: https://brand.metlife.co.kr/pn/mcvrgProd/retrieveMcvrgProdMain.do
- 실제 상품 목록 URL: 같음
- 판매 중 상품 URL: 같은 화면(판매기간 종료일이 없는 행)
- 판매 중지 상품 URL: **별도 화면 미제공** — 판매중지는 각 상품의 '이전 판매기간' 행으로만 제공
- 확인일: 2026-07-31

## 2. 사이트 특징

- 렌더링 방식: STATIC_HTML
- 상품 카테고리: 보장 / 변액 / 연금 (표의 `구분` 열)
- 판매채널 구분: 구분 없음
- 검색 조건: 상품명(`searchKeyword`)
- 날짜 제공 방식: `판매기간` 열 `YYYY.MM.DD ~ [YYYY.MM.DD]`
- 페이지네이션 방식: 없음(1회 응답 747행)
- 상품 버전 표시 방식: 판매기간 행 단위(주보험 57개 → 690버전)
- 이전 판매기간 제공 여부: **제공** — '이전 판매기간 펼치기' 행이 HTML 에 이미 포함
- 팝업 또는 모달 사용 여부: 예(특약보기 팝업)

## 3. 실제 엔드포인트

| 구분 | 메서드 | 엔드포인트 | 주요 파라미터 | 응답 형식 |
|---|---|---|---|---|
| 세션 초기화 | GET | `/pn/mcvrgProd/retrieveMcvrgProdMain.do` | - | HTML |
| 상품 목록 | GET | `/pn/mcvrgProd/retrieveMcvrgProdMain.do` | - | HTML |
| 상품 상세 | - | 목록 행에 포함 | - | - |
| 판매기간 | - | 목록 행에 포함(이전 기간 포함) | - | - |
| 첨부파일 목록 | POST | `/pn/mcvrgProd/retrieveMcvrgProdPop.do` | `insProdSeq`,`seq` | HTML(특약 약관) |
| 파일 다운로드 | GET | `/pn/mcvrgProd/mcvrgProdDownloadFile.do` | `insProdSeq`,`seq`,`fnum`(01·02·03) | PDF |

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

- 약관: `fnum=03`(표의 `약관` 열) + 특약 팝업의 특약 약관 전부
- 사업방법서: `fnum=01`
- 상품요약서: `fnum=02`
- 상대 URL 여부: 예
- JavaScript 함수 여부: `popUpOpen()`
- 파일명 획득 방법: 링크 텍스트 + `Content-Disposition`
- 한 상품에 여러 문서 존재 여부: **예** — 주계약 3종 + 특약 약관 다수

## 6. 구현 방식

- Adapter 파일: `crawler/adapters/metlife.py`
- 수집 방식: STATIC_HTML
- Playwright 사용 여부: 사용 안 함
- 선택한 구현 방식의 이유: 상품·이전 판매기간이 모두 한 HTML 에 있어 1회 요청으로 전량 수집. 특약은 선정된 버전에 대해서만 팝업 조회
- 공통 유틸리티 사용 내역: `common.soup/table_rows/clean/parse_period/absolute`

## 7. 테스트 결과

- 대상 월: 2026-07
- 수집 상품 수: 57 (주보험)
- 상품 버전 수: 690 (2026-07 대상 39)
- 약관 링크 수: 39 + 특약 약관
- 사업방법서 링크 수: 39
- 상품요약서 링크 수: 39
- 다운로드 성공 수: 3 (3종 각 1건)
- 실패 수: 0
- 중복 수: 0
- 누락 또는 수동 검토 수: 0

## 8. 제한 사항

- WAF: 관측되지 않음
- CAPTCHA: 관측되지 않음
- 세션 만료: 관측되지 않음
- 조회 범위 제한: 판매중지 전용 화면이 없어 완전 단종 상품은 목록에 없을 수 있음(확인 불가)
- 날짜 누락: 없음
- 문서 누락: `상품설명서(남/여)` 열은 기본 제외 대상
- 기타 문제: HTML 내 문서 링크 총 1,437개, Adapter 수집 결과(1,437)와 일치

## 9. 확인 근거

- 확인한 화면: 주보험 판매상품목록 + 특약보기 팝업
- 확인한 Network 요청: `GET retrieveMcvrgProdMain.do`, `POST retrieveMcvrgProdPop.do`, `GET mcvrgProdDownloadFile.do`
- 테스트 상품: 무배당 더해주고채워주는정기보험 (insProdSeq 403 / seq 4182)
- 테스트 파일: 무배당 더해주고채워주는정기보험_12284_20260701.pdf — 200 / 2,465,495 bytes / `%PDF-1.6`
- 로그 위치: `99_운영/runs/{YYYY}/{MM}/{DD}/{run_id}/crawler.log`
