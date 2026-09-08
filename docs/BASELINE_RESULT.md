# BASELINE_RESULT.md — 신규 Adapter 추가 **이전** 기준 상태

> ⚠️ 역사적 기록 안내: 이 문서는 **과거 layout v1/당시 검증 기록**입니다. 현재 경로와
> 실행 명령은 `README.md`를 참조하세요. `scratchpad`는 현재 배포에 포함되지 않습니다.

> 목적: 25개사 확장 작업을 시작하기 전, 기존 5개사가 정상 동작하는 상태를 기록해 두고
> 확장 이후 회귀 테스트(`docs/REGRESSION_TEST_RESULT.md`)와 1:1 비교하기 위한 문서입니다.
>
> - 측정 일시: **2026-07-31**
> - 대상 월: `2026-07`
> - 실행 명령: `python main.py --target-month 2026-07 --dry-run`, `pytest`
> - 코드 상태: 확장 작업 착수 전 커밋(신규 Adapter·공통 유틸 추가 이전)

---

## 1. pytest

```
$ python -m pytest -q
........................................................................ [ 60%]
.................sssss.........................                          [100%]
```

- 통과 **119건**, 건너뜀 **5건**(네트워크 실사용 테스트), 실패 **0건**
- 건너뛴 5건은 `tests/test_integration_adapters.py` 의 실 사이트 호출 케이스입니다.

---

## 2. 전체 Dry-run (`--target-month 2026-07 --dry-run`)

| 코드 | 보험사 | 수집 방식 | 전체 수집 버전 | 대상 월 선정 | 목록 수집 시간 | 비고 |
|---|---|---|---:|---:|---:|---|
| DB | DB손해보험 | 내부 JSON API(Step5 기간검색) | 6 | 6 | 12초 | 서버측 기간 필터 사용 |
| LOTTE | 롯데손해보험 | 폼 POST(EUC-KR) 검색형 1회 조회 | 4,391 | 49 | 3.4초 | 판매 2,027 + 판매종료 2,364 |
| MERITZ | 메리츠화재 | Playwright(헤드풀) + 페이지 내 API | 183 | 183 | 149초 | 분류 16종 × 판매/판매중지 |
| KB | KB손해보험 | 폼 POST + 정적 HTML 파싱 | 상품 3,994건 상세 순회 | (장시간 실행) | 약 2시간 30분 | 목록에 날짜가 없어 전 상품 상세 조회 필요 |
| SAMSUNG | 삼성화재 | 내부 JSON API(VH.HDIF0103) | 9,404 | 137 | 1.4초 | 1회 호출로 전량 |

### 2.1 실행 로그 원문(발췌)

```
2026-07-31 15:46:42 [INFO] [DB] DB손해보험 수집 시작 (2026-07-01 ~ 2026-07-31)
2026-07-31 15:46:54 [INFO] [DB] 수집 6건 -> 대상 월 선정 6건
2026-07-31 15:47:18 [INFO] [LOTTE] 롯데손해보험 수집 시작 (2026-07-01 ~ 2026-07-31)
2026-07-31 15:47:21 [INFO] [LOTTE] 수집 4391건 -> 대상 월 선정 49건
2026-07-31 15:47:26 [INFO] [MERITZ] 메리츠화재 수집 시작 (2026-07-01 ~ 2026-07-31)
2026-07-31 15:49:50 [INFO] [MERITZ] 수집 183건 -> 대상 월 선정 183건
2026-07-31 15:49:53 [INFO] [KB] KB손해보험 수집 시작 (2026-07-01 ~ 2026-07-31)
2026-07-31 15:49:53 [INFO] [KB] 마지막 페이지 오프셋 3991 (약 4000개 상품)
2026-07-31 16:03:11 [INFO] [KB] 상품 3994건의 상세를 조회합니다.
```

