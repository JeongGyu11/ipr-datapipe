# KB라이프생명 상품공시실 분석

## 1. 기본 정보

- 보험사 코드: `KB_LIFE`
- 보험사명: KB라이프생명
- 보험 구분: 생명보험(life)
- config URL: https://www.kblife.co.kr/customer-common/productList.do
- 실제 상품 목록 URL: https://www.kblife.co.kr/customer-common/API/productList1.do
- 판매 중 상품 URL: `tabType=1` (판매상품)
- 판매 중지 상품 URL: `tabType=2` (판매중지상품)
- 확인일: 2026-07-31

## 2. 사이트 특징

- 렌더링 방식: JAVASCRIPT_RENDERED + JSON_API
- 상품 카테고리: 연금 / 보장 / 저축 / 변액 / 단체 / 특약 (`TYPE`)
- 판매채널 구분: `PER_TYPE`
- 검색 조건: 상품구분(`srchType`) + 상품명(`pdNm`)
- 날짜 제공 방식: `SALE_DATE`(`YYYY/MM/DD ~ YYYY/MM/DD`), `PROD_SALE_END_DATE`
- 페이지네이션 방식: `pageIndex`/`pageSize`, 응답 `pagingVO.finalPgNo`
- 상품 버전 표시 방식: `SEQNO` 단위(같은 `P_CODE` 의 판매기간별 행)
- 이전 판매기간 제공 여부: 제공
- 팝업 또는 모달 사용 여부: 없음(아코디언)

## 3. 실제 엔드포인트

| 구분 | 메서드 | 엔드포인트 | 주요 파라미터 | 응답 형식 |
|---|---|---|---|---|
| 세션 초기화 | GET | `/customer-common/productList.do` | - | HTML |
| 상품 목록 | POST | `/customer-common/API/productList1.do` | `pageSize`,`pageIndex`,`tabType`,`srchType`,`pdNm` | JSON |
| 상품 상세 | - | 목록에 포함 | - | - |
| 판매기간 | - | 목록에 포함 | - | - |
| 첨부파일 목록 | - | `UPFILE`,`UPFILE1~5` | - | - |
| 파일 다운로드 | GET | `/api/archive/archives/download/{fileno}/{SEQNO}/{boxno}` | - | PDF |

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

- 약관: `UPFILE2`(product-terms/2), `UPFILE3`(/8), `UPFILE4`(/9)
- 사업방법서: `UPFILE1`(product-explain/1)
- 상품요약서: `UPFILE`(product-explain/0)
- 상대 URL 여부: 예
- JavaScript 함수 여부: `downFile` 클래스 클릭 핸들러
- 파일명 획득 방법: `Content-Disposition`
- 한 상품에 여러 문서 존재 여부: **예** — 약관이 최대 3개(`UPFILE2~4`)

## 6. 구현 방식

- Adapter 파일: `crawler/adapters/kb_life.py`
- 수집 방식: JSON_API
- Playwright 사용 여부: 사용 안 함
- 선택한 구현 방식의 이유: 필드↔문서유형 매핑을 화면 스크립트 `/res/pc/js/customer-common/productList.js` 에서 직접 확인
- 공통 유틸리티 사용 내역: `common.parse_period`

## 7. 테스트 결과

- 대상 월: 2026-07
- 수집 상품 수: 1,247버전 수집(판매중 148 / 판매중지 1,099)
- 상품 버전 수: 2026-07 대상 110
- 약관 링크 수: 111
- 사업방법서 링크 수: 110
- 상품요약서 링크 수: 96
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
- 문서 누락: `UPFILE5`(상품설명서)는 기본 제외 대상
- 기타 문제: 없음

## 9. 확인 근거

- 확인한 화면: 상품공시 > 상품 목록(판매상품 / 판매중지상품 탭)
- 확인한 Network 요청: `POST /customer-common/API/productList1.do`, `GET /api/archive/archives/download/product-explain/501618196/0`
- 테스트 상품: KB 넥스트 레벨업 연금보험 무배당(미보증형) (SEQNO 501618196)
- 테스트 파일: KBL011_KB 넥스트 레벨업 연금보험 무배당.pdf — 200 / 4,109,128 bytes / `%PDF-`
- 로그 위치: `99_운영/runs/{YYYY}/{MM}/{DD}/{run_id}/crawler.log`
