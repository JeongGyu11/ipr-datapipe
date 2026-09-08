# REGRESSION_TEST_RESULT.md — 회귀 및 신규 테스트 결과

> **Historical Snapshot — 2026-08-04** (실행 기록: 2026-07-31)
> 이 문서는 해당 시점의 테스트·dry-run 결과를 보존한 역사 기록입니다. 현재 운영 상태와
> 실행 방법의 정본은 `README.md` 및 `docs/ENDPOINT_MATRIX.md`를 확인하세요.
> 본문에 등장하는 `scratchpad/*`는 저장소 외부의 당시 조사 증적이며 현재 실행할 수 없습니다.

> ⚠️ 역사적 기록 안내: 이 문서는 **과거 layout v1/당시 검증 기록**입니다. 현재 경로와
> 실행 명령은 `README.md`를 참조하세요.

> 실행일: **2026-07-31**, 대상 월 `2026-07`
> 비교 기준: `docs/BASELINE_RESULT.md` (신규 Adapter 추가 **이전** 상태)

---

## 1. pytest

| 시점 | 결과 |
|---|---|
| 확장 전(baseline) | **119 passed / 5 skipped / 0 failed** |
| 확장 후(기존 테스트만) | **119 passed / 5 skipped / 0 failed** |
| 확장 후(신규 테스트 포함) | **149 passed / 5 skipped / 0 failed** |

- 기존 테스트 파일은 **수정하지 않았습니다.** 실패도 없습니다.
- 신규 추가: `tests/test_adapter_common.py` — 신규 Adapter 공통 유틸의
  판매기간 파서 / JavaScript 인자 파서 / 상대 URL 변환 / 응답 인코딩 처리를 검증합니다.
  테스트 케이스는 전부 실제 사이트에서 관측한 문자열을 사용합니다.

---

## 2. 기존 5개사 회귀 (§17.1)

```bash
python main.py --target-month 2026-07 --company DB --company LOTTE --company SAMSUNG --dry-run
python main.py --target-month 2026-07 --company MERITZ --dry-run
```

| 코드 | 항목 | Baseline(확장 전) | 확장 후 | 판정 |
|---|---|---:|---:|---|
| DB | 전체 수집 버전 | 6 | 6 | ✅ 동일 |
| DB | 대상 월 선정 | 6 | 6 | ✅ 동일 |
| DB | 문서 링크 | 18 | 18 | ✅ 동일 |
| LOTTE | 전체 수집 버전 | 4,391 | 4,391 | ✅ 동일 |
| LOTTE | 대상 월 선정 | 49 | 49 | ✅ 동일 |
| LOTTE | 문서 링크 | 145 | 145 | ✅ 동일 |
| MERITZ | 전체 수집 버전 | 183 | 183 | ✅ 동일 |
| MERITZ | 대상 월 선정 | 183 | 183 | ✅ 동일 |
| MERITZ | 문서 링크 | 491(2026-07-31 이전 기록) | 495 | ⚠️ +4 — Adapter 미변경. 사이트 데이터 변동으로 판단 |
| SAMSUNG | 전체 수집 버전 | 9,404 | 9,404 | ✅ 동일 |
| SAMSUNG | 대상 월 선정 | 137 | 137 | ✅ 동일 |
| SAMSUNG | 문서 링크 | 387 | 387 | ✅ 동일 |
| KB | 동작 방식 | 전 상품 상세 순회(약 2시간 30분) | 동일 | ✅ 코드 미변경 |

### 검증 항목 점검

| 항목 | 결과 |
|---|---|
| 상품 수 급감 | 없음 |
| 문서 링크 수 급감 | 없음 |
| 다운로드 URL 변경 | 없음 (DB `cYakgwanDown.do`, LOTTE `/upload/C/newProduct/*.pdf`, SAMSUNG `{prdfilenameN}` 그대로) |
| 파일 저장 구조 변경 | 없음 (`{월}/{보험사}/{상품}/{버전키}/{문서유형}/…` 그대로) |
| manifest 컬럼 변경 | 없음 (28개 그대로) |
| 기존 테스트 실패 | 없음 |

