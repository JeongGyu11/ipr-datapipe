# 하나생명 상품공시실 분석

## 1. 기본 정보

- 보험사 코드: `HANA_LIFE`
- 보험사명: 하나생명
- 보험 구분: 생명보험(life)
- config URL: https://www.hanalife.co.kr/anm/product/allProduct.do?status=on
- 실제 상품 목록 URL: 같음
- 판매 중 상품 URL: `status=on`
- 판매 중지 상품 URL: `status=off`
- 확인일: 2026-07-31

## 2. 사이트 특징

- 렌더링 방식: FORM_POST
- 상품 카테고리: 분류 열(연금/보장 등)
- 판매채널 구분: `대상` 열(개인/단체)
- 검색 조건: 대상(`object`), 분류(`gubun`), 기준일(`yyyy`/`mm`/`dd`), 상품명
- 날짜 제공 방식: `판매기간` 열 `YYYY.MM.DD -`
- 페이지네이션 방식: `pageIndex` 파라미터가 있으나 **실측상 무시되고 전체 행 반환**(판매 40행 / 판매중지 1,454행)
- 상품 버전 표시 방식: 행 단위
- 이전 판매기간 제공 여부: 판매중지 화면에 제공
- 팝업 또는 모달 사용 여부: 없음

## 3. 실제 엔드포인트

| 구분 | 메서드 | 엔드포인트 | 주요 파라미터 | 응답 형식 |
|---|---|---|---|---|
| 세션 초기화 | GET | `/anm/product/allProduct.do?status=on` | - | HTML |
| 상품 목록 | POST | `/anm/product/allProduct.do` | `status`,`object`,`gubun`,`pageIndex` | HTML |
| 상품 상세 | - | 목록 행에 포함 | - | - |
| 판매기간 | - | 목록 행에 포함 | - | - |
| 첨부파일 목록 | - | 행의 `<a href>` | - | - |
| 파일 다운로드 | GET | `/home/download2.do`(요약서·방법서), `/anm/product/download.do`(약관) | `fileName`,`downFileName` / `code`,`seq` | PDF |

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

- 약관: `/anm/product/download.do?code=&seq=`
- 사업방법서: `/home/download2.do?fileName=…_사업방법서…`
- 상품요약서: `/home/download2.do?fileName=…_상품요약서…`
- 상대 URL 여부: 예
- JavaScript 함수 여부: 없음(직접 링크)
- 파일명 획득 방법: `downFileName` 쿼리 파라미터 사용
- 한 상품에 여러 문서 존재 여부: 버전당 3종

## 6. 구현 방식

- Adapter 파일: `crawler/adapters/hana_life.py`
- 수집 방식: FORM_POST
- Playwright 사용 여부: 사용 안 함
- 선택한 구현 방식의 이유: status 두 번의 POST 로 전량 수집 가능
- 공통 유틸리티 사용 내역: `common.soup/table_rows/clean/parse_period/absolute`

## 7. 테스트 결과

- 대상 월: 2026-07
- 수집 상품 수: 40버전(판매중) + 1,454행(판매중지)
- 상품 버전 수: 2026-07 대상 11
- 약관 링크 수: 11
- 사업방법서 링크 수: 11
- 상품요약서 링크 수: 11
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
- 기타 문제: 약관 다운로드의 `Content-Disposition` 이 EUC-KR 원문이라 파일명이 깨짐. 저장 파일명은 크롤러가 조립하므로 저장에는 영향 없고 DB의 `original_filename` 만 영향

## 9. 확인 근거

- 확인한 화면: 상품공시실 > 전체상품 목록(판매상품 / 판매중지상품)
- 확인한 Network 요청: `POST /anm/product/allProduct.do`
- 테스트 상품: R(무)하나로 라이트 3.10.5 간편건강보험 (code 611013)
- 테스트 파일: R(무)하나로 라이트 3.10.5 간편건강보험_상품요약서.pdf — 200 / 4,325,085 bytes / `%PDF-`
- 로그 위치: `99_운영/runs/{YYYY}/{MM}/{DD}/{run_id}/crawler.log`
