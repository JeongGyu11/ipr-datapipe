# DB생명 상품공시실 분석

## 1. 기본 정보

- 보험사 코드: `DB_LIFE`
- 보험사명: DB생명
- 보험 구분: 생명보험(life)
- config URL: https://www.idblife.com/notice/product/sale
- 실제 상품 목록 URL: https://www.idblife.com/notice/product/sale
- 판매 중 상품 URL: `/notice/product/sale`
- 판매 중지 상품 URL: `/notice/product/sold_out`
- 확인일: 2026-08-20

## 2. 사이트 특징

- 렌더링 방식: STATIC_HTML
- 상품 카테고리: 보험종류(보장/연금/저축) × 보험유형(종신/실손/암·질병/치매·간병/저축/어린이/기타/연금)
- 판매채널 구분: `gubn1` 1=개인 / 2=단체 / 4=방카
- 검색 조건: 상품명(`product_name`) + 분류
- 판매중지 날짜 제공 방식: 목록 HTML에는 날짜가 없고, `mctg[name=mcode]` 분류 참조별 AJAX XML 상세의 `SALE_START_DATE`/`SALE_END_DATE`에 있음
- 페이지네이션 방식: `page` 파라미터, `data-total-page` 로 총 페이지 제공(개인 판매 78건 / 8페이지)
- 상품 버전 표시 방식: 행 단위(판매기간)
- 이전 판매기간 제공 여부: 판매중지 화면에 제공
- 팝업 또는 모달 사용 여부: 예(약관 팝업)

## 3. 실제 엔드포인트

| 구분 | 메서드 | 엔드포인트 | 주요 파라미터 | 응답 형식 |
|---|---|---|---|---|
| 세션 초기화 | GET | `/notice/product/sale` | - | HTML |
| 상품 목록 | GET | `/notice/product/sale`, `/notice/product/sold_out` | `gubn1`,`gubn2`,`gubn3`,`page` | HTML |
| 판매중지 분류 참조 | GET | `/notice/product/sold_out` | `gubn1`,`page` + `a.mctg[name=mcode][data-value]` | HTML |
| 판매중지 상품 상세 | POST | `/notice/product/sold_out/ajaxRequest` | form `mcode`,`gubn1` | XML (`poplist` 반복) |
| 판매기간 | POST 상세 응답 | `SALE_START_DATE`,`SALE_END_DATE` | `PRODUCT_NAME`,`PUBLISH_NO` 필수 | XML 필드 |
| 첨부파일 목록(판매중) | GET | `/notice/product/prov/sale/{provNo}` | - | HTML(팝업) |
| 첨부파일 목록(판매중지) | GET | `/notice/product/prov/soldOut/{PUBLISH_NO}` | - | HTML(팝업) |
| 파일 다운로드 | GET | `/notice/product/file/{publishNo}/{n}`, `/notice/product/prov/file` | `publishNo`,`fileGb`,`fileSeq` | PDF / ZIP |

## 4. 필수 요청 정보

- Referer: 설정함(config 의 url)
- Origin: 불필요
- User-Agent: config.crawler.user_agent
- Cookie: 불필요
- 세션: 불필요
- CSRF: 페이지에 `_csrf` 메타가 있으나 조회에는 불필요
- 인코딩: UTF-8
- 판매중지 AJAX 헤더: `Referer: https://www.idblife.com/notice/product/sold_out`, `X-Requested-With: XMLHttpRequest`, `Accept: application/xml,text/xml,*/*;q=0.01`

## 5. 문서 링크 구조

- 약관: 약관 팝업 안의 `prov/file?publishNo=&fileGb=&fileSeq=` 링크 **전부**(약관 취합 zip / 주계약 / 제도성 특약)
- 판매중/판매중지 사업방법서: `file/{publishNo}/1`
- 판매중 상품요약서: 목록 행의 `file/{publishNo}/2` (판매중지 상세 XML에는 상품요약서 필드가 없어 생성하지 않음)
- 상대 URL 여부: 예(`file/3239/1` → `/notice/product/file/3239/1`)
- JavaScript 함수 여부: 판매중지 행의 `mctg` 참조를 클릭하면 `ajaxRequest` POST, 문서 팝업은 `prov/soldOut/{PUBLISH_NO}`
- 파일명 획득 방법: `Content-Disposition`
- 한 상품에 여러 문서 존재 여부: **예** — 한 버전에 약관이 수십 개

## 6. 구현 방식

- Adapter 파일: `crawler/adapters/db_life.py`
- 수집 방식: STATIC_HTML
- Playwright 사용 여부: 사용 안 함
- 선택한 구현 방식의 이유: 서버 렌더링이라 HTML 파싱이 가장 단순하고 안정적
- 공통 유틸리티 사용 내역: `common.soup/table_rows/clean/parse_period/absolute`

## 7. 테스트 결과

- 동적 계약 확인일: 2026-08-20
- 자동화 검증: `tests/test_db_life_adapter.py` targeted 5 passed
- 판매중지 상세는 `gubn1|mcode` 체크포인트를 사용하며 완료된 참조는 재사용하고 실패한 참조만 재시도

## 8. 제한 사항

- WAF: 관측되지 않음
- CAPTCHA: 관측되지 않음
- 세션 만료: 관측되지 않음
- 조회 범위 제한: 없음
- 날짜 누락: 판매중지 목록에는 없으며 AJAX 상세에서 보완
- 판매중지 상품요약서: 상세 계약상 제공되지 않음
- 기타 문제: **구형 TLS** — 기본 SSL 컨텍스트로는 `WRONG_SIGNATURE_TYPE` 으로 연결 실패. `options.legacy_ssl: true` 필요. 약관 1순위 파일은 `.zip`(약관 취합본)

## 판매상태 재검증 계약 (2026-08-20)

- **신뢰 상태 소스**: `sale`(판매중)·`sold_out`(판매중지) 목록을 기본으로 사용하며, 판매중지 목록의 `mcode`·`gubn1`은 `sold_out/ajaxRequest` 상세로 보강합니다.
- **필요 상세 호출**: 판매중지 상품은 AJAX 상세 호출이 필요합니다. 기존 `ACTIVE`와 일치하는 캐시 결과는 상태 이동을 확인하기 위해 fresh 상세를 요청합니다.
- **coverage 실패**: 페이지 순회가 잘리지 않고 판매중지 상세 실패가 없어야 complete입니다. 실패·상한이면 DB의 기존 문서 상태·폴더를 유지하고 실패 상세만 재시도 대상으로 남깁니다.
- **체크포인트**: 판매중지 상세 성공은 `detail_checkpoint.jsonl`에서 재사용하지만, `ACTIVE`와 일치하는 캐시는 우회합니다. 판매중 목록은 별도 상세 체크포인트를 사용하지 않습니다.

## 9. 확인 근거

- 확인한 화면: 판매상품공시 / 판매중지상품공시 / 주계약 및 특약 약관 팝업
- 확인한 Network 요청: `GET /notice/product/sale?page=N`, `GET /notice/product/sold_out?page=N`, `POST /notice/product/sold_out/ajaxRequest` (`mcode`,`gubn1`), `GET /notice/product/prov/soldOut/{PUBLISH_NO}`
- 테스트 상품: (무) 10년 더 드림 플러스 유니버셜 간편종신보험(보증비용부과형)(2404)
- 테스트 파일: (무) …(2404).zip — 200 / 6,200,425 bytes / `PK\x03\x04`, 사업방법서 366,081 bytes / `%PDF-`
- 로그 위치: `99_운영/runs/{YYYY}/{MM}/{DD}/{run_id}/crawler.log`