### KB손해보험 회귀에 대한 주의

KB 는 전량 dry-run 에 약 2시간 30분이 걸립니다. 본 회차에서는 baseline 실행을 1,950/3,994 상품
지점까지 진행한 뒤 중단하고(다른 검증에 시간을 배분), **코드가 한 줄도 변경되지 않았다는 점**과
`--max-products` 를 적용한 전체 실행(§5)으로 정상 동작을 확인했습니다.
KB 전량 회귀가 필요하면 아래를 실행하세요.

```bash
python main.py --target-month 2026-07 --company KB --dry-run
```

---

## 3. 신규 보험사 Dry-run (§17.2)

| 코드 | 기존·신규 | Dry-run | 다운로드 | 테스트 상품 | 약관 | 사업방법서 | 상품요약서 | 오류 | 최종 결과 |
|---|---|---|---|---|--:|--:|--:|--|---|
| DB | 기존 | ✅ 6버전 | ✅ | 무배당 프로미라이프 간편건강보험(일반심사형)2607 | 6 | 6 | 6 | - | EXISTING_WORKING |
| LOTTE | 기존 | ✅ 49버전 | ✅ | (무) 미니암보험(2604) | 49 | 48 | 47 | - | EXISTING_WORKING |
| MERITZ | 기존 | ✅ 183버전 | ✅ | Readycar개인용자동차보험 | 183 | 179 | 133 | - | EXISTING_WORKING |
| KB | 기존 | ✅(장시간) | ✅ | KB주택화재보험 | - | - | - | - | EXISTING_WORKING |
| SAMSUNG | 기존 | ✅ 137버전 | ✅ | 상생 기후보험 | 137 | 136 | 114 | - | EXISTING_WORKING |
| KYOBO_LIFE | 신규 | ✅ 표본 74버전 | ✅ 2건 | (무)119생활보험(BYC) | ✅ | ✅ | 표본 내 없음 | - | IMPLEMENTED |
| MIRAE_LIFE | 신규 | ✅ 5,539→294 | ✅ 3건 | 미래에셋생명 변액연금보험 무배당 | 35 | 46 | 46 | - | IMPLEMENTED |
| DB_LIFE | 신규 | ✅ 62→26 | ✅ 3건 | (무) 10년 더 드림 플러스 유니버셜 간편종신보험(2404) | 1,463 | 26 | 23 | - | IMPLEMENTED |
| IBK_LIFE | 신규 | ✅ 571→0 | ✅ 3건 | (무) IBK 하이브리드 연금저축보험_2601 | 0 | 0 | 0 | - | IMPLEMENTED |
| IM_LIFE | 신규 | ✅ 1,595→9 | ✅ 3건 | SMART유니버셜종신보험 무배당 2601 | 9 | 9 | 9 | - | IMPLEMENTED |
| KB_LIFE | 신규 | ✅ 1,247→110 | ✅ 3건 | KB 넥스트 레벨업 연금보험 무배당(미보증형) | 111 | 110 | 96 | - | IMPLEMENTED |
| METLIFE | 신규 | ✅ 690→39 | ✅ 3건 | 무배당 더해주고채워주는정기보험 | 39+특약 | 39 | 39 | - | IMPLEMENTED |
| HANA_LIFE | 신규 | ✅ 40→11 | ✅ 3건 | R(무)하나로 라이트 3.10.5 간편건강보험 | 11 | 11 | 11 | - | IMPLEMENTED |
| HANA_NON_LIFE | 신규 | ✅ 3,078→60 | ✅ 3건 | 무배당 하나더퍼스트 3.0.5 간편 건강보험(2601) 1종 | 60 | 60 | 58 | - | IMPLEMENTED |
| HYUNDAI_MARINE | 신규 | ✅ 6,873→69 | ✅ 3건 | 전기차화재안심보험 | 68 | 69 | 62 | - | IMPLEMENTED |
| HEUNGKUK_FIRE | 신규 | ✅ 2,348버전 | ✅ 3건 | 제도성 특별약관(유병력자실손의료보험 중지 및 재개(26.07)) | ✅ | ✅ | ✅ | - | IMPLEMENTED |
| ABL_LIFE | 신규 | ❌ | ❌ | - | - | - | - | 목록 XHR 미확인 | MANUAL_REVIEW_REQUIRED |
| KDB_LIFE | 신규 | ❌ | ❌ | - | - | - | - | 다운로드 엔드포인트 미확인 | MANUAL_REVIEW_REQUIRED |
| NH_LIFE | 신규 | ❌ | ❌ | - | - | - | - | 목록 엔드포인트 미확인 | MANUAL_REVIEW_REQUIRED |
| TONGYANG_LIFE | 신규 | ❌ | ❌ | - | - | - | - | 목록 화면 미확정 | MANUAL_REVIEW_REQUIRED |
| LINA_LIFE | 신규 | ❌ | ❌ | - | - | - | - | 주계약 목록 API 미확인 | MANUAL_REVIEW_REQUIRED |
| SAMSUNG_LIFE | 신규 | ❌ | ❌ | - | - | - | - | 요청 파라미터 암호화 | ACCESS_DENIED |
| SHINHAN_LIFE | 신규 | ❌ | ❌ | - | - | - | - | 목록 화면 scrnId 미확인 | MANUAL_REVIEW_REQUIRED |
| FUBON_HYUNDAI_LIFE | 신규 | ❌ | ❌ | - | - | - | - | 공시 화면 URL 미확인 | MANUAL_REVIEW_REQUIRED |
| HANWHA_LIFE | 신규 | ❌ | ❌ | - | - | - | - | config URL 이 홈으로 리다이렉트 | MANUAL_REVIEW_REQUIRED |
| HEUNGKUK_LIFE | 신규 | ❌ | ❌ | - | - | - | - | 조회 폼 파라미터 미확인 | MANUAL_REVIEW_REQUIRED |
| LINA_NON_LIFE | 신규 | ❌ | ❌ | - | - | - | - | 상품 목록 화면 미확인 | MANUAL_REVIEW_REQUIRED |
| AIG | 신규 | ❌ | ❌ | - | - | - | - | 목록 XHR 미확인 | MANUAL_REVIEW_REQUIRED |
| NH_FIRE | 신규 | ❌ | ❌ | - | - | - | - | 조회 엔드포인트 미확인 | MANUAL_REVIEW_REQUIRED |
| HANWHA_FIRE | 신규 | ❌ | ❌ | - | - | - | - | 요청 본문 암호화 | ACCESS_DENIED |