> **KB손해보험에 대한 주의**
> KB는 목록 화면에 날짜 정보가 전혀 없어 대상 월 버전을 찾으려면 전 상품(3,994건)의 상세를
> 열어야 합니다. `request_interval_seconds: 2` 기준 약 **2시간 30분**이 걸립니다.
> 본 baseline 측정에서도 동일하게 장시간 실행되었으며, 이 특성은 확장 작업으로 **변경되지 않았습니다**
> (KB Adapter 코드 미변경).

---

## 3. 확장 전 기준 산출물 형식

아래 항목은 확장 이후에도 **변경되지 않아야 하는** 기준입니다.

### 3.1 manifest 컬럼 (28개, `crawler/manifest_service.py:MANIFEST_COLUMNS`)

```
run_id, company_code, company_name, product_category, product_name_raw,
product_name_normalized, source_product_id, sale_status, sale_start_date,
sale_end_date, disclosure_date, revision_date, target_date, date_basis,
document_type, document_label, source_page_url, document_url, original_filename,
saved_filename, saved_path, file_extension, content_type, file_size, sha256,
download_status, downloaded_at, error_message
```

### 3.2 파일 저장 구조

```
{base_path}/{root_folder}/{YYYY-MM}/{보험사명}/{상품명}/{버전키}/{문서유형}/{보험사}_{상품}_{기준일}_{문서유형}.pdf
```

예)
```
…\insurance_product_documents\2026-07\iM라이프\SMART유니버셜종신보험 무배당 2601(보증비용부과형)
   \20260701_판매개시\약관\iM라이프_SMART유니버셜종신보험 무배당 2601(보증비용부과형)_20260701_약관.pdf
```

### 3.3 기존 5개사 Adapter 파일 (수집 로직 미변경)

```
crawler/adapters/db_insurance.py
crawler/adapters/lotte_insurance.py
crawler/adapters/meritz_insurance.py
crawler/adapters/kb_insurance.py
crawler/adapters/samsung_insurance.py
```

---

## 4. 확장 작업 중 기존 코드에 적용한 변경 (영향 범위)

기존 5개사 Adapter 파일은 **한 줄도 수정하지 않았습니다.** 공통 모듈에만 하위 호환 변경을 적용했습니다.

| 파일 | 변경 내용 | 변경 이유 | 기존 5개사 영향 |
|---|---|---|---|
| `crawler/http_client.py` | `HttpClient(..., legacy_ssl=False)` 키워드 추가, `legacy_ssl_context()` 신설 | DB생명·한화생명·AIG는 구형 TLS 스택이라 기본 컨텍스트로 **연결 자체가 실패**(`WRONG_SIGNATURE_TYPE` 등) | **없음**. 기본값 `False` 이며 이때 동작(`verify=False`)은 종전과 동일 |
| `crawler/base_adapter.py` | `_build_client()` 에 `legacy_ssl=self._legacy_ssl()` 전달, `_legacy_ssl()` 신설 | 위 옵션을 보험사별로 켜기 위함 | **없음**. 기존 5개사는 클래스 속성·config 옵션 모두 미지정이라 `False` |
| `crawler/config.py` | `CompanyConfig` 에 `insurance_type`, `resolved_disclosure_url` 필드 추가(기본값 `""`) | 요구사항 §4 의 생명/손보 구분과 실제 공시 URL 분리 기록 | **없음**. 기본값이 있어 기존 config 그대로 로드됨 |
| `crawler/adapters/__init__.py` | 신규 Adapter 11종 등록 | 확장 | **없음**. 기존 5개 매핑 그대로 유지 |
| `config.yaml` | 30개사 등록, 기존 5개사 항목에 `insurance_type` 추가 | 확장 | **없음**. 기존 5개사의 `code`/`name`/`url`/`options` 는 그대로 |
| `crawler/adapters/common.py` | **신규 파일**. 신규 Adapter 전용 공통 파서/요청 유틸 | 중복 코드 방지(요구사항 §11) | **없음**. 기존 5개 Adapter 는 이 모듈을 import 하지 않음 |

확장 후 pytest 재실행 결과도 동일하게 **119 passed / 5 skipped / 0 failed** 입니다
(`docs/REGRESSION_TEST_RESULT.md` §1).
