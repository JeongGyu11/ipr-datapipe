# IBK연금보험 상품공시실 분석

## 1. 기본 정보

- 보험사 코드: `IBK_LIFE`
- 보험사명: IBK연금보험
- 보험 구분: 생명보험(life)
- config URL: https://www.ibki.co.kr/process/HP_PBANO_PDT_SP_INDV
- 실제 상품 목록 URL: `/process/HP_PBANO_PDT_SP_INDV`, `_SP_RTMT`, `_NSP_INDV`, `_NSP_RTMT`
- 판매 중 상품 URL: `HP_PBANO_PDT_SP_INDV` / `HP_PBANO_PDT_SP_RTMT`
- 판매 중지 상품 URL: `HP_PBANO_PDT_NSP_INDV` / `HP_PBANO_PDT_NSP_RTMT`
- 확인일: 2026-07-31

## 2. 사이트 특징

- 렌더링 방식: STATIC_HTML
- 상품 카테고리: 개인연금 / 퇴직연금
- 판매채널 구분: 일반, TM, CM, 방카슈랑스(표의 `판매채널` 열)
- 검색 조건: 상품명(`searchString`)
- 날짜 제공 방식: `판매기간` 열 `YYYY-MM-DD ~ 현재`
- 페이지네이션 방식: 없음(화면당 전체)
- 상품 버전 표시 방식: 행 단위
- 이전 판매기간 제공 여부: 판매중지 화면에 제공
- 팝업 또는 모달 사용 여부: 없음

## 3. 실제 엔드포인트

| 구분 | 메서드 | 엔드포인트 | 주요 파라미터 | 응답 형식 |
|---|---|---|---|---|
| 세션 초기화 | GET | `/process/HP_PBANO_PDT_SP_INDV` | - | HTML |
| 상품 목록 | GET | `/process/HP_PBANO_PDT_{SP\|NSP}_{INDV\|RTMT}` | - | HTML(EUC-KR) |
| 상품 상세 | - | 목록 행에 포함 | - | - |
| 판매기간 | - | 목록 행에 포함 | - | - |
| 첨부파일 목록 | - | `onDownload(filecors, seq, '#n')` | - | - |
| 파일 다운로드 | POST | `/process/mFileDownload` | `pFilePath`,`pFidwSeq`(=`{seq}#{n}`) | PDF |

## 4. 필수 요청 정보

- Referer: 설정함(config 의 url)
- Origin: 불필요
- User-Agent: config.crawler.user_agent
- Cookie: 불필요
- 세션: 불필요
- CSRF: 없음
- 인코딩: EUC-KR
- 기타 헤더: 없음

## 5. 문서 링크 구조

- 약관: `#3` (보험약관 열)
- 사업방법서: `#2` (사업방법서 열)
- 상품요약서: `#1` (상품요약서 열)
- 상대 URL 여부: 해당 없음(폼 POST)
- JavaScript 함수 여부: `onDownload()`
- 파일명 획득 방법: `Content-Disposition`
- 한 상품에 여러 문서 존재 여부: 버전당 최대 3종

## 6. 구현 방식

- Adapter 파일: `crawler/adapters/ibk_life.py`
- 수집 방식: STATIC_HTML
- Playwright 사용 여부: 사용 안 함
- 선택한 구현 방식의 이유: 4개 화면 모두 서버 렌더링. 표 머리글을 읽어 열을 매핑(퇴직연금 화면은 열 구성이 다름)
- 공통 유틸리티 사용 내역: `common.soup/table_rows/clean/decode_body/js_call_args/parse_period`

## 7. 테스트 결과

- 대상 월: 2026-07
- 수집 상품 수: 571버전 수집(판매중 18 / 판매중지 553)
- 상품 버전 수: 2026-07 대상 **0**
- 약관 링크 수: 0
- 사업방법서 링크 수: 0
- 상품요약서 링크 수: 0
- 다운로드 성공 수: 3 (대상 월 외 상품으로 3종 각 1건 검증)
- 실패 수: 0
- 중복 수: 0
- 누락 또는 수동 검토 수: 0

## 8. 제한 사항

- WAF: 관측되지 않음
- CAPTCHA: 관측되지 않음
- 세션 만료: 관측되지 않음
- 조회 범위 제한: 없음
- 날짜 누락: 없음
- 문서 누락: 퇴직연금 화면의 `운용관리계약서`/`자산관리협정서` 열은 수집 3종이 아니므로 제외
- 기타 문제: **2026-07 판매개시 상품 0건**. 실측 판매개시월 분포: 2026-01 9건 / 2026-04 2건 / 2026-06 1건 / 2026-07 0건. 수집 누락이 아니라 실제 데이터가 없는 것

## 9. 확인 근거

- 확인한 화면: 판매상품(개인연금·퇴직연금), 판매중지상품(개인연금·퇴직연금) 4개 화면
- 확인한 Network 요청: `POST /process/mFileDownload`
- 테스트 상품: (무) IBK 하이브리드 연금저축보험_2601 (seq 675)
- 테스트 파일: (무)_IBK_하이브리드_연금저축보험_2601_약관.pdf — 200 / 5,074,354 bytes / `%PDF-1.6`
- 로그 위치: `99_운영/runs/{YYYY}/{MM}/{DD}/{run_id}/crawler.log`