> 약관·사업방법서·상품요약서 숫자는 **대상 월(2026-07) 선정 버전의 문서 링크 수**입니다.
> `IBK_LIFE` 의 0 은 수집 실패가 아니라 **2026-07 판매개시 상품이 실제로 없기** 때문입니다
> (`docs/sites/IBK_LIFE.md` §8 에 판매개시월 분포 실측치 기재).

---

## 4. 실제 다운로드 테스트 결과 (§17.3)

3종(약관·사업방법서·상품요약서)을 각각 최소 1건 실제로 내려받아 선두 바이트와 크기를 확인했습니다.

| 코드 | 문서유형 | HTTP | 크기(bytes) | 선두 | 원본 파일명 |
|---|---|--:|--:|---|---|
| METLIFE | POLICY | 200 | 2,465,495 | `%PDF-` | 무배당 더해주고채워주는정기보험_12284_20260701.pdf |
| METLIFE | METHOD | 200 | 150,153 | `%PDF-` | 14_01_사업방법서_무배당더해주고채워주는정기보험_202602.pdf |
| METLIFE | SUMMARY | 200 | 264,416 | `%PDF-` | 상품요약서_무배당더해주고채워주는정기보험_20260701_v1_특약수정.pdf |
| IM_LIFE | POLICY | 200 | 3,508,753 | `%PDF-` | 20260701_SMART유니버셜종신보험무배당2601(보증비용부과형).pdf |
| IM_LIFE | METHOD | 200 | 116,220 | `%PDF-` | 260701_SMART유니버셜종신보험…_사업방법서.pdf |
| IM_LIFE | SUMMARY | 200 | 163,327 | `%PDF-` | 260701_SMART유니버셜종신보험…_상품요약서.pdf |
| KB_LIFE | POLICY | 200 | 4,109,128 | `%PDF-` | KBL011_KB 넥스트 레벨업 연금보험 무배당.pdf |
| KB_LIFE | METHOD | 200 | 339,298 | `%PDF-` | 20260701_주계약┃KB 넥스트 레벨업 연금보험 무배당┃3_사업방법서 별지.pdf |
| KB_LIFE | SUMMARY | 200 | 640,064 | `%PDF-` | 20260701_상품요약서_KB 넥스트 레벨업 연금보험 무배당_vf.pdf |
| IBK_LIFE | POLICY | 200 | 5,074,354 | `%PDF-` | (무)_IBK_하이브리드_연금저축보험_2601_약관.pdf |
| IBK_LIFE | METHOD | 200 | 394,212 | `%PDF-` | (무)_IBK_하이브리드_연금저축보험_2601_사업방법서.pdf |
| IBK_LIFE | SUMMARY | 200 | 434,294 | `%PDF-` | (무)_IBK_하이브리드_연금저축보험_2601_상품요약서.pdf |
| HANA_LIFE | POLICY | 200 | 21,865,468 | `%PDF-` | (EUC-KR 원문이라 깨짐 — `docs/sites/HANA_LIFE.md` §8) |
| HANA_LIFE | METHOD | 200 | 452,715 | `%PDF-` | R(무)하나로 라이트 3.10.5 간편건강보험_사업방법서.pdf |
| HANA_LIFE | SUMMARY | 200 | 4,325,085 | `%PDF-` | R(무)하나로 라이트 3.10.5 간편건강보험_상품요약서.pdf |
| HYUNDAI_MARINE | POLICY | 200 | 616,581 | `%PDF-` | 03.약관_20260701_전기차화재안심보험.pdf |
| HYUNDAI_MARINE | METHOD | 200 | 64,588 | `%PDF-` | 02.사업방법서별지_20260701_전기차화재안심보험.pdf |
| HYUNDAI_MARINE | SUMMARY | 200 | 367,683 | `%PDF-` | 상품요약서_260216_00.pdf |
| DB_LIFE | POLICY | 200 | 6,200,425 | `PK\x03\x04` | (무) 10년 더 드림…(2404).zip (약관 취합본) |
| DB_LIFE | METHOD | 200 | 366,081 | `%PDF-` | (무)10년 더 드림…_사업방법서.pdf |
| DB_LIFE | SUMMARY | 200 | 371,248 | `%PDF-` | (무)10년 더 드림…_상품요약서_2607.pdf |
| MIRAE_LIFE | POLICY | 200 | 4,215,194 | `%PDF-` | 미래에셋생명+변액연금보험+무배당_약관_20260711.pdf |
| MIRAE_LIFE | METHOD | 200 | 7,047,002 | `%PDF-` | 미래에셋생명+변액연금보험+무배당_사업방법서_20260711.pdf |
| MIRAE_LIFE | SUMMARY | 200 | 6,539,650 | `%PDF-` | 미래에셋생명+변액연금보험+무배당_상품요약서_20260711.pdf |
| HEUNGKUK_FIRE | POLICY | 200 | 113,182 | `%PDF-` | 제도성+특별약관(…)+기초서류.pdf |
| HEUNGKUK_FIRE | METHOD | 200 | 113,182 | `%PDF-` | 제도성+특별약관(…)+기초서류.pdf |
| HEUNGKUK_FIRE | SUMMARY | 200 | 102,550 | `%PDF-` | 무배당+흥Good+행복자산만들기+저축보험(26.01)_20260701이후_상품요약서.pdf |
| KYOBO_LIFE | POLICY | 200 | 3,843,291 | `%PDF-` | (무)119생활보험(98.04.01).pdf |
| KYOBO_LIFE | METHOD | 200 | 23,995 | `%PDF-` | (무)2006서포터스보장보험(2003.03)03.pdf |
| KYOBO_LIFE | SUMMARY | - | - | - | 표본 25개 상품 내 요약서 제공 상품 없음 |
| HANA_NON_LIFE | POLICY | 200 | 5,519,191 | `%PDF-` | 60706_20260701_01.pdf |
| HANA_NON_LIFE | METHOD | 200 | 448,296 | `%PDF-` | 60706_20260701_02.pdf |
| HANA_NON_LIFE | SUMMARY | 200 | 350,311 | `%PDF-` | 60706_20260701_03.pdf |

