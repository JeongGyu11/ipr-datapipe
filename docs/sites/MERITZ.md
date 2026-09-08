# 메리츠화재 상품공시실 분석

## 1. 기본 정보

- 보험사 코드: `MERITZ`
- 보험사명: 메리츠화재
- 보험 구분: 손해보험(non_life)
- config URL: https://www.meritzfire.com/disclosure/product-announcement/product-list.do?vMode=PC
- 실제 상품 목록 URL: 화면 내 AngularJS `bc` 서비스 → `POST /json.smart`
- 판매 중 상품 URL: `notfYn=Y`
- 판매 중지 상품 URL: `notfYn=N`
- 확인일: 2026-07-31

## 2. 사이트 특징

- 렌더링 방식: PLAYWRIGHT_REQUIRED (헤드풀)
- 상품 카테고리: 16종(자동차/운전자/통합/질병/어린이/암/상해/연금저축/저축/화재·재물·비용/생활/장기 방카/일반 방카/배상책임/퇴직연금/제도성특약)
- 판매채널 구분: 별도 구분 없음
- 검색 조건: `retrieveSalPdSchList` 검색형 제공
- 날짜 제공 방식: `bgnDt`(판매개시일), `putupStDdTm`/`putupEdDdTm`(게시일)
- 페이지네이션 방식: 없음(분류별 전체 반환)
- 상품 버전 표시 방식: `ntbdDtlSeq` 단위
- 이전 판매기간 제공 여부: 분류 목록에 이전 버전 포함
- 팝업 또는 모달 사용 여부: 없음

## 3. 실제 엔드포인트

| 구분 | 메서드 | 엔드포인트 | 주요 파라미터 | 응답 형식 |
|---|---|---|---|---|
| 세션 초기화 | GET | 화면 진입(헤드풀 브라우저) | - | HTML |
| 상품 목록 | POST | `/json.smart` | `rcvmsgSrvId=...PbanBc.retrieveSalPdList`,`cmPdDivCd`,`notfYn` | JSON |
| 상품 상세 | POST | `/json.smart` | `...retrieveSalPdListForCdNm` | JSON |
| 판매기간 | - | 목록 응답에 포함 | - | JSON |
| 첨부파일 목록 | - | 목록 응답 `file1~file4` + `*#[E]` 토큰 | - | JSON |
| 파일 다운로드 | POST→GET | `/hp/fileDownload.do` | `path`,`id`,`orgFileName` (암호화 토큰) | PDF |

## 4. 필수 요청 정보

- Referer: 설정함(config 의 url)
- Origin: 불필요
- User-Agent: config.crawler.user_agent
- Cookie: 필수(웹방화벽)
- 세션: 필수 — 목록과 다운로드를 같은 브라우저 세션에서 처리
- CSRF: 없음
- 인코딩: UTF-8
- 기타 헤더: 없음

## 5. 문서 링크 구조

- 약관: `file1`
- 사업방법서: `file2`
- 상품요약서: `file3`
- 상대 URL 여부: 해당 없음(토큰 기반)
- JavaScript 함수 여부: `fileUtil.download()` 호출
- 파일명 획득 방법: 응답의 `orgFileName`
- 한 상품에 여러 문서 존재 여부: 상품 버전당 3종 각 1개

## 6. 구현 방식

- Adapter 파일: `crawler/adapters/meritz_insurance.py` (기존, 미변경)
- 수집 방식: PLAYWRIGHT_REQUIRED
- Playwright 사용 여부: 사용(headless=False 강제)
- 선택한 구현 방식의 이유: httpx·headless 로는 파일 다운로드 경로가 웹방화벽에 차단됨. 우회하지 않고 실제 브라우저의 정상 클릭 흐름을 사용
- 공통 유틸리티 사용 내역: 기존 Adapter 로 `common.py` 미사용

## 7. 테스트 결과

- 대상 월: 2026-07
- 수집 상품 수: 183
- 상품 버전 수: 183
- 약관 링크 수: 183
- 사업방법서 링크 수: 167
- 상품요약서 링크 수: 141
- 다운로드 성공 수: 표본 2건 검증
- 실패 수: 0
- 중복 수: 0
- 누락 또는 수동 검토 수: 0

## 8. 제한 사항

- WAF: 있음 — `Web firewall security policies have been blocked.` (우회하지 않음)
- CAPTCHA: 관측되지 않음
- 세션 만료: 관측되지 않음
- 조회 범위 제한: 없음
- 날짜 누락: 없음
- 문서 누락: 없음
- 기타 문제: `#[E]` 토큰이 세션 종속. 서비스 계정/무인 서버에서는 헤드풀 실행 환경 필요

## 판매상태 재검증 계약 (2026-08-20)

- **신뢰 상태 소스**: Playwright 세션으로 호출하는 `retrievePdList`·`retrieveSalPdList`의 `notfYn=Y`(판매중) / `N`(판매중지) 분기를 우선합니다. `putupEdDdTm`은 게시 종료일이므로 단독으로 판매종료를 판정하지 않습니다.
- **필요 상세 호출**: 별도 상품별 상태 API는 없으며, 상태별 분류와 상품 목록 API를 모두 조회합니다.
- **coverage 실패**: 두 상태 분기·분류·목록 응답 중 하나라도 실패하면 완전한 coverage가 아니므로 DB의 기존 문서 상태·폴더를 유지합니다. 정상적으로 전량 분기를 소진했을 때만 `status_coverage_complete=true`입니다.
- **체크포인트**: 상품별 상세 체크포인트는 없습니다. WAF 세션을 포함한 목록 분기를 재실행해 상태를 확인합니다.

## 9. 확인 근거

- 확인한 화면: 상품공시 목록 화면
- 확인한 Network 요청: `POST /json.smart`, `POST /hp/fileDownload.do`
- 테스트 상품: Readycar개인용자동차보험 (bgnDt 20260707)
- 테스트 파일: Readycar개인용자동차보험약관.pdf (5,148,137 bytes)
- 로그 위치: `99_운영/runs/{YYYY}/{MM}/{DD}/{run_id}/crawler.log`
