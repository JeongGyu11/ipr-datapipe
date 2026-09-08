# 롯데손해보험 상품공시실 분석

## 1. 기본 정보

- 보험사 코드: `LOTTE`
- 보험사명: 롯데손해보험
- 보험 구분: 손해보험(non_life)
- config URL: https://www.lotteins.co.kr/web/C/D/H/cdh190.jsp
- 실제 상품 목록 URL: https://www.lotteins.co.kr/CChannelSvl (task=searchKey)
- 판매 중 상품 URL: `issale=Y` / 응답의 `searchviewissale` 표
- 판매 중지 상품 URL: `issale=N` / `searchviewisnotsale` 표
- 확인일: 2026-07-31

## 2. 사이트 특징

- 렌더링 방식: FORM_POST (응답은 HTML+JS injection)
- 상품 카테고리: 자동차(11) / 일반(1) / 장기(6) / 기타(1) — lcode·mcode 조합 19종
- 판매채널 구분: 별도 구분 없음
- 검색 조건: 상품명(`srcPrdNm`, EUC-KR 인코딩 필수)
- 날짜 제공 방식: 판매기간 컬럼(`YYYY.MM.DD ~ YYYY.MM.DD` 또는 `~ 현재`)
- 페이지네이션 방식: 없음(1회 조회로 4,391행)
- 상품 버전 표시 방식: 판매기간 행 단위
- 이전 판매기간 제공 여부: Step3/Step4 드릴다운으로 제공
- 팝업 또는 모달 사용 여부: 없음

## 3. 실제 엔드포인트

| 구분 | 메서드 | 엔드포인트 | 주요 파라미터 | 응답 형식 |
|---|---|---|---|---|
| 세션 초기화 | GET | `/web/C/D/H/cdh190.jsp` | - | HTML |
| 상품 목록 | POST | `/CChannelSvl` | `ops_tc=dfi.c.d.g.cmd.Cdg079Cmd`,`task=searchKey`,`issale`,`srcPrdNm` | HTML+JS |
| 상품 상세 | POST | `/CChannelSvl` | `task=gostep4issale`,`lcode`,`mcode`,`scode`,`startdate` | HTML+JS |
| 판매기간 | POST | `/CChannelSvl` | `task=gostep3issale` | HTML+JS |
| 첨부파일 목록 | - | 목록 응답에 `<a href>` 포함 | - | HTML |
| 파일 다운로드 | GET | `/upload/C/newProduct/*.pdf` | - | PDF |

## 4. 필수 요청 정보

- Referer: 설정함(config 의 url)
- Origin: 불필요
- User-Agent: config.crawler.user_agent
- Cookie: 불필요
- 세션: 불필요
- CSRF: 없음
- 인코딩: EUC-KR (UTF-8 로 보내면 한글 검색 0건)
- 기타 헤더: 없음

## 5. 문서 링크 구조

- 약관: `<img alt='약관'>` 링크
- 사업방법서: `alt='사업방법서'`
- 상품요약서: `alt='상품요약서'`
- 상대 URL 여부: 예(`/upload/...`)
- JavaScript 함수 여부: 없음(직접 링크)
- 파일명 획득 방법: URL 경로 마지막 세그먼트
- 한 상품에 여러 문서 존재 여부: 상품 버전당 3종 각 1개

## 6. 구현 방식

- Adapter 파일: `crawler/adapters/lotte_insurance.py` (기존, 미변경)
- 수집 방식: FORM_POST
- Playwright 사용 여부: 사용 안 함
- 선택한 구현 방식의 이유: 검색형 1회 조회가 드릴다운 대비 요청 수가 압도적으로 적음
- 공통 유틸리티 사용 내역: 기존 Adapter 로 `common.py` 미사용

## 7. 테스트 결과

- 대상 월: 2026-07
- 수집 상품 수: 49
- 상품 버전 수: 49
- 약관 링크 수: 49
- 사업방법서 링크 수: 48
- 상품요약서 링크 수: 48
- 다운로드 성공 수: 표본 2건 검증
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
- 기타 문제: 검색형 응답에 상품 내부 식별자가 없어 약관 파일명을 보조 식별자로 사용

## 판매상태 재검증 계약 (2026-08-20)

- **신뢰 상태 소스**: 검색형 `POST /CChannelSvl` 1회 응답 안의 `searchviewissale`(판매중)·`searchviewisnotsale`(판매중지) view를 사용합니다.
- **필요 상세 호출**: 별도 상품 상세 호출은 하지 않습니다. 두 상태 표와 문서 링크가 같은 응답에 포함됩니다.
- **coverage 실패**: 응답이 비어 있거나 알려진 view assignment가 없으면 수집을 실패시키며, 완전한 상태 목록으로 확인되지 않으므로 DB의 기존 문서 상태·폴더를 유지합니다. 정상 응답은 `status_coverage_complete=true`입니다.
- **체크포인트**: 상품별 상세 체크포인트는 없습니다. 상태 재검증 시 검색형 전체 응답을 새로 요청합니다.

## 9. 확인 근거

- 확인한 화면: 상품공시실 검색 화면
- 확인한 Network 요청: `POST /CChannelSvl`
- 테스트 상품: (무) let:click 실손의료보험Ⅴ(재가입용)(2607)
- 테스트 파일: 11_click_silson_5_2607_yak.pdf
- 로그 위치: `99_운영/runs/{YYYY}/{MM}/{DD}/{run_id}/crawler.log`
