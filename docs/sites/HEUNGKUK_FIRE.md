# 흥국화재 상품공시실 분석

## 1. 기본 정보

- 보험사 코드: `HEUNGKUK_FIRE`
- 보험사명: 흥국화재
- 보험 구분: 손해보험(non_life)
- config URL: https://www.heungkukfire.co.kr/FRW/announce/insGoodsGongsiSale.do
- 실제 상품 목록 URL: 같음(POST)
- 판매 중 상품 URL: `mode=go`
- 판매 중지 상품 URL: `mode=stop`
- 확인일: 2026-07-31

## 2. 사이트 특징

- 렌더링 방식: FORM_POST
- 상품 카테고리: `type` 1 장기보험 / 2 일반보험 / 3 자동차보험, 표의 `구분` 열(의료·건강, 운전자·상해, 자녀·실버 등)
- 판매채널 구분: 별도 구분 없음
- 검색 조건: 상품명(`searchvalue`)
- 날짜 제공 방식: `판매일` 열 — 판매 화면은 단일 판매개시일, 판매중지 화면은 `시작 ~ 종료`
- 페이지네이션 방식: `page` 파라미터, 페이지당 10행, `goPage(page)`
- 상품 버전 표시 방식: 행 단위
- 이전 판매기간 제공 여부: 판매중지 화면에 제공
- 팝업 또는 모달 사용 여부: 없음

## 3. 실제 엔드포인트

| 구분 | 메서드 | 엔드포인트 | 주요 파라미터 | 응답 형식 |
|---|---|---|---|---|
| 세션 초기화 | GET | `/FRW/announce/insGoodsGongsiSale.do` | - | HTML |
| 상품 목록 | POST | `/FRW/announce/insGoodsGongsiSale.do` | `mode`,`type`,`page`,`searchvalue` | HTML |
| 상품 상세 | - | 목록 행에 포함 | - | - |
| 판매기간 | - | 목록 행에 포함 | - | - |
| 첨부파일 목록 | - | `fn_filedownX(path, realName, saveName)` | - | - |
| 파일 다운로드 | POST | `/common/download.do` | `filePath`,`fileRealName`,`fileSaveName`,`mode=View` | PDF |

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

- 약관: 첨부파일 셀의 `상품약관` 링크
- 사업방법서: `사업방법서` 링크
- 상품요약서: `상품요약서` 링크
- 상대 URL 여부: 해당 없음(폼 POST)
- JavaScript 함수 여부: `fn_filedownX()`
- 파일명 획득 방법: `fileRealName` 인자
- 한 상품에 여러 문서 존재 여부: 행마다 첨부 링크 2~3개

## 6. 구현 방식

- Adapter 파일: `crawler/adapters/heungkuk_fire.py`
- 수집 방식: FORM_POST
- Playwright 사용 여부: 사용 안 함
- 선택한 구현 방식의 이유: 화면이 서버 렌더링. mode×type 6조합 × 페이지 순회
- 공통 유틸리티 사용 내역: `common.soup/table_rows/clean/js_call_args/parse_period`

## 7. 테스트 결과

- 대상 월: 2026-07
- 수집 상품 수: 2,348버전 수집(판매중 112 / 판매중지 2,236)
- 상품 버전 수: `docs/REGRESSION_TEST_RESULT.md` 참조
- 약관 링크 수: 수집 확인
- 사업방법서 링크 수: 수집 확인
- 상품요약서 링크 수: 수집 확인
- 다운로드 성공 수: 3 (3종 각 1건)
- 실패 수: 0
- 중복 수: 0
- 누락 또는 수동 검토 수: 0

## 8. 제한 사항

- WAF: 관측되지 않음
- CAPTCHA: 관측되지 않음
- 세션 만료: 관측되지 않음
- 조회 범위 제한: 6조합 × 평균 약 40페이지 ≈ 240요청 → 실측 약 500초
- 날짜 누락: 없음
- 문서 누락: 없음
- 기타 문제: 첨부 링크 표시명이 `상품약관`/`사업방법서`/`상품요약서` 이므로 표시명으로 문서유형 판별

## 9. 확인 근거

- 확인한 화면: 보험상품공시(판매 / 판매중지 탭 × 장기·일반·자동차 탭)
- 확인한 Network 요청: `POST /FRW/announce/insGoodsGongsiSale.do`, `POST /common/download.do`
- 테스트 상품: 제도성 특별약관(유병력자실손의료보험 중지 및 재개(26.07) 특별약관) (2026-07-01)
- 테스트 파일: 제도성+특별약관(…)+기초서류.pdf — 200 / 113,182 bytes / `%PDF-`
- 로그 위치: `99_운영/runs/{YYYY}/{MM}/{DD}/{run_id}/crawler.log`
