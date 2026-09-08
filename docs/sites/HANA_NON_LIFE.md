# 하나손해보험 상품공시실 분석

## 1. 기본 정보

- 보험사 코드: `HANA_NON_LIFE`
- 보험사명: 하나손해보험
- 보험 구분: 손해보험(non_life)
- config URL: https://m.hanainsure.co.kr/w/disclosure/product/saleProduct
- 실제 상품 목록 URL: 4단계 JSON 드릴다운(getSaleStepOne~Four)
- 판매 중 상품 URL: `/w/disclosure/product/saleProduct` (`sSaleYn=Y`)
- 판매 중지 상품 URL: `/w/disclosure/product/saleStopProduct` (`sSaleYn=N`)
- 확인일: 2026-07-31

## 2. 사이트 특징

- 렌더링 방식: JAVASCRIPT_RENDERED + JSON_API
- 상품 카테고리: 자동차보험(개인용/업무용/영업용/이륜차/기타), 일반보험(상해/화재/종합/기타), 장기보험(상해·건강/재물/제도성특약)
- 판매채널 구분: 별도 구분 없음
- 검색 조건: 상품명(`searchProduct.json` 통합검색)
- 날짜 제공 방식: STEP4 응답 `sSaleStrDt` / `sSaleEndDt`(`9999…` = 판매중)
- 페이지네이션 방식: 없음(단계별 전체)
- 상품 버전 표시 방식: STEP3 의 `nSeqNo` 단위
- 이전 판매기간 제공 여부: **제공** — STEP3 가 상품의 모든 판매기간 반환
- 팝업 또는 모달 사용 여부: 없음(4-STEP 화면)

## 3. 실제 엔드포인트

| 구분 | 메서드 | 엔드포인트 | 주요 파라미터 | 응답 형식 |
|---|---|---|---|---|
| 세션 초기화 | GET | `/w/disclosure/product/saleProduct` | - | HTML |
| 분류 목록 | POST | `/w/disclosure/product/getSaleStepOne.json` | `sSaleYn` | JSON |
| 상품 목록 | POST | `/w/disclosure/product/getSaleStepTwo.json` | `sSaleYn`,`sInsType`,`sInsDtlType` | JSON |
| 판매기간 | POST | `/w/disclosure/product/getSaleStepThree.json` | `sSaleYn`,`sInsType`,`sInsDtlType`,`sSpcType`,`RPSPDCD`,`UNTPDCD` | JSON |
| 첨부파일 목록 | POST | `/w/disclosure/product/getSaleStepFour.json` | `sSaleYn`,`nSeqNo` | JSON |
| 파일 다운로드 | GET | `/download/{fileID}` | - | PDF |

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

- 약관: `sPolicyFileID`
- 사업방법서: `sBizFileID`
- 상품요약서: `sSummaryFileID`
- 상대 URL 여부: 예(`/download/{id}`)
- JavaScript 함수 여부: 템플릿 렌더링(`tmplStep04Init`)
- 파일명 획득 방법: `Content-Disposition`
- 한 상품에 여러 문서 존재 여부: 버전당 최대 3종

## 6. 구현 방식

- Adapter 파일: `crawler/adapters/hana_non_life.py`
- 수집 방식: JSON_API
- Playwright 사용 여부: 사용 안 함
- 선택한 구현 방식의 이유: 공식 화면의 4단계 API 재현. `sPrdKeyID`/`sPrdType`/`sPrdCd` 는 STEP2 응답에 없어 빈 문자열로 전송(빈 문자열일 때 정상 응답 실측 확인, `undefined` 는 빈 배열 반환)
- 공통 유틸리티 사용 내역: `common.json_post`
- **STEP4 지연 조회**: STEP3 응답에 이미 `sSaleStrDt`/`sSaleEndDt` 가 있으므로 대상 월 판정은 STEP3 까지로 끝내고,
  문서 링크를 얻는 STEP4 는 `collect_documents()` 에서 **대상 월로 선정된 버전에 대해서만** 호출합니다.
  이 구조 덕분에 요청 수가 약 4,000회 → 약 970회로 줄었습니다(§8 참조).

## 7. 테스트 결과

- 대상 월: 2026-07
- 수집 상품 수: 888 (판매중 141 / 판매중지 747)
- 상품 버전 수: **3,078 수집 → 2026-07 대상 60**
- 약관 링크 수: 60
- 사업방법서 링크 수: 60
- 상품요약서 링크 수: 58 (2건 미제공)
- 다운로드 성공 수: 3 (약관·사업방법서·상품요약서 각 1건)
- 실패 수: 0
- 중복 수: 0
- 누락 또는 수동 검토 수: 0
- 전량 dry-run 소요: **1,944.9초(약 32분)**, 문서 레코드 178건, 실패 0건

## 8. 제한 사항

- WAF: 관측되지 않음
- CAPTCHA: 관측되지 않음
- 세션 만료: 관측되지 않음
- 조회 범위 제한: 없음(전량 수집 확인). 요청 수는 STEP1 2회 + STEP2 22회 + STEP3 888회 + STEP4(선정 버전 60회)
  ≈ **972회 / 약 32분**(요청 간격 2초)
- 날짜 누락: 없음
- 문서 누락: 상품요약서 2건 미제공(`sSummaryFileID` 빈 값) — 사이트가 제공하지 않는 건
- 기타 문제: 없음
- **성능 이력**: 초기 구현은 판매기간마다 STEP4 를 호출해 24분에 4개 세부분류(상품 15건)밖에 처리하지 못했습니다.
  STEP3 에 이미 판매기간이 들어 있는 점을 이용해 STEP4 를 `collect_documents()` 로 미룬 뒤
  전량 32분으로 단축했습니다(요청 약 4,000회 → 약 972회).

## 9. 확인 근거

- 확인한 화면: 상품목록 4-STEP 화면(판매상품 / 판매중지상품)
- 확인한 Network 요청: `getSaleStepOne~Four.json` (Playwright 네트워크 로깅 + httpx 재현)
- 테스트 상품: 무배당 하나더퍼스트 3.0.5 간편 건강보험(간편심사형)(2601) 1종(암집중형)
  — 2026-07-01 판매개시, STEP3 nSeqNo 3402
- 테스트 파일 (2026-08-04 실측)
  - 약관 `GET /download/…` → 200 / 5,519,191 bytes / `%PDF-` / `60706_20260701_01.pdf`
  - 사업방법서 → 200 / 448,296 bytes / `%PDF-` / `60706_20260701_02.pdf`
  - 상품요약서 → 200 / 350,311 bytes / `%PDF-` / `60706_20260701_03.pdf`
- 로그 위치: `99_운영/runs/{YYYY}/{MM}/{DD}/{run_id}/crawler.log`; 레거시 근거(2026-07-31 수동 조사) dry-run 로그 `scratchpad/hana_nl_dryrun.txt` — 현재 저장구조/리포지토리에 포함되지 않음