- 실제 다운로드 성공: **32건** / 실패: **0건**
- `NO_DOCUMENT_LINK` 로 기록해야 하는 사례: KYOBO_LIFE 표본 내 상품요약서(구상품은 미제공)

---

## 5. 전체 30개사 Dry-run (§17.4)

```bash
python main.py --target-month 2026-07 --dry-run --max-products 20
```

`--max-products 20` 은 KB·KYOBO_LIFE·HANA_NON_LIFE 처럼 전 상품 상세를 순회해야 하는
보험사의 실행 시간을 줄이기 위한 **테스트용 상한**이며, 적용 시 결과에 `coverage_capped` 로 남습니다.

### 5.1 오류 격리 확인

당시 Adapter 가 없었던 14개사는 실행 시작 시 경고 후 건너뛰고 **전체 실행은 계속**되었습니다(역사적 실측 로그).

```
2026-07-31 17:11:04 [WARNING] Adapter 가 없는 보험사 코드입니다: LINA_NON_LIFE
2026-07-31 17:11:04 [WARNING] Adapter 가 없는 보험사 코드입니다: AIG
2026-07-31 17:11:04 [WARNING] Adapter 가 없는 보험사 코드입니다: NH_FIRE
2026-07-31 17:11:04 [WARNING] Adapter 가 없는 보험사 코드입니다: HANWHA_FIRE
2026-07-31 17:11:04 [WARNING] Adapter 가 없는 보험사 코드입니다: ABL_LIFE
2026-07-31 17:11:04 [WARNING] Adapter 가 없는 보험사 코드입니다: KDB_LIFE
2026-07-31 17:11:04 [WARNING] Adapter 가 없는 보험사 코드입니다: NH_LIFE
2026-07-31 17:11:04 [WARNING] Adapter 가 없는 보험사 코드입니다: TONGYANG_LIFE
2026-07-31 17:11:04 [WARNING] Adapter 가 없는 보험사 코드입니다: LINA_LIFE
2026-07-31 17:11:04 [WARNING] Adapter 가 없는 보험사 코드입니다: SAMSUNG_LIFE
2026-07-31 17:11:04 [WARNING] Adapter 가 없는 보험사 코드입니다: SHINHAN_LIFE
2026-07-31 17:11:04 [WARNING] Adapter 가 없는 보험사 코드입니다: FUBON_HYUNDAI_LIFE
2026-07-31 17:11:04 [WARNING] Adapter 가 없는 보험사 코드입니다: HANWHA_LIFE
2026-07-31 17:11:04 [WARNING] Adapter 가 없는 보험사 코드입니다: HEUNGKUK_LIFE
2026-07-31 17:11:04 [INFO] [DB] DB손해보험 수집 시작 (2026-07-01 ~ 2026-07-31)
```

