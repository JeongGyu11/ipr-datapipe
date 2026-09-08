# 라이나생명 상품공시실 분석

## 1. 기본 정보

- 보험사 코드: `LINA_LIFE`
- 보험사명: 라이나생명
- 보험 구분: 생명보험(life)
- config URL: https://www.lina.co.kr/disclosure/product-public-announcement/product-on-sales
- 실제 상품 목록 URL: https://api.lina.co.kr/public/contents/v1/disclosure/… (특약 목록만 확인)
- 판매 중 상품 URL: 화면 `/product-on-sales`
- 판매 중지 상품 URL: 추가 수동 확인 필요
- 확인일: 2026-07-31

## 2. 사이트 특징

- 렌더링 방식: JAVASCRIPT_RENDERED (Nuxt SPA) + 외부 JSON API(`api.lina.co.kr`)
- 상품 카테고리: `kcisInsKcd`(예: 02), `mtrtDcd`(R=특약) 등 코드 파라미터 존재
- 판매채널 구분: 확인 불가
- 검색 조건: 확인 불가
- 날짜 제공 방식: 응답 `sellOpnDt` / `sellEndDt` 확인
- 페이지네이션 방식: 확인 불가
- 상품 버전 표시 방식: 확인 불가
- 이전 판매기간 제공 여부: 확인 불가
- 팝업 또는 모달 사용 여부: 확인 불가

## 3. 실제 엔드포인트

| 구분 | 메서드 | 엔드포인트 | 주요 파라미터 | 응답 형식 |
|---|---|---|---|---|
| 세션 초기화 | GET | `/disclosure/product-public-announcement/product-on-sales` | - | HTML(Nuxt) |
| 상품 목록(주계약) | - | 확인 불가 | - | - |
| 특약 목록 | GET | `https://api.lina.co.kr/public/contents/v1/disclosure/end-product` | `mtrtDcd=R`,`KcisInsKcd`,`KliaProdClcd`,`searchKey`,`inscd`,`prodPbanGrpCd` | JSON |
| 판매기간 | - | 응답의 `sellOpnDt`/`sellEndDt` | - | JSON |
| 첨부파일 목록 | - | 확인 불가 | - | - |
| 파일 다운로드 | - | 확인 불가 | - | - |

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

- 약관: 추가 수동 확인 필요
- 사업방법서: 추가 수동 확인 필요
- 상품요약서: 추가 수동 확인 필요
- 상대 URL 여부: 확인 불가
- JavaScript 함수 여부: 확인 불가
- 파일명 획득 방법: 확인 불가
- 한 상품에 여러 문서 존재 여부: 확인 불가

## 6. 구현 방식

- Adapter 파일: `crawler/adapters/lina_life.py` (`LinaLifeAdapter`)
- 등록: `crawler/adapters/__init__.py` (`"LINA_LIFE": LinaLifeAdapter`)
- 수집 방식: JSON_API (목록·판매기간 상세 API)
- Playwright 사용 여부: 사용 안 함
- 선택한 구현 방식의 이유: `api.lina.co.kr`의 인증 없는 평문 JSON API를 재현
- 공통 유틸리티 사용 내역: `BaseInsurerAdapter.client`(HttpClient)와 `utils.date_utils.parse_date` 사용

## 7. 테스트 결과

- 대상 월: 2026-07
- 수집 상품 수: 확인 불가
- 상품 버전 수: 확인 불가
- 약관 링크 수: 확인 불가
- 사업방법서 링크 수: 확인 불가
- 상품요약서 링크 수: 확인 불가
- 다운로드 성공 수: 0
- 실패 수: 0
- 중복 수: 0
- 누락 또는 수동 검토 수: 전건 수동 확인 필요

## 8. 제한 사항

- WAF: 관측되지 않음
- CAPTCHA: 관측되지 않음
- 세션 만료: 관측되지 않음
- 조회 범위 제한: 없음
- 날짜 누락: 없음
- 문서 누락: 없음
- 기타 문제: 초기 로드 시 호출되는 API 는 특약(`mtrtDcd=R`) 목록뿐이며 주계약 목록·문서 다운로드 엔드포인트는 화면 조작이 필요해 확정하지 못함. 응답 예: `{inscd:'R00016005', insNm:'무배당추가보장특약', sellOpnDt:'20030101', sellEndDt:'20050508'}`

## 9. 확인 근거

- 확인한 화면: 공시실 > 상품공시실 > 판매중인상품/판매중지상품
- 확인한 Network 요청: `GET https://api.lina.co.kr/public/contents/v1/disclosure/end-product?mtrtDcd=R&KcisInsKcd=02…` (200 / JSON)
- 테스트 상품: 미검증
- 테스트 파일: 미검증
- 레거시 근거(2026-07-31 수동 조사): `C:/…/scratchpad/net.py` Playwright 네트워크 로깅 출력 — 현재 저장구조/리포지토리에 포함되지 않음

---

## 10. 후속 조사 (2026-08-04)

