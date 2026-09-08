# 현대해상 상품공시실 분석

## 1. 기본 정보

- 보험사 코드: `HYUNDAI_MARINE`
- 보험사명: 현대해상
- 보험 구분: 손해보험(non_life)
- config URL: https://www.hi.co.kr/serviceAction.do?view=bin%2FPA%2F03%2FHHPA03020M
- 실제 상품 목록 URL: https://www.hi.co.kr/ajax.xhi (tranId=HHCA0310M19S)
- 판매 중 상품 URL: `slYn=Y`
- 판매 중지 상품 URL: `slYn=N`
- 확인일: 2026-07-31

## 2. 사이트 특징

- 렌더링 방식: JSON_API
- 상품 카테고리: `prodCatCd` 앞 2자리 — 01 일반보험 / 02 자동차보험 / 03 장기보험 / 04·05 기타
- 판매채널 구분: 별도 구분 없음
- 검색 조건: `searchKeyword` 존재(본 크롤러는 전량 조회)
- 날짜 제공 방식: `slStDt` / `slEdDt`
- 페이지네이션 방식: 없음(1회 호출 약 6,900행)
- 상품 버전 표시 방식: `insCd`+`slStDt` 단위
- 이전 판매기간 제공 여부: 응답에 과거 판매기간 포함
- 팝업 또는 모달 사용 여부: 없음

## 3. 실제 엔드포인트

| 구분 | 메서드 | 엔드포인트 | 주요 파라미터 | 응답 형식 |
|---|---|---|---|---|
| 세션 초기화 | GET | `/serviceAction.do?view=bin/PA/03/HHPA03020M` | - | HTML |
| 상품 목록 | POST | `/ajax.xhi` | JSON `{header:{tranId:"HHCA0310M19S"},request:{slYn}}` | JSON |
| 상품 상세 | - | 목록에 포함 | - | - |
| 판매기간 | - | 목록에 포함 | - | - |
| 첨부파일 경로 | POST | `/ajax.xhi` | JSON `{header:{tranId:"HHCA0310M26S"},request:{apnflId}}` | JSON |
| 파일 다운로드 | GET | `/FileActionServlet/download/0/{savPath}/{savFileNm}.{flExts}` | - | PDF |

## 4. 필수 요청 정보

- Referer: 설정함(config 의 url)
- Origin: 불필요
- User-Agent: config.crawler.user_agent
- Cookie: 불필요
- 세션: 불필요
- CSRF: 없음
- 인코딩: UTF-8
- 기타 헤더: `Content-Type: application/json`

## 5. 문서 링크 구조

- 약관: `clauApnflId`
- 사업방법서: `userMthdApnflId`
- 상품요약서: `prodSmryApnflId`
- 상대 URL 여부: 예
- JavaScript 함수 여부: `openPdf()`/`linkPdf()` → `doBizFileDownload()`
- 파일명 획득 방법: `HHCA0310M26S` 응답의 `originalFileNm`
- 한 상품에 여러 문서 존재 여부: 버전당 최대 3종

## 6. 구현 방식

- Adapter 파일: `crawler/adapters/hyundai_marine.py`
- 수집 방식: JSON_API
- Playwright 사용 여부: 사용 안 함
- 선택한 구현 방식의 이유: 1회 호출로 전량 수집. 파일은 UUID→경로 변환 1회 후 직접 GET
- 공통 유틸리티 사용 내역: `common.json_post`

## 7. 테스트 결과

- 대상 월: 2026-07
- 수집 상품 수: 6,873버전 수집(판매중 212 / 판매중지 6,661)
- 상품 버전 수: 2026-07 대상 69
- 약관 링크 수: 68
- 사업방법서 링크 수: 69
- 상품요약서 링크 수: 62
- 다운로드 성공 수: 3 (3종 각 1건)
- 실패 수: 0
- 중복 수: 0
- 누락 또는 수동 검토 수: 0

## 8. 제한 사항

- WAF: 관측되지 않음
- CAPTCHA: 관측되지 않음
- 세션 만료: 관측되지 않음
- 조회 범위 제한: 없음
- 날짜 누락: 없음
- 문서 누락: `prodNoteApnflId`(상품설명서)는 기본 제외 대상
- 기타 문제: 응답이 약 1.9MB 이므로 타임아웃 120초로 확장

## 9. 확인 근거

- 확인한 화면: 보험상품공시 화면(자동차 / 장기 / 일반 탭)
- 확인한 Network 요청: `POST /ajax.xhi`(HHCA0310M19S, HHCA0310M26S), `GET /FileActionServlet/download/…`
- 테스트 상품: 전기차화재안심보험 (2026-07-01), Hicar 개인용자동차보험 (2026-07-28)
- 테스트 파일: 03.약관_20260701_전기차화재안심보험.pdf — 200 / 616,581 bytes / `%PDF-`
- 로그 위치: `99_운영/runs/{YYYY}/{MM}/{DD}/{run_id}/crawler.log`