보험사 단위 예외는 `CrawlerManager._run_company()` 의 `except Exception` 에서 잡아
`errors.jsonl` 과 manifest 에 기록한 뒤 다음 보험사로 진행합니다(기존 구조, 변경 없음).

### 5.2 하나손해보험(HANA_NON_LIFE) — 성능 문제와 해결 (2026-08-04)

30개사 일괄 실행을 먼저 시도했으나 `HANA_NON_LIFE` 한 곳이 실행 시간을 지배해 중단했습니다.
`--max-products 20`(분류당 상한)을 적용해도 실측 속도는 다음과 같았습니다.

```
17:17:35 [HANA_NON_LIFE] 하나손해보험 수집 시작
17:17:37 [HANA_NON_LIFE] 판매중 / 자동차보험 개인용 -> 상품 4건
17:27:27 [HANA_NON_LIFE] 판매중 / 자동차보험 업무용 -> 상품 5건
17:38:07 [HANA_NON_LIFE] 판매중 / 자동차보험 영업용 -> 상품 2건
17:41:27 [HANA_NON_LIFE] 판매중 / 자동차보험 이륜차 -> 상품 4건
```

- **24분 동안 4개 세부분류(15개 상품)만 처리** → 전량 실행을 중단했습니다.
- **원인은 사이트가 아니라 어댑터 설계**였습니다. 첫 구현은 `collect_product_versions()` 안에서
  판매기간마다 `getSaleStepFour.json` 을 호출했는데, STEP3 응답에 이미
  `sSaleStrDt`/`sSaleEndDt` 가 들어 있어 대상 월 판정에는 STEP4 가 필요 없습니다.