- **최종 분류**: `NEEDS_NETWORK_ANALYSIS` (변경 없음)
- **현재 실패 단계**: **목록 조회**
- **정확한 원인**
  - config URL `/product-on-sales` 로 접속하면 화면에는 **'판매중지 상품'** 이 렌더링되고,
    초기 로드에서 호출되는 API 는 `end-product?mtrtDcd=R`(특약) **한 건뿐**입니다.
  - 좌측 메뉴의 '판매중인상품' 은 `href` 가 없는 JS 메뉴라 클릭 경로를 재현하지 못했습니다
    (`get_by_role('link', name='판매중인상품')` 타임아웃).
  - 주계약 목록·문서 다운로드 요청은 사용자가 보종 탭을 선택한 뒤에 발생하는 것으로 보이나
    아직 기록하지 못했습니다.
- **확인한 요청(성공)**
  ```
  GET https://api.lina.co.kr/public/contents/v1/disclosure/end-product
      ?mtrtDcd=R&KliaProdClcd=&KcisInsKcd=02&searchKey=&inscd=&prodPbanGrpCd=&tabTitle=
  → 200 application/json, listDisclosure 15건
    {inscd, insureCd, insNm, mtrtDcd, sellOpnDt, sellEndDt, kcisInsKcd, prodPbanGrpCd, kliaProdClcd}
  ```
- **확인한 실패**: 같은 엔드포인트에 `mtrtDcd=M` → `resultCode=-1`(0건).
  `sale-product` / `product` / `on-product` 는 404 (추정 경로이므로 사용하지 않음)
- **후속 작업**: 브라우저에서 '판매중인상품' 진입 → 보종 탭 선택 → 조회 → 문서 클릭까지 수행하며
  Network 기록. `api.lina.co.kr` 는 인증 없는 평문 JSON 이라 엔드포인트만 확정되면 즉시 구현 가능합니다.

---

## 11. 2026-08-04 구현 결과

- **최종 분류**: `NEEDS_NETWORK_ANALYSIS` → **`PARTIAL`** (상품·판매기간까지 구현)
- **판매중 목록 API 확정(2026-08-04)**
  ```
  GET https://api.lina.co.kr/public/contents/v1/disclosure/product-list
      ?mtrtDcd=B&KliaProdClcd=01&KcisInsKcd=&searchKey=&inscd=&prodPbanGrpCd=&tabTitle=
  ```
  - 판매중지는 `end-product` (기존 확인분)
  - `mtrtDcd`: `B` 주보험 / `R` 특약
  - `KliaProdClcd`: 주보험 분류(실측 응답 있는 코드 01·03·04~11). 특약은 이 값과 무관
- **발견 경로**: 좌측 메뉴 '판매중인상품' 을 JS 로 직접 클릭(`element.click()`)했을 때 발생
- **수집 규모(실측)**: 403버전 — 판매중 93(주보험 74 + 특약 19) / 판매중지 310(주보험 306 + 특약 4)
- **남은 문제(문서)**: 목록 응답에 파일 정보가 **없고**, 문서를 반환하는 요청을 확정하지 못했습니다.
  - 화면이 headless 브라우저에서 상품 행을 렌더링하지 않음(`table` 0개,
    "직접검색을 원하시면 상품명을 입력 후 검색 버튼을 클릭해 주세요." 표시)
  - `inscd` / `prodPbanGrpCd` 를 목록 API 에 넣어도 응답 구조가 동일(문서 필드 없음) — 실측
  - **추정 URL 을 만들지 않았습니다.**
- **조치**: 상품·판매기간까지만 수집하고 `stats.document_endpoint_unconfirmed = True` 로 표시
- **Adapter**: `crawler/adapters/lina_life.py`

---

## 12. 2026-08-06 구현 완료 — §10 · §11 의 "문서 요청 미확정" 해소

### 12.1 문서 요청은 존재합니다

§11 의 "문서를 반환하는 요청을 확정하지 못했다" 는 탐색이 부족했던 것입니다.
문서 요청은 **상품 카드를 펼칠 때** 호출됩니다.

**놓친 이유 3가지**

1. 초기 로드 API 는 `product-list` 인데 파일 필드가 없습니다. 여기서 멈췄습니다.
   실제 목록은 **검색 버튼을 눌러야** 호출되는 `get-product-list` 이며 건수도 다릅니다
   (특약 15건 → **2,264건**).
2. 목록이 `<table>` 이 아니라 `<li class="list">` **아코디언 카드**라 행 탐색에 실패했습니다.
3. 문서 표는 **펼친 뒤에만** 나타납니다. 접힌 상태에는 상품명과 `>` 화살표뿐입니다(화면 캡처 확인).

### 12.2 확정된 엔드포인트 (실측)

| 구분 | 판매중 | 판매중지 |
|---|---|---|
| 목록 | `GET /public/contents/v1/disclosure/get-product-list` | `GET /public/contents/v1/disclosure/get-product-endlist` |
| 상세 | `GET /public/contents/v1/disclosure/product-list-detail` | `GET /public/contents/v1/disclosure/end-product-detail` |

