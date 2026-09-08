# 미래에셋생명 상품공시실 분석

## 1. 기본 정보

- 보험사 코드: `MIRAE_LIFE`
- 보험사명: 미래에셋생명
- 보험 구분: 생명보험(life)
- config URL: https://life.miraeasset.com/micro/disclosure/product/PC-HO-080301-000000.do
- 실제 상품 목록 URL: 같음(화면) / API `POST /micro/disclosure/selectWorkDvsnDataPaging.do`
- 판매 중 상품 URL: `text1=판매중인상품`
- 판매 중지 상품 URL: `text1=판매중지상품`
- 확인일: 2026-07-31

## 2. 사이트 특징

- 렌더링 방식: JAVASCRIPT_RENDERED + JSON_API
- 상품 카테고리: 12종(변액연금/변액유니버셜/변액종신/종신·정기/건강·암/재해·상해/방카슈랑스/단체보장/단체저축/기타/온라인/간편고지·간편심사)
- 판매채널 구분: 분류에 온라인·방카·단체 포함
- 검색 조건: 상품분류(`text2`) + 상품명(`text3`)
- 날짜 제공 방식: `jsonData.cell2`(판매시작일) / `cell3`(판매종료일)
- 페이지네이션 방식: `pageNum` 0부터 증가, 응답이 비면 종료
- 상품 버전 표시 방식: 행(`seq`) 단위 = 판매기간 1건
- 이전 판매기간 제공 여부: 제공
- 팝업 또는 모달 사용 여부: 없음

## 3. 실제 엔드포인트

| 구분 | 메서드 | 엔드포인트 | 주요 파라미터 | 응답 형식 |
|---|---|---|---|---|
| 세션 초기화 | GET | `/micro/disclosure/product/PC-HO-080301-000000.do` | - | HTML |
| 분류 목록 | POST | `/micro/disclosure/selectProdDvsnGroup.do` | `workDvsn=D`,`text1` | JSON |
| 상품 목록 | POST | `/micro/disclosure/selectWorkDvsnDataPaging.do` | `workDvsn=D`,`text1`,`text2`,`text3`,`pageNum` | JSON |
| 상품 상세 | - | 목록 `jsonData` 에 포함 | - | JSON |
| 판매기간 | - | 목록에 포함 | - | JSON |
| 파일 다운로드 | POST | `/micro/cmmnFileDown.do` | `pathType=gongci_u1`,`filePath`,`fileName`,`orgFileName` | PDF |

## 4. 필수 요청 정보

- Referer: 설정함(config 의 url)
- Origin: 불필요
- User-Agent: config.crawler.user_agent
- Cookie: 불필요
- 세션: 불필요
- CSRF: 없음
- 인코딩: UTF-8
- 기타 헤더: **`Accept: application/json, text/javascript, */*; q=0.01` 필수** — 없으면 HTTP 404(실측)

## 5. 문서 링크 구조

- 약관: 판매중 `cell5` / 판매중지 `cell6`
- 사업방법서: 판매중 `cell6` / 판매중지 `cell7`
- 상품요약서: 판매중 `cell4` / 판매중지 `cell5`
- 상대 URL 여부: 예(`/uploadwas/life` + `cell7`/`cell8`)
- JavaScript 함수 여부: `fn_fileDownClick()` → `COMUTIL.fileDown()`
- 파일명 획득 방법: `jsonData` 의 파일명
- 한 상품에 여러 문서 존재 여부: 버전당 최대 3종

## 6. 구현 방식

- Adapter 파일: `crawler/adapters/mirae_life.py`
- 수집 방식: JSON_API
- Playwright 사용 여부: 사용 안 함
- 선택한 구현 방식의 이유: 화면이 쓰는 페이징 API 재현. 시트별 컬럼 매핑이 달라 분기 처리
- 공통 유틸리티 사용 내역: `common` 의 상수·유틸 대신 Adapter 내 폼 POST + `fetch_document()` 재정의

## 7. 테스트 결과

- 대상 월: 2026-07
- 수집 상품 수: 5,539버전 수집(판매중 46 / 판매중지 5,493)
- 상품 버전 수: 2026-07 대상 294
- 약관 링크 수: 35
- 사업방법서 링크 수: 46
- 상품요약서 링크 수: 46
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
- 문서 누락: 없음
- 기타 문제: 판매중지 시트는 화면상 상품요약서를 숨기지만(`//판매중지상품은 요약서 표시안함`) 응답에는 존재하므로 수집함

## 판매상태 재검증 계약 (2026-08-20)

- **신뢰 상태 소스**: `판매중인상품`·`판매중지상품` 두 탭의 `selectWorkDvsnDataPaging.do` 응답과 탭 자체 상태를 우선합니다. 판매중지 탭의 종료일 셀은 원본 메타데이터로만 보존합니다.
- **필요 상세 호출**: 별도 상품별 상세 호출은 하지 않으며 두 탭의 모든 페이지를 순회합니다.
- **coverage 실패**: 두 탭 중 하나라도 페이지네이션이 끝까지 완료되지 않거나 조회 상한이 적용되면 coverage가 불완전해져 DB의 기존 문서 상태·폴더를 유지합니다.
- **체크포인트**: 상품별 상세 체크포인트는 없습니다. 상태 재검증 시 두 탭과 모든 페이지를 새로 조회합니다.

## 9. 확인 근거

- 확인한 화면: 공시실 > 상품공시실 > 상품목록
- 확인한 Network 요청: Playwright 네트워크 로깅으로 `selectWorkDvsnDataPaging.do` / `selectProdDvsnGroup.do` 확인
- 테스트 상품: 미래에셋생명 변액연금보험 무배당 (2026-07-11 판매개시)
- 테스트 파일: 미래에셋생명+변액연금보험+무배당_약관_20260711.pdf — 200 / 4,215,194 bytes / `%PDF-`
- 로그 위치: `99_운영/runs/{YYYY}/{MM}/{DD}/{run_id}/crawler.log`
