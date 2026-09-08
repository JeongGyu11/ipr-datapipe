# 삼성화재 상품공시실 분석

## 1. 기본 정보

- 보험사 코드: `SAMSUNG`
- 보험사명: 삼성화재
- 보험 구분: 손해보험(non_life)
- config URL: https://www.samsungfire.com/vh/page/VH.HPIF0103.do
- 실제 상품 목록 URL: https://www.samsungfire.com/vh/data/VH.HDIF0103.do
- 판매 중 상품 URL: `displayGb=1` 또는 `saleEnDt=99991231`
- 판매 중지 상품 URL: `displayGb=2` 또는 종료일 존재
- 확인일: 2026-07-31

## 2. 사이트 특징

- 렌더링 방식: JSON_API
- 상품 카테고리: 장기 / 일반보험 / 자동차 / 퇴직연금 / 퇴직보험 (`prdGun`)
- 판매채널 구분: `saleChannel`(대면/온라인/TM 등)
- 검색 조건: 없음(클라이언트 필터)
- 날짜 제공 방식: `saleStDt`, `saleEnDt`
- 페이지네이션 방식: 없음(1회 호출 9,404건)
- 상품 버전 표시 방식: `prdCode`+`jongGb`+`saleStDt`
- 이전 판매기간 제공 여부: 전량 응답에 포함
- 팝업 또는 모달 사용 여부: 없음

## 3. 실제 엔드포인트

| 구분 | 메서드 | 엔드포인트 | 주요 파라미터 | 응답 형식 |
|---|---|---|---|---|
| 세션 초기화 | GET | `/vh/page/VH.HPIF0103.do` | - | HTML |
| 상품 목록 | POST | `/vh/data/VH.HDIF0103.do` | `header={"tranId":"VH.HDIF0103"}` | JSON |
| 상품 상세 | - | 목록에 포함 | - | - |
| 판매기간 | - | 목록에 포함 | - | - |
| 첨부파일 목록 | - | `prdfilename1~4` | - | - |
| 파일 다운로드 | GET | `https://www.samsungfire.com{prdfilenameN}` | - | PDF |

## 4. 필수 요청 정보

- Referer: 설정함(config 의 url)
- Origin: 불필요
- User-Agent: config.crawler.user_agent
- Cookie: 불필요
- 세션: 불필요
- CSRF: 없음
- 인코딩: UTF-8
- 기타 헤더: `Content-Type: application/x-www-form-urlencoded;charset=UTF-8`, `X-Requested-With`

## 5. 문서 링크 구조

- 약관: `prdfilename1`
- 사업방법서: `prdfilename2`
- 상품요약서: `prdfilename3`
- 상대 URL 여부: 예(`/publication/pdf/...`)
- JavaScript 함수 여부: 없음
- 파일명 획득 방법: 경로 마지막 세그먼트
- 한 상품에 여러 문서 존재 여부: 상품 버전당 3종 각 1개

## 6. 구현 방식

- Adapter 파일: `crawler/adapters/samsung_insurance.py` (기존, 미변경)
- 수집 방식: JSON_API
- Playwright 사용 여부: 사용 안 함
- 선택한 구현 방식의 이유: 1회 호출로 전량 수집 가능
- 공통 유틸리티 사용 내역: 기존 Adapter 로 `common.py` 미사용

## 7. 테스트 결과

- 대상 월: 2026-07
- 수집 상품 수: 137
- 상품 버전 수: 137
- 약관 링크 수: 137
- 사업방법서 링크 수: 130
- 상품요약서 링크 수: 120
- 다운로드 성공 수: 표본 2건 검증
- 실패 수: 0
- 중복 수: 0
- 누락 또는 수동 검토 수: 4 (날짜 없음)

## 8. 제한 사항

- WAF: 관측되지 않음
- CAPTCHA: 관측되지 않음
- 세션 만료: 관측되지 않음
- 조회 범위 제한: 없음
- 날짜 누락: 4건 → `MANUAL_REVIEW_REQUIRED`
- 문서 누락: 없음
- 기타 문제: 응답 3MB 이상 → 타임아웃 120초 사용. 파일 없는 상품은 키 자체가 응답에 없음

## 판매상태 재검증 계약 (2026-08-20)

- **신뢰 상태 소스**: 전량 목록 API의 `displayGb`를 우선 사용합니다(`1`=판매중, `2`=판매중지). 그 외 값만 `saleEnDt`가 열린 기간인지로 판정합니다.
- **필요 상세 호출**: 별도 상세 호출은 하지 않으며 `POST /vh/data/VH.HDIF0103.do` 전량 응답을 사용합니다.
- **coverage 실패**: 목록 응답이 유효한 배열이 아니거나 요청이 실패하면 상태 coverage가 완료되지 않아 DB의 기존 문서 상태·폴더를 유지합니다. 날짜 미상 행도 버리지 않고 관찰 대상으로 남깁니다.
- **체크포인트**: 상품별 상세 체크포인트는 없습니다. 기존 `ACTIVE` 행은 전량 목록에서 다시 대조하므로 다음 실행에 새 목록 요청이 필요합니다.

## 9. 확인 근거

- 확인한 화면: 보험상품 공시 화면
- 확인한 Network 요청: `POST /vh/data/VH.HDIF0103.do`
- 테스트 상품: 상생 기후보험 (KR1656P, saleStDt 20260718)
- 테스트 파일: KR1656P_0_20260718_file1.pdf
- 로그 위치: `99_운영/runs/{YYYY}/{MM}/{DD}/{run_id}/crawler.log`
