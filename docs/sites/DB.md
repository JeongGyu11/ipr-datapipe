# DB손해보험 상품공시실 분석

## 1. 기본 정보

- 보험사 코드: `DB`
- 보험사명: DB손해보험
- 보험 구분: 손해보험(non_life)
- config URL: https://www.idbins.com/FWMAIV1534.do
- 실제 상품 목록 URL: https://www.idbins.com/insuPcPbanFindProductStep5_AX.do (화면이 호출하는 내부 API)
- 판매 중 상품 URL: `arc_pdc_sl_yn=1`
- 판매 중지 상품 URL: `arc_pdc_sl_yn=0`
- 확인일: 2026-07-31

## 2. 사이트 특징

- 렌더링 방식: JSON_API (화면은 정적 HTML + AJAX)
- 상품 카테고리: 장기보험 / 일반 / 자동차보험 / 제도성 특별약관 (`ARC_KND_LGCG_NM`)
- 판매채널 구분: `sl_chn_nm` 파라미터로 구분
- 검색 조건: 상품명 키워드 + 판매기간(beginDate/endDate)
- 날짜 제공 방식: `SALE_BEGIN_DAY`(판매개시일), Step4 의 `SL_STR_DT`/`SL_FIN_DT`
- 페이지네이션 방식: 없음(Step5 는 조건에 맞는 전체 반환)
- 상품 버전 표시 방식: `SQNO` 단위로 상품 버전 1건
- 이전 판매기간 제공 여부: Step3 판매기간 목록으로 제공
- 팝업 또는 모달 사용 여부: 없음

## 3. 실제 엔드포인트

| 구분 | 메서드 | 엔드포인트 | 주요 파라미터 | 응답 형식 |
|---|---|---|---|---|
| 세션 초기화 | GET | `/FWMAIV1534.do` | - | HTML |
| 상품 목록 | POST | `/insuPcPbanFindProductStep5_AX.do` | `searchCheck`,`keyword`,`beginDate`,`endDate` | JSON |
| 상품 상세 | POST | `/insuPcPbanFindProductStep4_AX.do` | `sqno`,`arc_pdc_sl_yn` | JSON |
| 판매기간 | POST | `/insuPcPbanFindProductStep3_AX.do` | `pdc_nm`,`arc_pdc_sl_yn` | JSON |
| 첨부파일 목록 | - | 목록 응답에 파일명 포함 | - | JSON |
| 파일 다운로드 | GET | `/cYakgwanDown.do` | `FilePath=InsProduct/{파일명}` | PDF |

## 4. 필수 요청 정보

- Referer: 설정함(config 의 url)
- Origin: 불필요
- User-Agent: config.crawler.user_agent
- Cookie: 불필요
- 세션: 불필요
- CSRF: 없음
- 인코딩: UTF-8
- 기타 헤더: `Content-Type: application/json` 필수 (폼 인코딩 시 HTTP 415)

## 5. 문서 링크 구조

- 약관: `INPL_FINM`
- 사업방법서: `BIZ_MDDC_FINM`
- 상품요약서: `CNSL_SMAR_FINM`
- 상대 URL 여부: 아니오(다운로드 URL 조립)
- JavaScript 함수 여부: 없음
- 파일명 획득 방법: 응답 필드에 원본 파일명 포함
- 한 상품에 여러 문서 존재 여부: 상품 버전당 3종 각 1개

## 6. 구현 방식

- Adapter 파일: `crawler/adapters/db_insurance.py` (기존, 미변경)
- 수집 방식: JSON_API
- Playwright 사용 여부: 사용 안 함
- 선택한 구현 방식의 이유: 공식 화면이 사용하는 기간검색 API 를 그대로 재현하는 것이 요청 수가 가장 적음
- 공통 유틸리티 사용 내역: 기존 Adapter 로 `crawler/adapters/common.py` 미사용

## 7. 테스트 결과

- 대상 월: 2026-07
- 수집 상품 수: 6
- 상품 버전 수: 6
- 약관 링크 수: 6
- 사업방법서 링크 수: 6
- 상품요약서 링크 수: 6
- 다운로드 성공 수: 18 (2026-07-31 전량 검증)
- 실패 수: 0
- 중복 수: 0
- 누락 또는 수동 검토 수: 0

## 8. 제한 사항

- WAF: 관측되지 않음
- CAPTCHA: 관측되지 않음
- 세션 만료: 관측되지 않음
- 조회 범위 제한: 없음
- 날짜 누락: 없음
- 문서 누락: 없음
- 기타 문제: 2026-07 신규/개정이 6건으로 적음(2026-06 은 67건). API 상한이 아니라 실제 건수

## 판매상태 재검증 계약 (2026-08-20)

- **신뢰 상태 소스**: 기간검색 Step5 결과와 판매기간을 보강하는 Step4 상세 응답을 함께 사용합니다. 기존 `ACTIVE` 행은 SQNO 기준으로 Step4를 다시 조회합니다.
- **필요 상세 호출**: Step5 후보마다 필요한 경우 `insuPcPbanFindProductStep4_AX.do`를 호출해 판매종료일과 상태를 보강합니다(동일 실행의 같은 SQNO/판매 플래그는 내부 캐시 재사용).
- **coverage 실패**: Step5 또는 필요한 Step4가 실패하거나 식별자가 없으면 `status_coverage_complete=false`가 되어 DB의 기존 문서 상태·폴더를 유지합니다. 실패를 판매종료로 추론하지 않습니다.
- **체크포인트**: DB는 상품 상세 체크포인트를 사용하지 않습니다. 상태 재검증 대상은 다음 실행에서도 Step4를 새로 확인합니다.

## 9. 확인 근거

- 확인한 화면: 공시실 상품검색 화면
- 확인한 Network 요청: Step2~Step5 AJAX
- 테스트 상품: 무배당 프로미라이프 간편건강보험(일반심사형)2607 (SQNO 10582)
- 테스트 파일: 약관_31073(08)_20260701.pdf (13,091,228 bytes)
- 로그 위치: `99_운영/runs/{YYYY}/{MM}/{DD}/{run_id}/crawler.log`
