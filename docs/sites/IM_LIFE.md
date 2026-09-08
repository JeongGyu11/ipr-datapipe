# iM라이프 상품공시실 분석

## 1. 기본 정보

- 보험사 코드: `IM_LIFE`
- 보험사명: iM라이프
- 보험 구분: 생명보험(life)
- config URL: https://www.imlifeins.co.kr/BA/BA_A020.do
- 실제 상품 목록 URL: https://www.imlifeins.co.kr/BA/BA_A020.do (POST)
- 판매 중 상품 URL: `sellType=1`
- 판매 중지 상품 URL: `sellType=0`
- 확인일: 2026-07-31

## 2. 사이트 특징

- 렌더링 방식: FORM_POST
- 상품 카테고리: 보장성 / 연금 / 변액 (표의 `구분` 열)
- 판매채널 구분: 개인 / 단체 / 독립특약 (표 caption 으로 구분)
- 검색 조건: 상품명
- 날짜 제공 방식: `판매개시일` / `판매중지일` 열
- 페이지네이션 방식: 없음(한 응답에 전체)
- 상품 버전 표시 방식: 행 단위
- 이전 판매기간 제공 여부: 상품별 여러 행
- 팝업 또는 모달 사용 여부: 없음

## 3. 실제 엔드포인트

| 구분 | 메서드 | 엔드포인트 | 주요 파라미터 | 응답 형식 |
|---|---|---|---|---|
| 세션 초기화 | GET | `/BA/BA_A020.do` | - | HTML |
| 상품 목록 | POST | `/BA/BA_A020.do` | `sellType=1\|0` | HTML |
| 상품 상세 | - | 목록 행에 포함 | - | - |
| 판매기간 | - | 목록 행에 포함 | - | - |
| 첨부파일 목록 | - | `fileDownload('/Download/…pdf')` | - | - |
| 파일 다운로드 | POST | `/www/downloadChk.do` | `fileName` | PDF |

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

- 약관: `보험약관` 열
- 사업방법서: `사업방법서` 열
- 상품요약서: `상품요약서` 열
- 상대 URL 여부: 해당 없음(폼 POST)
- JavaScript 함수 여부: `fileDownload(fileName)`
- 파일명 획득 방법: `Content-Disposition`(URL 인코딩)
- 한 상품에 여러 문서 존재 여부: 버전당 최대 3종

## 6. 구현 방식

- Adapter 파일: `crawler/adapters/im_life.py`
- 수집 방식: FORM_POST
- Playwright 사용 여부: 사용 안 함
- 선택한 구현 방식의 이유: `sellType` 두 번의 POST 로 전량 수집 가능
- 공통 유틸리티 사용 내역: `common.soup/table_rows/clean/js_call_args`

## 7. 테스트 결과

- 대상 월: 2026-07
- 수집 상품 수: 1,595버전 수집(판매중 개인 48·단체 13 / 판매중지 개인 1,236·단체 197·독립특약 101)
- 상품 버전 수: 2026-07 대상 9
- 약관 링크 수: 9
- 사업방법서 링크 수: 9
- 상품요약서 링크 수: 9
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
- 기타 문제: 다운로드가 URL 이 아닌 폼 POST 라 DB의 `document_url` 은 비어 있고 `source_metadata.download_hint` 로 처리

## 9. 확인 근거

- 확인한 화면: 공시실 > 상품공시실 > 전체상품공시(판매 중 / 판매 중지 탭, 개인 / 단체 탭)
- 확인한 Network 요청: `POST /BA/BA_A020.do`, `POST /www/downloadChk.do`
- 테스트 상품: SMART유니버셜종신보험 무배당 2601(보증비용부과형) (2026-07-01)
- 테스트 파일: 20260701_SMART유니버셜종신보험무배당2601(보증비용부과형).pdf — 200 / 3,508,753 bytes / `%PDF-`
- 로그 위치: `99_운영/runs/{YYYY}/{MM}/{DD}/{run_id}/crawler.log`
