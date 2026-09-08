# NH농협손해보험 상품공시실 분석

## 1. 기본 정보

- 보험사 코드: `NH_FIRE`
- 보험사명: NH농협손해보험
- 보험 구분: 손해보험(non_life)
- config URL: https://www.nhfire.co.kr/announce/productAnnounce/retrieveInsuranceProductsAnnounce.nhfire
- 실제 상품 목록 URL: 추가 수동 확인 필요
- 판매 중 상품 URL: 추가 수동 확인 필요
- 판매 중지 상품 URL: 추가 수동 확인 필요
- 확인일: 2026-07-31

## 2. 사이트 특징

- 렌더링 방식: STATIC_HTML 셸 + AJAX 드릴다운(`xsync.js`)
- 상품 카테고리: 확인 불가
- 판매채널 구분: 확인 불가
- 검색 조건: 확인 불가
- 날짜 제공 방식: 표 머리글에 `판매개시일` / `판매종료일` 존재
- 페이지네이션 방식: 확인 불가
- 상품 버전 표시 방식: 확인 불가
- 이전 판매기간 제공 여부: 확인 불가
- 팝업 또는 모달 사용 여부: 확인 불가

## 3. 실제 엔드포인트

| 구분 | 메서드 | 엔드포인트 | 주요 파라미터 | 응답 형식 |
|---|---|---|---|---|
| 세션 초기화 | GET | `/announce/productAnnounce/retrieveInsuranceProductsAnnounce.nhfire` | - | HTML(200, 404KB) |
| 상품 목록 | - | 화면 함수 `fnRetrievePdtDcd()` / `fnRetrieveProductList()` / `fnRetrieveProductInfo()` 존재. 실제 엔드포인트 확인 불가 | - | - |
| 상품 상세 | - | 확인 불가 | - | - |
| 판매기간 | - | 확인 불가 | - | - |
| 첨부파일 목록 | - | 확인 불가(폼 `oDownloadForm` 존재) | - | - |
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

- 약관: 표 열 `약관` 존재
- 사업방법서: 표 열 `사업방법서`(퇴직연금 표에는 `업무방법서`도 존재)
- 상품요약서: 표 열 `상품요약서` 존재
- 상대 URL 여부: 확인 불가
- JavaScript 함수 여부: 확인 불가
- 파일명 획득 방법: 확인 불가
- 한 상품에 여러 문서 존재 여부: 확인 불가

## 6. 구현 방식

- Adapter 파일: `crawler/adapters/nh_fire.py` (`NHFireAdapter`)
- 등록: `crawler/adapters/__init__.py` (`"NH_FIRE": NHFireAdapter`)
- 수집 방식: XML_AJAX (HTML 진입 후 `devon.xSync` XML 단계 API)
- Playwright 사용 여부: 사용 안 함
- 선택한 구현 방식의 이유: 화면 스크립트에 명시된 3단계 XML AJAX 요청을 재현
- 공통 유틸리티 사용 내역: `BaseInsurerAdapter.client`(HttpClient)와
  `utils.date_utils.parse_date` 사용; XML 태그 추출은 사이트 전용 `_column()` 파서

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
- 기타 문제: 초기 로드 시 상품 관련 XHR 이 발생하지 않고(사용자가 보험종류를 선택해야 조회) 화면 함수만 확인했습니다. 표 머리글에 `상품안내장` 열도 있으나 수집 3종이 아니므로 제외 대상입니다

## 9. 확인 근거

- 확인한 화면: 보험상품공시 > 판매상품
- 확인한 Network 요청: Playwright 네트워크 로깅 — 초기 로드 시 상품 XHR 미관측
- 테스트 상품: 미검증
- 테스트 파일: 미검증
- 레거시 근거(2026-07-31 수동 조사): `C:/…/scratchpad/net.py` Playwright 네트워크 로깅 출력 — 현재 저장구조/리포지토리에 포함되지 않음

---

## 10. 후속 조사 (2026-08-04)

- **최종 분류**: `HTTP_IMPLEMENTABLE` → **구현 완료(IMPLEMENTED)**
- **막혀 있던 지점**: 목록 조회. 초기 로드에 상품 XHR 이 없어 엔드포인트를 확정하지 못했으나,
  화면 인라인 스크립트의 `devon.xSync('/front/announce/...')` 호출부에 그대로 적혀 있었습니다.
- **확정한 경로(3단계)**
  | 순서 | 메서드 | 엔드포인트 | 파라미터 | 반환 |
  |---|---|---|---|---|
  | 1 | POST | `/front/announce/retrievePdtDcd.ajax` | `type=ajax, pdtSelYn(Y/N), pdtGrCd(01~04)` | 상품구분 `pdtDcd` |
  | 2 | POST | `/front/announce/retrievePdtCd.ajax` | `+ pdtDcd` | 상품 `pdtCd`,`pdtNm` |
  | 3 | POST | `/front/announce/retrievePdtInfo.ajax` | `+ pdtCd` | 판매기간·파일ID |
  | 4 | GET/POST | `/imageView/downloadFile.ajax` | `fileId, afileSeqn` | PDF |
- **응답 형식**: JSON 이 아니라 **xSync XML** — `<태그><![CDATA[값]]></태그>` 가 태그별로 순서대로 나열됩니다.
- **파일 순번(afileSeqn)**: `1` 약관 / `2` 상품요약서 / `3` 상품안내장(수집 제외) /
  `4` 사업방법서 / `5` 업무방법서(수집 3종 아님)
- **상품군(pdtGrCd)**: 01 장기보험 · 02 일반보험 · 03 정책보험 · 04 농작물재해보험
- **검증(2026-08-04)**: 정책보험 표본 33버전 / 99문서.
  약관 878,751 B, 상품요약서 163,232 B, 사업방법서 84,220 B 모두 `%PDF-` 200.
- **Adapter**: `crawler/adapters/nh_fire.py`