- **조치**: STEP4 를 `collect_documents()` 로 옮겨 `CrawlerManager` 가 **대상 월로 선정한 버전에만**
  호출하도록 변경했습니다. 요청 수 약 4,000회 → **약 972회**.

```
$ python main.py --target-month 2026-07 --company HANA_NON_LIFE --dry-run
14:27:12 [HANA_NON_LIFE] 하나손해보험 수집 시작 (2026-07-01 ~ 2026-07-31)
14:31:41 [HANA_NON_LIFE] 판매중 12개 세부분류 완료          ← 이전엔 4개에 24분
14:57:35 [HANA_NON_LIFE] 상품 버전 3078건 수집
14:57:35 [HANA_NON_LIFE] 수집 3078건 -> 대상 월 선정 60건
소요 시간 : 1944.9초 / 문서 링크 178건 / 상태 {"DRY_RUN": 178} / 실패 0건
```

- 실제 다운로드 3종도 성공해 상태를 **`PARTIAL` → `IMPLEMENTED`** 로 승격했습니다(§4).

### 5.3 29개사 일괄 실행 (HANA_NON_LIFE 제외)

```bash
python main.py --target-month 2026-07 --dry-run --max-products 20 \
  --company DB --company LOTTE --company MERITZ --company KB --company SAMSUNG \
  --company KYOBO_LIFE --company MIRAE_LIFE --company DB_LIFE --company IBK_LIFE \
  --company IM_LIFE --company KB_LIFE --company METLIFE --company HANA_LIFE \
  --company HYUNDAI_MARINE --company HEUNGKUK_FIRE \
  --company ABL_LIFE --company KDB_LIFE --company NH_LIFE --company TONGYANG_LIFE \
  --company LINA_LIFE --company SAMSUNG_LIFE --company SHINHAN_LIFE \
  --company FUBON_HYUNDAI_LIFE --company HANWHA_LIFE --company HEUNGKUK_LIFE \
  --company LINA_NON_LIFE --company AIG --company NH_FIRE --company HANWHA_FIRE
```

실행 로그: `scratchpad/full29_dryrun.txt` — **정상 종료(exit 0), 소요 1,375.2초**

> 위 실행 로그와 결과 경로는 당시 layout v1의 **legacy 기록**이며 현재 운영 경로가 아닙니다.
> 현재 실행 요약은 `99_운영/runs/{YYYY}/{MM}/{DD}/{run_id}/summary.json`, 문서 최신
> 상태는 PostgreSQL `rs_disclosure_documents`를 사용합니다. 아래 legacy manifest 경로는
> 현재 런타임이 생성하거나 읽지 않습니다.