- host: `https://api.lina.co.kr`
- 목록 파라미터: `mtrtDcd`(`B` 주보험 / `R` 특약), `KliaProdClcd`(주보험 분류), `KcisInsKcd`(특약 보종),
  `searchKey`, `inscd`, `prodPbanGrpCd`, `tabTitle`
- 상세 파라미터: `insureCd`, `prodPbanGrpCd` (판매중지는 `insRenwPrcsPsbYn` 추가)
- 인증 없는 평문 JSON. `api.lina.co.kr` robots.txt 없음.

**문서 다운로드**

```
GET https://www.lina.co.kr/cms/upload/upload/docs/disclosure/{파일명}
```

화면 스크립트 `_nuxt/a41423a464e92deb0f8c.js` 의 `openFile()` 에서 확인했습니다.

```javascript
openFile: function(e) {
    var t = this.currentUrl + "/cms/upload/upload/docs/disclosure/" + e;
    window.open(t, "_blank");
}
```

### 12.3 상세 응답 → 수집 항목

```json
{ "insNm": "무배당THE간편고지종신보험(해약환급금미지급형)_기납입P플러스형",
  "sellOpnDt": "20260401", "sellEndDt": "99991231",
  "productSumary":    "B00312011_1_S.pdf",
  "productMethod":    "B00312011_0_B.pdf",
  "productProvision": "B00312011_1_P.pdf",
  "itemSection": "최초계약", "trtTpCd": "01" }
```

| 수집 항목 | 필드 |
|---|---|
| 약관 | `productProvision` |
| 사업방법서 | `productMethod` |
| 상품요약서 | `productSumary` |
| 판매기간 | `sellOpnDt` ~ `sellEndDt` |

**상세는 판매기간별로 여러 행을 돌려줍니다.** 목록은 현재 판매기간 1건만 주므로
판매기간 이력은 상세에서만 얻을 수 있습니다.

### 12.4 파일명은 조립하지 않습니다

파일명 앞부분은 `inscd` 와 같지만 가운데 번호가 개정 이력마다 달라집니다(실측).

| 판매기간 | 요약서 | 방법서 | 약관 |
|---|---|---|---|
| 2026-04-01 ~ | `_0_S` | `_2_B` | (없음) |
| 2025-09-01 ~ 2026-03-31 | (없음) | `_2_B` | `_3_P` |
| 2025-04-01 ~ 2025-08-31 | (없음) | `_2_B` | `_2_P` |
| 2024-06-01 ~ 2025-03-31 | (없음) | `_1_B` | `_1_P` |

서버가 준 파일명을 그대로 씁니다.

### 12.5 구현상 처리한 사항

- **상세 지연 조회**: 상품 3,455건 전량 상세 조회 시 약 2시간이므로 `collect_documents()` 에 배치.
  `CrawlerManager` 가 대상 월로 선정한 버전만 조회합니다.
  - 제약: 대상 월 판정에 목록의 `sellOpnDt`(현재 판매기간)를 쓰므로
    **과거 판매기간 버전은 후보에 포함되지 않습니다.** `new_or_revised` 모드에서는 문제없습니다.
- **`sellEndDt: "99991231"`**: 무기한 판매중 표기. `None` 으로 변환하지 않으면 전 상품이 판매중지가 됩니다.
- **종속특약 `-` 표기**: `trtTpCd=02` 는 요약서·방법서가, `03` 은 요약서가 화면에서 `-` 로 표시되고
  "함께 가입하신 주보험에서 확인" 안내가 붙습니다. 빈 값 또는 `-` 면 문서를 만들지 않습니다.
  **수집 누락이 아니라 사이트 정책입니다.**

### 12.6 검증 결과

**Dry-run** (`--company LINA_LIFE --dry-run --target-month 2026-07`, 74.1초)

```
3,455버전 수집 → 대상 1건 / 문서 링크 2건 / MANUAL_REVIEW_REQUIRED 0
대상 상품: 대리청구인지정서비스특약 (2026-07-01 판매개시)
```

대상 1건은 라이나생명의 2026-07 판매개시 상품이 실제로 1건이기 때문입니다.

**실제 다운로드**

| 문서 | HTTP | 크기 | 매직 | 파일명 |
|---|---|---|---|---|
| 약관 | 200 | 270,338 B | `%PDF-` | `R00804009_0_P.pdf` |
| 사업방법서 | 200 | 5,336,746 B | `%PDF-` | `R00804009_0_B.pdf` |
| 상품요약서 | — | — | — | 종속특약(`trtTpCd=03`)이라 사이트 미제공 |

별도 확인한 주보험 상품(`B00312011`): 약관 1,020,551 B / 사업방법서 2,461,025 B /
상품요약서 758,375 B — 3종 모두 `%PDF-`.

### 12.7 최종 분류

`PARTIAL` → **`IMPLEMENTED_HTTP`**

- Adapter: `crawler/adapters/lina_life.py`
- `stats.document_endpoint_unconfirmed` 플래그 제거
