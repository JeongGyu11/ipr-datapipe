# 교보생명 상품공시실 분석

## 1. 기본 정보

- 보험사 코드: `KYOBO_LIFE`
- 보험사명: 교보생명
- 보험 구분: 생명보험(life)
- config URL: https://www.kyobo.com/dgt/web/product-official/information (공시 안내 화면 — 상품 목록 아님)
- 실제 상품 목록 URL: https://www.kyobo.com/dgt/web/product-official/all-product/search (resolved_disclosure_url)
- 판매 중 상품 URL: 목록 API `saleYn=Y`
- 판매 중지 상품 URL: 목록 API `saleYn=N` (본 크롤러는 `99`=전체 사용)
- 확인일: 2026-07-31

## 2. 사이트 특징

- 렌더링 방식: JAVASCRIPT_RENDERED + JSON_API
- 상품 카테고리: `dgtPdtAtrMclCd`(PAMS…) 대분류 / `dgtPdtAtrSmclCd` 소분류. 화면 표기는 '보장성보험(재해상해)' 형태
- 판매채널 구분: 별도 구분 없음
- 검색 조건: 상품명(`searchTxt`), 분류, 판매여부
- 날짜 제공 방식: 상세 응답 `list[].saleStDt` / `saleEdDt`
- 페이지네이션 방식: `currentPage`/`pagePerSize` (전체 1,119건, pagePerSize=100 기준 12페이지)
- 상품 버전 표시 방식: `dgtPdtAtrSeqtId` 상품 → 상세의 판매기간 배열 각각이 1버전
- 이전 판매기간 제공 여부: 제공(상세 팝업의 판매기간 목록 전체)
- 팝업 또는 모달 사용 여부: 예(기간별 다운로드 모달)

## 3. 실제 엔드포인트

| 구분 | 메서드 | 엔드포인트 | 주요 파라미터 | 응답 형식 |
|---|---|---|---|---|
| 세션 초기화 | GET | `/dgt/web/product-official/all-product/search` | - | HTML |
| 상품 목록 | POST | `/dtc/product-official/find-allProductSearch` | JSON `{dgtPdtAtrDvCd:"M", saleYn:"99", currentPage, pagePerSize}` | JSON |
| 상품 상세 | POST | `/dtc/product-official/find-allProductSearchDetail` | JSON `{dgtPdtPdSeqtId}` | JSON |
| 판매기간 | - | 상세 응답 `body.list` | - | JSON |
| 첨부파일 목록 | - | 상세 응답 `body.list2` (`temp01~03`) | - | JSON |
| 파일 다운로드 | GET | `/file/ajax/download` | `fName=/dtc/pdf/mm/{파일명}` | PDF |

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

- 약관: `list2[].temp02`
- 사업방법서: `list2[].temp03`
- 상품요약서: `list2[].temp01`
- 상대 URL 여부: 예
- JavaScript 함수 여부: `getProdDtlList()` → `fileDownload()`
- 파일명 획득 방법: `Content-Disposition: filename*=UTF-8''…` (RFC5987)
- 한 상품에 여러 문서 존재 여부: 상품당 판매기간 수만큼 버전, 버전당 최대 3종

## 6. 구현 방식

- Adapter 파일: `crawler/adapters/kyobo_life.py`
- 수집 방식: JSON_API
- Playwright 사용 여부: 사용 안 함
- 선택한 구현 방식의 이유: 공식 화면이 쓰는 XHR 두 개(목록·상세)로 전량 수집 가능. Playwright 불필요
- 공통 유틸리티 사용 내역: `common.json_post`

## 7. 테스트 결과

- 대상 월: 2026-07
- 수집 상품 수: 1,119 (전체)
- 상품 버전 수: 상품 25건 표본 → 74버전 / 문서 112건
- 약관 링크 수: 표본 확인
- 사업방법서 링크 수: 표본 확인
- 상품요약서 링크 수: 표본 0 (구상품은 요약서 미제공)
- 다운로드 성공 수: 2 (약관 1, 사업방법서 1)
- 실패 수: 0
- 중복 수: 0
- 누락 또는 수동 검토 수: 0

## 8. 제한 사항

- WAF: 관측되지 않음
- CAPTCHA: 관측되지 않음
- 세션 만료: 관측되지 않음
- 조회 범위 제한: 상품 1,119건 × 상세 1회 ≈ 1,131 요청. 요청 간격 2초 기준 약 40분(전량 dry-run 미완료)
- 날짜 누락: 없음
- 문서 누락: 1999년 이전 상품은 사업방법서를 공시하지 않음(`dgtPdtDsc` 에 명시)
- 기타 문제: config URL 이 공시 안내 화면이라 `resolved_disclosure_url` 로 실제 목록 화면을 분리 기록

## 판매상태 재검증 계약 (2026-08-20)

- **신뢰 상태 소스**: 상품 목록 `find-allProductSearch` 자체가 아니라 상품별 `find-allProductSearchDetail`의 판매기간 상세를 사용합니다.
- **필요 상세 호출**: 상품별 상세 호출이 필수입니다. 기존 `ACTIVE` 상품은 완료된 상세 체크포인트가 있어도 fresh detail을 요청합니다.
- **coverage 실패**: 상품 상한(`max-products`) 또는 상세 실패가 있으면 `status_coverage_complete=false`이며 DB의 기존 문서 상태·폴더를 유지합니다. 상세 실패는 재실행 대상으로 기록합니다.
- **체크포인트**: 일반 상품의 성공 상세는 `detail_checkpoint.jsonl`에서 재사용하지만, `ACTIVE` 상태 재검증 대상은 체크포인트를 우회합니다.

## 9. 확인 근거

- 확인한 화면: 전체상품조회 화면 + 기간별 다운로드 팝업
- 확인한 Network 요청: `find-allProductSearch`, `find-allProductSearchDetail`, `/file/ajax/download`
- 테스트 상품: (무)119생활보험(BYC) (dgtPdtAtrSeqtId 182)
- 테스트 파일: (무)119생활보험(98.04.01).pdf — 200 / application/pdf / 3,843,291 bytes / `%PDF-1.4`
- 로그 위치: `99_운영/runs/{YYYY}/{MM}/{DD}/{run_id}/crawler.log`