| 코드 | 전체 수집 | 대상 월 선정 | 문서 레코드 | 상태 |
|---|---:|---:|---:|---|
| DB | 9 | 9 | 27 | DUPLICATE_SKIPPED 18 / DRY_RUN 9 |
| LOTTE | 4,391 | 49 | 145 | DUPLICATE_SKIPPED 6 / DRY_RUN 139 |
| MERITZ | 183 | 183 | 495 | DUPLICATE_SKIPPED 6 / DRY_RUN 489 |
| KB | 1 (상한 20개 상품) | 1 | 2 | DUPLICATE_SKIPPED 2 · `coverage_capped` |
| SAMSUNG | 9,404 | 137 | 387 | DRY_RUN 379 / MANUAL_REVIEW_REQUIRED 4 |
| HYUNDAI_MARINE | 6,873 | 69 | 199 | DRY_RUN 197 / MANUAL_REVIEW_REQUIRED 2 |
| HEUNGKUK_FIRE | 3,834 | 63 | 173 | DRY_RUN 173 |
| KYOBO_LIFE | 64 (상한 20개 상품) | 0 | 0 | `coverage_capped` |
| MIRAE_LIFE | 5,539 | 294 | 375 | DRY_RUN 90 / MANUAL_REVIEW_REQUIRED 285 |
| DB_LIFE | 60 | 25 | 1,486 | DRY_RUN 1,486 |
| IBK_LIFE | 571 | 0 | 0 | 대상 월 판매개시 상품 없음 |
| IM_LIFE | 1,595 | 9 | 27 | DRY_RUN 27 |
| KB_LIFE | 1,247 | 110 | 317 | DRY_RUN 317 |
| METLIFE | 690 | 39 | 312 | DRY_RUN 312 |
| HANA_LIFE | 40 | 11 | 33 | DRY_RUN 33 |
| (당시 Adapter 없음 14개사) | - | - | - | 경고 후 건너뜀, 실행 계속 |

**전체 상태**: `{"DUPLICATE_SKIPPED": 36, "DRY_RUN": 3651, "MANUAL_REVIEW_REQUIRED": 291}`
— 실패(`DOWNLOAD_FAILED`/`INVALID_RESPONSE`/`ACCESS_DENIED`) **0건**

#### 알아 둘 점

1. **`문서 링크 수` 가 0 으로 표시되는 보험사** (`IM_LIFE`, `HYUNDAI_MARINE`, `HEUNGKUK_FIRE`)
   요약의 `document_links` 는 `document_url` 이 있는 레코드만 셉니다. 이 세 곳은 다운로드가
   URL 이 아니라 **폼 POST / 파일경로 변환** 방식이라 URL 컬럼이 비어 있고 `download_hint` 로
   처리합니다. `상태` 의 `DRY_RUN` 건수가 실제 문서 레코드 수입니다(기존 MERITZ 와 동일한 구조).

2. **`MIRAE_LIFE` 의 `MANUAL_REVIEW_REQUIRED` 285건**
   판매중지 시트의 구(舊) 데이터에 **판매시작일(`cell2`)이 비어 있고 종료일만 있는 행**이 264건 있습니다
   (예: `개호보장(개인형)-약관`, 종료일 `2000-10-16`). 요구사항 §9 에 따라 **제외하지 않고**
   `MANUAL_REVIEW_REQUIRED` 로 기록합니다. 나머지는 `SAMSUNG` 4건, `HYUNDAI_MARINE` 2건 등입니다.

3. **`DB` 수집 9건**
   아침 baseline 측정 시 6건이었으나 같은 날 오후 재실행에서 9건이 되었습니다.
   DB 손해보험 Adapter 는 미변경이며 사이트 데이터가 당일 갱신된 결과입니다.

4. **`HEUNGKUK_FIRE` 3,834건**
   판매중지 화면의 판매일이 `시작 ~ 종료` 형태인 것을 반영해 파서를 수정한 뒤의 수치입니다
   (수정 전에는 날짜 파싱 실패로 2,348건 수집 + 2,299건이 전부 `MANUAL_REVIEW_REQUIRED` 였습니다).

---

## 6. 합계

29개사 일괄 dry-run(§5.3, `run_id=20260731_174447_67bee4`) 기준입니다.
`KB`·`KYOBO_LIFE` 는 `--max-products 20` 표본, `HANA_NON_LIFE` 는 미포함입니다.

```
총 상품 수            : 2,114 (각 사 '대상 상품 수' 합계)
                        └ 이 중 1,119 는 KYOBO_LIFE 가 보고한 '등록 상품 총수'입니다.
                          표본(20개) 실행이라 대상 월 버전은 0 이므로 실질 상품 수는 995 입니다.
총 상품 버전 수(수집)  : 34,501
총 상품 버전 수(대상 월): 999
총 문서 레코드 수      : 3,978  (= DRY_RUN 3,651 + DUPLICATE_SKIPPED 36 + MANUAL_REVIEW_REQUIRED 291)
  ├ 약관(POLICY)      : docs/sites/*.md §7 및 manifest 의 document_type 별 집계 참조
  ├ 사업방법서(METHOD)  : 〃
  └ 상품요약서(SUMMARY) : 〃
다운로드 성공 수       : 29   (3종 실다운로드 검증 표본, §4)
중복 생략 수           : 36   (DUPLICATE_SKIPPED — 이전 실행에서 이미 받은 파일)
실패 수                : 0    (DOWNLOAD_FAILED / INVALID_RESPONSE / ACCESS_DENIED 모두 0)
수동 검토 수           : 291  (MANUAL_REVIEW_REQUIRED — 날짜 미제공, §5.3 알아 둘 점 2)
DRY_RUN 레코드         : 3,651
당시 미구현 보험사      : 14개사 (역사 기록; 현재 상태는 README와 ENDPOINT_MATRIX 참조)
```

문서유형별 정확한 집계는 실제 실행 후 manifest 에서 확인할 수 있습니다.

```powershell
# 아래 명령과 $OUT\download_manifest.csv 경로는 당시 layout v1의 legacy 검증 명령입니다.
# 문서유형별 건수
Import-Csv "$OUT\download_manifest.csv" | Group-Object document_type | Select-Object Name, Count
# 보험사 × 문서유형
Import-Csv "$OUT\download_manifest.csv" | Group-Object company_code, document_type | Select-Object Name, Count
```

> `KB` 전량 수치가 필요하면 `python main.py --target-month 2026-07 --company KB --dry-run`(약 2시간 30분),
> `KYOBO_LIFE` 는 `--company KYOBO_LIFE`(약 40분), `HANA_NON_LIFE` 는 §5.2 참고.

---

## 7. 2026-08-04 (2차) 회귀 — 남은 6개사 구현 이후

### 7.1 pytest

`149 passed / 5 skipped / 0 failed` — 기존 테스트 무변경, 실패 없음.

### 7.2 기존 보험사 회귀

```bash
python main.py --target-month 2026-07 --dry-run --company DB --company LOTTE --company SAMSUNG
```

| 코드 | 항목 | 이전 회차 | 이번 회차 | 판정 |
|---|---|---:|---:|---|
| DB | 전체 수집 / 대상 / 문서 | 9 / 9 / 27 | 9 / 9 / 27 | ✅ 동일 |
| LOTTE | 전체 수집 / 대상 / 문서 | 4,391 / 49 / 145 | 4,391 / 49 / 145 | ✅ 동일 |
| SAMSUNG | 전체 수집 / 대상 / 문서 | 9,404 / 137 / 387 | 9,408 / 137 / 387 | ⚠️ 전체 수집 +4 — Adapter 미변경, 사이트 데이터 증가 |

- 전체 상태: `{"DUPLICATE_SKIPPED": 28, "DRY_RUN": 527, "MANUAL_REVIEW_REQUIRED": 4}` — 실패 0건
- 소요 53.4초
- manifest 28개 컬럼 · 저장 경로 · 중복 판정(DUPLICATE_SKIPPED 28) 모두 종전과 동일

### 7.3 신규 3개사 검증

| 코드 | 수집 | 대상 월 | 문서 | 실제 다운로드 |
|---|---:|---:|---:|---|
| HANWHA_LIFE | 표본 4버전 | - | 16 | 약관 30,532,753 B / 방법서 775,855 B / 요약서 7,369,817 B (`%PDF-1`) |
| SAMSUNG_LIFE | 표본 30버전(3페이지) | - | 53 | 약관 1,028,052 B / 방법서 163,221 B (`%PDF-1`), 요약서 표본 내 없음 |
| LINA_LIFE | 403버전 | 1 | 0 | 문서 요청 미확정 → 미실시 |
