# SITE_ANALYSIS.md — 손해보험사 상품공시실 구조 분석

> **Historical Snapshot — 2026-07-31**
> 이 문서는 2026-07-31 당시의 손해보험 5개사 사이트 분석을 보존한 역사 기록입니다.
> 현재 Adapter·엔드포인트 정본은 `README.md`, `docs/ENDPOINT_MATRIX.md` 및
> `docs/SITE_ANALYSIS_30.md`를 확인하세요. 이 문서에 포함된 외부 조사 도구나
> `scratchpad/*` 경로가 있더라도 저장소 외부의 당시 증적이며 현재 실행할 수 없습니다.

> 본 문서의 모든 엔드포인트·파라미터·선택자는 **2026-07-31 기준으로 실제 요청을 보내 응답을 확인한 결과**만 기록했습니다.
> 추정하여 작성한 항목은 없으며, 확인하지 못한 항목은 "미확인"으로 표기했습니다.
> 사용한 요청은 모두 각 사 공시실 화면이 브라우저에서 실제로 호출하는 공개 요청입니다.
> 인증 우회·관리자 API·CAPTCHA 우회는 사용하지 않았습니다.

---

## 0. 요약 비교표

| 항목 | DB손해보험 | 롯데손해보험 | 메리츠화재 | KB손해보험 | 삼성화재 |
|---|---|---|---|---|---|
| 수집 방식 | 내부 JSON API | 내부 폼 POST(HTML/JS 응답) | Playwright(헤드풀) + 페이지 내 API | 폼 POST + 정적 HTML 파싱 | 내부 JSON API |
| 우선순위 | 1순위 | 1순위 | 3순위(불가피) | 2순위 | 1순위 |
| 인코딩 | UTF-8 | EUC-KR | UTF-8 | EUC-KR | UTF-8 |
| 기간 조회 지원 | **O (서버 필터)** | X (전체 순회) | X (전체 순회) | X (전체 순회) | X (전체 순회) |
| 목록 1회 호출로 전량 | O (기간 내) | **O (4,391건)** | X (분류별) | X (페이지네이션) | **O (9,404건)** |
| 세션/쿠키 필요 | 불필요 | 불필요 | **필수(WAF)** | 불필요 | 불필요 |
| 2026-07 대상 버전 수 | 6 | 49 | 183 | 전수 조회 필요 | 137 |
| 목록 수집 요청 수 | 1 + 버전당 1 | **1** | 약 40 | **약 400 + 4,000** | **1** |
| 목록 수집 실측 시간 | 12초 | 3.4초 | 149초 | 상품 40개당 87초 → 전수 약 2시간 30분 | 1.4초 |

> 위 "2026-07 대상 버전 수"와 시간은 2026-07-31 실제 dry-run 실행 결과입니다.
> KB손해보험은 목록에 날짜가 없어 전 상품(약 4,000개) 상세를 열어야 하므로 유일하게 장시간이 소요됩니다.

---

## 1. DB손해보험 (DB)

- 화면 URL: `https://www.idbins.com/FWMAIV1534.do`
- 수집 방식: **1순위 — 화면이 호출하는 JSON API 재현**

### 1.1 상품목록 조회 방식

화면 하단 인라인 스크립트(`FWMAIV1534.do` 응답 9305~9640행)에 4개의 AJAX 엔드포인트가 정의되어 있습니다.

| 용도 | 엔드포인트 | 파라미터 |
|---|---|---|
| Step2 상품명 목록 | `POST /insuPcPbanFindProductStep2_AX.do` | `arc_knd_lgcg_nm`, `sl_chn_nm`, `arc_knd_mdcg_nm`, `arc_pdc_sl_yn` |
| Step3 판매기간 목록 | `POST /insuPcPbanFindProductStep3_AX.do` | `pdc_nm`, `arc_pdc_sl_yn` |
| Step4 문서 조회 | `POST /insuPcPbanFindProductStep4_AX.do` | `sqno`, `arc_pdc_sl_yn` |
| **Step5 기간 검색** | `POST /insuPcPbanFindProductStep5_AX.do` | `searchCheck`, `keyword`, `beginDate`, `endDate` |

**중요**: 요청 본문은 반드시 `Content-Type: application/json` + JSON 이어야 합니다.
`application/x-www-form-urlencoded` 로 보내면 **HTTP 415 Unsupported Media Type** 이 반환됩니다(실측).

본 크롤러는 화면의 "판매기간 검색" 기능(`searchClick()` → `searchCheck='1'`)이 사용하는 **Step5** 를 사용합니다.
대상 월을 그대로 `beginDate`/`endDate` 에 넣으면 서버가 필터링해 주므로 요청 수가 가장 적습니다.

실측 요청/응답:

```http
POST /insuPcPbanFindProductStep5_AX.do
Content-Type: application/json; charset=UTF-8
Referer: https://www.idbins.com/FWMAIV1534.do

{"searchCheck":"1","keyword":"","beginDate":"20260701","endDate":"20260731"}
```

```json
{"result":[{"ARC_PDC_SL_YN":"1","CNSL_SMAR_FINM":"요약_31073(08)_20260701.pdf",
 "SALE_BEGIN_DAY":"2026.07.01","SQNO":10582,"BIZ_MDDC_FINM":"사방_31073(08)_20260701.pdf",
 "ARC_KND_LGCG_NM":"장기보험","INPL_FINM":"약관_31073(08)_20260701.pdf",
 "PDC_NM":"무배당 프로미라이프 간편건강보험(일반심사형)2607"}, ...]}
```

- `keyword` 는 화면에서는 필수 입력이지만 서버는 빈 문자열을 허용하며, 이때 전체 상품이 대상이 됩니다.
  `keyword=""` 와 `keyword="보험"` 의 2026-07 결과가 6건으로 동일함을 실측 확인했습니다.
- 응답 1건 = **상품 버전 1건**이며 문서 파일명이 함께 옵니다. 별도 상세 요청이 필요 없습니다.
- 판매종료일이 필요하면 `Step4`(`sqno`)로 `SL_STR_DT`/`SL_FIN_DT` 를 추가 조회합니다(본 크롤러는 조회함).

### 1.2 필드 매핑

| 응답 필드 | 의미 |
|---|---|
| `PDC_NM` | 상품명 |
| `SALE_BEGIN_DAY` | 판매개시일 (`YYYY.MM.DD`) |
| `SQNO` | 상품 버전 내부 식별자 |
| `ARC_KND_LGCG_NM` | 상품 대분류(장기보험/일반/자동차보험/제도성 특별약관) |
| `ARC_PDC_SL_YN` | `1`=판매중, `0`=판매중지 |
| `INPL_FINM` | 약관 파일명 |
| `BIZ_MDDC_FINM` | 사업방법서 파일명 |
| `CNSL_SMAR_FINM` | 상품요약서 파일명 |
| `PDC_EXPP_FINM` | 상품설명서 파일명 (**수집 제외 대상**) |
| `SL_STR_DT`/`SL_FIN_DT` | Step4 응답의 판매 시작/종료일(`YYYYMMDD`) |

### 1.3 문서 다운로드

```
GET /cYakgwanDown.do?FilePath=InsProduct/{urlencode(파일명)}
```

실측 응답: `200`, `Content-Type: application/pdf;charset=UTF-8`,
`Content-Disposition: inline;filename=%EC%95%BD%EA%B4%80_31073%2808%29_20260701.pdf`,
본문 선두 `%PDF-1.6`, 13,091,228 bytes.

### 1.4 기타

- 페이지네이션: 없음(Step5 는 전체 반환)
- 판매중/중지 구분: `ARC_PDC_SL_YN`
- 쿠키/세션: 불필요. 다만 `Referer` 헤더는 설정함.
- Playwright: 불필요
- 테스트 가능 상품 1건: `무배당 프로미라이프 간편건강보험(일반심사형)2607` (SQNO 10582, 2026.07.01)
- 제한 사항: 2026-07 결과가 6건으로 타사 대비 적음. 실측상 2026-06은 67건, 2026년 전체는 434건으로
  API 자체 상한은 확인되지 않았고 해당 월의 실제 신규/개정 건수로 판단됨.
- `date_basis`: `sale_start_date`

---

## 2. 롯데손해보험 (LOTTE)

- 화면 URL: `https://www.lotteins.co.kr/web/C/D/H/cdh190.jsp`
- 수집 방식: **1순위 — 화면 폼 POST 재현** (응답은 JSON이 아닌 HTML+JS)

공시실 화면에는 두 가지 조회 방식이 있고 **둘 다 동작함을 실측 확인**했습니다.

| 방식 | task | 요청 수 | 채택 |
|---|---|---|---|
| 분류형 4단계 드릴다운 | `gostep2~gostep4` | 상품 1건마다 요청 → **수 시간** | 미채택(대안으로 문서화) |
| **검색형 1회 조회** | `searchKey` | **1회 (4,391행 수신)** | **채택** |

두 방식이 같은 데이터를 주므로, 사이트 부하와 소요 시간이 훨씬 작은 검색형을 사용합니다.

### 2.0 검색형 조회 (채택 방식)

```http
POST /CChannelSvl
Content-Type: application/x-www-form-urlencoded    (EUC-KR)

ops_tc=dfi.c.d.g.cmd.Cdg079Cmd
rtnUri=/web/C/D/H/cdh190_result.jsp
task=searchKey
srcPrdNm=            (빈 값 = 전체)
lcode=&mcode=&scode=&startdate=&issale=Y
```

응답 1회에 두 개의 표가 함께 옵니다(실측).

| view id | 내용 | 실측 행 수 |
|---|---|---|
| `searchviewissale` | 판매상품 | 2,027 |
| `searchviewisnotsale` | 판매종료상품 | 2,364 |

각 행 구성: **상품군 / 상품명 / 판매기간 / 보험약관 / 사업방법서 / 상품요약서**

```html
<tr><td>자동차</td><td>let:way 개인용자동차보험</td><td>1989.06.29 ~ 2017.02.28</td>
<td><a href='/upload/C/newProduct/car4001_20170131.pdf'><img alt='약관'></a></td>
<td><a href='/upload/C/newProduct/carmethod_20170101.pdf'><img alt='사업방법서'></a></td>
<td><a href='/upload/C/newProduct/carsummary_20151228.pdf'><img alt='상품요약서'></a></td></tr>
```

**중요 — 인코딩**: 폼이 EUC-KR 이므로 `srcPrdNm` 을 UTF-8 로 보내면 한글 검색이 **항상 0건**으로
반환됩니다(실측: UTF-8 `실손` → 0건, EUC-KR `실손` → 165건). 반드시 EUC-KR 로 퍼센트 인코딩해야 합니다.
빈 검색어는 서버가 전체 조회로 처리합니다(실측: 2,027 + 2,364건).

### 2.1 분류형 4단계 드릴다운 (대안, 실측 확인됨)

모든 단계가 동일한 서블릿으로 갑니다.

```http
POST /CChannelSvl
Content-Type: application/x-www-form-urlencoded   (EUC-KR)

ops_tc=dfi.c.d.g.cmd.Cdg079Cmd
rtnUri=/web/C/D/H/cdh190_result.jsp
task=<단계별 값>
lcode=&mcode=&scode=&startdate=&issale=Y&srcPrdNm=
```

| 단계 | `task` (판매중 / 판매중지) | 입력 | 출력 |
|---|---|---|---|
| Step2 상품목록 | `gostep2issale` / `gostep2isnotsale` | `lcode`,`mcode` | `step3('lcode','mcode','scode')` 링크 + 상품명 |
| Step3 판매기간 | `gostep3issale` / `gostep3isnotsale` | +`scode` | `step4('lcode','mcode','scode','YYYYMMDD')` + `2026.07.01 ~ 현재` |
| Step4 문서 | `gostep4issale` / `gostep4isnotsale` | +`startdate` | 상품명·판매기간·PDF `<a href>` 3종 |

응답 본문은 부모 프레임에 HTML을 주입하는 스크립트입니다(실측).

```html
<script>
parent.document.getElementById("step4view").innerHTML =
"<dl class='pro_select'><dt>상품명</dt><dd><span>(무) let:click 실손의료보험Ⅴ(재가입용)(2607)</span></dd>
 <dt class='pt20'>판매기간</dt><dd><span>2026.07.01 ~ 현재</span></dd></dl>
 <ul class='pdf_btn'>
 <li><a href=/upload/C/newProduct/11_click_silson_5_2607_sb_v2_260722.pdf title='새창열림_사업방법서 PDF보기' ...
 <li><a href=/upload/C/newProduct/11_click_silson_5_2607_yoy.pdf title='새창열림_상품요약서 PDF보기' ...
 <li><a href=/upload/C/newProduct/11_click_silson_5_2607_yak.pdf title='새창열림_약관 PDF보기' ...
 </ul>";
</script>
```

따라서 파서는 `innerHTML = "..."` 안의 이스케이프된 HTML을 추출한 뒤 파싱합니다.
문서유형은 `title` 속성(`_사업방법서 PDF보기` 등) 또는 `<img alt>` 로 판별합니다.

### 2.2 카테고리 (`cdh190.jsp` 원본 HTML에서 추출, 실측)

| lcode | 대분류 | mcode 목록 |
|---|---|---|
| 01 | 자동차 | 01 개인용, 02 업무용, 03 영업용, 04 이륜차, 05 운전자, 06 외화표시, 07 농기계, 08 기타, 09 운전면허교습생, 10 모터바이크, 11 공동인수 |
| 02 | 일반 | 01 일반 |
| 03 | 장기 | 01 상해·질병, 02 저축, 03 운전자, 04 재물, 05 연금보험, 06 제도성특약 |
| 04 | 기타 | 01 공통 |

`issale` 이 `Y`/`N` 두 값이므로 총 **19 × 2 = 38** 개 조합을 순회합니다.

### 2.3 문서 다운로드

`/upload/C/newProduct/*.pdf` 형태의 **정적 직접 링크**입니다. 세션 불필요.

### 2.4 기타

- 페이지네이션: 없음(단계별 전체 목록 반환)
- 인코딩: 응답 `Content-Type: text/html;charset=euc-kr`
- Playwright: 불필요
- 테스트 가능 상품 1건: `(무) let:click 실손의료보험Ⅴ(재가입용)(2607)` (lcode 03 / mcode 01 / scode 1125 / startdate 20260701)
- `date_basis`: `sale_start_date`
- **제한 사항**
  - 검색형 응답에는 상품 내부 식별자가 없습니다. 본 크롤러는 약관 파일명을 보조 식별자로 사용합니다.
  - 분류형은 상품 1건마다 Step3 호출이 필요합니다. 실측상 `장기보험>상해,질병` 한 분류에만
    판매중지 상품이 1,079건 있어, 전체 순회에 수 시간이 걸립니다(그래서 미채택).
  - 판매기간 종료가 `현재` 로 표시되는 행은 판매종료일을 `None` 으로 처리합니다.

---

## 3. 메리츠화재 (MERITZ)

- 화면 URL: `https://www.meritzfire.com/disclosure/product-announcement/product-list.do?vMode=PC`
- 수집 방식: **3순위 — Playwright(헤드풀) 필수**

### 3.1 왜 Playwright 가 필요한가 (실측 근거)

| 시도 | 결과 |
|---|---|
| httpx 로 화면 HTML GET | 200 정상 (AngularJS 셸만 반환, 목록 없음) |
| httpx 로 `POST /json.smart` (목록 API) | **200 정상 — 데이터 수신됨** |
| httpx 로 `POST /hp/fileDownload.do` (파일) | **웹방화벽 차단** `Web firewall security policies have been blocked.` |
| Playwright **headless** 로 화면 진입 | **웹방화벽 차단** (페이지 진입 자체 실패) |
| Playwright **headful(headless=False)** | **정상 동작 — 목록·다운로드 모두 성공** |

파일 다운로드 경로가 방화벽에 의해 차단되므로 우회를 시도하지 않고,
**사이트가 의도한 그대로 실제 브라우저에서 화면의 다운로드 동작을 수행**하는 방식으로 구현했습니다.
차단이 지속되면 해당 문서는 `ACCESS_DENIED` 로 기록합니다.

### 3.2 상품목록 조회 방식

화면의 AngularJS `bc` 서비스가 `POST /json.smart` 한 곳으로 모든 전문을 보냅니다
(`/default/app/comm/http.js` 의 `SERVICE_URL = mz.DOMAIN + mz.WEBROOT + '/json.smart'`).

서비스 ID(`/default/app/biz/cu/ua/pdpban/salPdLst.js`):

| 논리명 | `rcvmsgSrvId` |
|---|---|
| 분류·상품명 목록 | `f.cg.he.cu.ua.o.bc.PbanBc.retrievePdList` |
| 분류별 전체 문서목록 | `f.cg.he.cu.ua.o.bc.PbanBc.retrieveSalPdList` |
| 상품명별 문서목록 | `f.cg.he.cu.ua.o.bc.PbanBc.retrieveSalPdListForCdNm` |
| 검색형 목록 | `f.cg.he.cu.ua.o.bc.PbanBc.retrieveSalPdSchList` |

전문 규격은 `{header:{...}, body:{...}}` 이며 `header` 는 `inputFilter()` 가 생성합니다.
본 크롤러는 **페이지 안에서 사이트 자신의 `bc` 서비스를 호출**하므로 헤더를 직접 만들지 않습니다.

```js
const inj = angular.element(document.querySelector('[data-ng-view]')).injector();
const bc  = inj.get('bc');
await bc.retrieveSalPdList({cmPdDivCd:'4102', notfYn:'Y', bcType:'SALPD_LST'});
```

- `notfYn`: `Y`=판매중, `N`=판매중지
- `srtSq`: 상품종류 순번(1~16)
- `cmPdDivCd`: 상품종류 코드(`pdDtlList[].cmCommCd`)

상품종류 16종(실측): 자동차보험, 운전자보험, 통합보험, 질병보험, 어린이보험, 암보험, 상해보험,
연금저축보험, 저축보험, 화재/재물/비용보험, 생활보험, 장기 방카슈랑스, 일반 방카슈랑스,
배상책임보험, 퇴직연금, 제도성특약.

### 3.3 `salPdList` 응답 필드 (실측)

```json
{
  "ttlNm": "Readycar개인용자동차보험",
  "bgnDt": "20260707",
  "putupStDdTm": "20260711",
  "putupEdDdTm": "-",
  "ntbdDtlSeq": 30567,
  "file1": "/cu/car/202607071457275730001U.pdf",
  "file2": "/cu/car/202607071457276490003U.pdf",
  "file3": "/cu/car/202607071457276510005U.pdf",
  "file1#[E]": "xqjuV/XO2+/+ha2ABi1yDIIRyH8qmlKrY7dTAQnHNtnW+qvrrXgwazPx6frIrA2B",
  "...#[E]": "(세션마다 값이 달라지는 암호화 토큰)"
}
```

| 필드 | 의미 |
|---|---|
| `ttlNm` | 상품명 |
| `bgnDt` | 판매개시일 |
| `putupStDdTm` / `putupEdDdTm` | 게시 시작/종료일 (`-` = 종료 없음) |
| `file1` / `file2` / `file3` | 약관 / 사업방법서 / 상품요약서 |
| `file4` | 상품설명서 (**수집 제외 대상**) |
| `*#[E]` | 다운로드에 사용하는 암호화 토큰. **세션 종속** |

`file1=약관, file2=사업방법서, file3=요약서, file4=상품설명서` 매핑은
`salPdLst.js` 의 `$scope.pdfDown()` 분기에서 확인했습니다.

### 3.4 문서 다운로드

`/default/app/comm/fileUtil.js` 의 `o.download()` 는 2단계입니다.

1. `POST /hp/fileDownload.do` (`check=Y`) → `{"resultMsg":""}` 이면 통과
2. 동일 파라미터로 `GET` 폼 submit → 실제 파일

본 크롤러는 페이지 안에서 동일 함수를 호출하고 Playwright 의 download 이벤트로 파일을 수신합니다.

```js
inj.get('fileUtil').download('/hp/fileDownload.do', {path: enc, id: enc, orgFileName: name});
```

실측 결과: `Readycar개인용자동차보험약관.pdf`, 5,148,137 bytes, 선두 `%PDF-1.6`.

### 3.5 기타

- 페이지네이션: 없음(분류별 전체 반환, 자동차보험 분류 401건)
- 브라우저 재사용: 보험사 단위 1회 기동 후 전 상품 처리
- 테스트 가능 상품 1건: `Readycar개인용자동차보험` (bgnDt 20260707)
- 제한 사항
  - **헤드풀 브라우저가 필요**하므로 화면 세션이 있는 환경에서 실행해야 합니다(서비스 계정/무인 서버 주의).
  - `#[E]` 토큰이 세션 종속이라 목록 수집과 다운로드를 **같은 브라우저 세션 안에서** 끝내야 합니다.
  - 방화벽 정책 변경 시 `ACCESS_DENIED` 로 기록됩니다.
- `date_basis`: `sale_start_date` (`bgnDt`)

---

## 4. KB손해보험 (KB)

- 화면 URL: `https://www.kbinsure.co.kr/CG802030001.ecs`
- 수집 방식: **2순위 — 폼 POST + 정적 HTML 파싱**

### 4.1 상품목록 조회 방식

```http
POST /CG802030001.ec
Content-Type: application/x-www-form-urlencoded   (EUC-KR)

devonTargetRow=1&devonOrderBy=&gubun=&goodsNm=&onsaleYn=&bojongNo=&bojongSeq=
&search_onsale_yn=+&search_bojong_no=&search_gubun=+&search_goods_nm=
```

- 목록은 `<table class="tb_list">` 에 **서버 렌더링**됩니다(판매중지여부·보험종류·상품코드·상품명).
- 상품 링크는 `javascript:detail('10101','1','1')` → `(bojongNo, gubun, bojongSeq)`
- 페이지네이션은 **행 오프셋 방식**입니다. `goPage('11')`, `goPage('21')` … 페이지당 10행.
  실측된 마지막 페이지 오프셋이 `3991` 이므로 **약 4,000개 상품**이 등록되어 있습니다.
- `search_gubun` 보험종류 코드(실측): ` `(전체), 1 일반보험, 3 퇴직보험, 4 자동차보험, 5 단체보험,
  6 개인연금, 7 퇴직연금, a 통합보험, b 운전자보험, c 상해보험, d 질병보험, e 화재/재물보험,
  f 방카슈랑스, g 제휴, h 저축성보험, i 독립특별약관, j 제도성 특별약관, k 기타보험
- `search_onsale_yn`: ` `(전체) / `Y`(판매중) / `N`(판매중지)

### 4.2 상세(버전) 조회

```http
POST /CG802030002.ec
... bojongNo=10101&gubun=1&bojongSeq=1 ...
```

`<table class="tb_view">` 안에 **판매시작일 / 판매종료일 / 보험약관 / 사업방법서 / 상품요약서 / 비고**
열로 상품의 모든 버전이 나열됩니다. 첫 행에 `[일반보험] KB주택화재보험` 형태의 제목이 있습니다.

실측 예(상품코드 10101, 34개 버전):

| 판매시작일 | 판매종료일 | 링크 |
|---|---|---|
| 20250901 | 20251231 | `/CG802030003.ec?fileNm=20250901_10101_1.pdf` … |
| 20260101 | (없음=판매중) | `/CG802030003.ec?fileNm=20260101_10101_1.pdf` … |

### 4.3 문서 다운로드

```
GET /CG802030003.ec?fileNm={판매시작일}_{상품코드}_{n}.pdf
```

`n` = **1 보험약관 / 2 사업방법서 / 3 상품요약서** (링크 `<img alt>` 로도 판별 가능)
확장자가 `.PDF` 인 경우, 파일명에 `[0]` 이 붙는 경우가 실제로 존재하므로
**파일명을 추측하지 말고 HTML 의 `href` 를 그대로 사용**해야 합니다(실측 확인).

**주의**: 해당 문서가 없는 칸에도 `<a>` 태그가 들어 있으며 `href="javascript:stop();"` 인
자리표시자입니다(실측: `발달장애인 일상생활 배상책임보험`의 상품요약서). 이 링크는 문서 없음으로
처리해야 하며, 그대로 다운로드를 시도하면 잘못된 URL 오류가 납니다.

### 4.4 기타

- 인코딩: `text/html; charset=euc-kr`
- 판매중/중지 구분: 목록의 `판매중지여부` 열, 상세의 판매종료일 유무
- 쿠키/세션: 불필요
- Playwright: 불필요
- 테스트 가능 상품 1건: `KB주택화재보험` (bojongNo 10101 / gubun 1 / bojongSeq 1)
- **제한 사항 (중요)**
  - 목록에 날짜가 전혀 없어, 대상 월 버전을 찾으려면 **모든 상품의 상세를 열어야** 합니다.
  - 요청 수 = 목록 약 400회 + 상세 약 4,000회 ≈ **4,400회**.
    `request_interval_seconds: 2` 기준 **약 2시간 30분** 소요됩니다.
  - 체크포인트가 있으므로 중단 후 이어받기가 가능하며, 테스트 시에는 `--max-products` 로 상한을 둘 수 있습니다
    (상한을 사용하면 manifest·로그·요약에 `coverage_capped` 로 명시됩니다).
- `date_basis`: `sale_start_date`

---

## 5. 삼성화재 (SAMSUNG)

- 화면 URL: `https://www.samsungfire.com/vh/page/VH.HPIF0103.do`
- 수집 방식: **1순위 — 화면이 호출하는 JSON API 재현**

### 5.1 상품목록 조회 방식

화면 스크립트 `/sfmi/v2/ui/info/IH_IF_Terms.js` 는 `ih.sendRequest("VH.HDIF0103", {})` 한 번으로
**전체 상품 버전 목록**을 받아 클라이언트에서 필터링합니다.

`ih.sendRequest` 의 실제 HTTP 규격은 `/sfmi/v2/ui/common/ih.common.js` 에 있습니다.

```js
var url = "/vh/data/" + tranId + ".do";
param = "header=" + encodeURIComponent(JSON.stringify(header));   // header={"tranId":...}
$.ajax({url: url, data: param, type: 'POST',
        contentType: "application/x-www-form-urlencoded;charset=UTF-8"});
```

실측 요청:

```http
POST /vh/data/VH.HDIF0103.do
Content-Type: application/x-www-form-urlencoded;charset=UTF-8
Referer: https://www.samsungfire.com/vh/page/VH.HPIF0103.do

header=%7B%22tranId%22%3A%22VH.HDIF0103%22%7D
```

실측 응답(3.3MB, `responseMessage.body.data.list` 에 **9,404건**):

```json
{"prdName":"상생 기후보험","prdGun":"일반보험","prdGb":"기타","saleChannel":"대면",
 "prdCode":"KR1656P","jongGb":"0","saleStDt":"20260718","saleEnDt":"99991231","displayGb":"1",
 "prdfilename1":"/publication/pdf/KR1656P_0_20260718_file1.pdf",
 "prdfilename2":"/publication/pdf/KR1656P_0_20260718_file2.pdf"}
```

응답 봉투가 `responseMessage.body` 아래에 있다는 점에 유의해야 합니다
(`data` 를 최상위에서 찾으면 실패).

### 5.2 필드 매핑

| 필드 | 의미 |
|---|---|
| `prdName` | 상품명 |
| `prdGun` | 상품군 (장기 6,223 / 일반보험 1,648 / 자동차 1,371 / 퇴직연금 160 / 퇴직보험 2) |
| `prdGb` | 상품구분 |
| `saleChannel` | 판매채널 |
| `prdCode`, `jongGb` | 상품코드, 종구분 |
| `saleStDt` | 판매개시일 |
| `saleEnDt` | 판매종료일 (`99991231` = 판매중) |
| `displayGb` | `1`=판매중 화면 고정, `2`=판매중지 화면 고정, 그 외 = `saleEnDt` 로 판정 |
| `prdfilename1` | **약관** 경로 |
| `prdfilename2` | **사업방법서** 경로 |
| `prdfilename3` | **상품요약서** 경로 |
| `prdfilename4` | 상품설명서 (**수집 제외 대상**) |

`file1=약관 / file2=사업방법서 / file3=상품요약서 / file4=상품설명서` 매핑은
`IH_IF_Terms.js` 의 `pdfCnt_2 / pdfCnt_0 / pdfCnt_1 / pdfCnt_3` 분기와
화면 표 머리글(`사업방법서·상품요약서·보험약관`) 순서로 교차 확인했습니다.

**주의**: 파일이 없는 상품은 `prdfilenameN` **키 자체가 응답에 없습니다**. 항상 `.get()` 으로 접근해야 합니다.

### 5.3 문서 다운로드

```
GET https://www.samsungfire.com{prdfilenameN}
```

실측: `200`, `application/pdf`, 선두 `%PDF-1.7`, 1,417,373 bytes. `Content-Disposition` 없음.

### 5.4 기타

- 페이지네이션: 없음(1회 호출로 전량)
- 판매중/중지 구분: `saleEnDt != '99991231'` + `displayGb`
- 쿠키/세션: 불필요
- Playwright: 불필요
- 테스트 가능 상품 1건: `상생 기후보험` (`KR1656P`, saleStDt 20260718)
- 2026-07 판매개시: **135건**
- 제한 사항: 응답이 3MB 이상이므로 타임아웃을 넉넉히(120초) 잡아야 합니다.
- `date_basis`: `sale_start_date`

---

## 6. 공통 결론

### 6.1 날짜 기준 (요구사항 §6 우선순위 적용 결과)

5개 사 모두 **개정일/공시일을 별도 필드로 제공하지 않으며, 판매개시일이 곧 해당 버전의 적용 시작일**입니다.
따라서 5개 사 전부 `date_basis = sale_start_date` 로 기록됩니다.

- 우선순위 1(문서 적용일/개정일): 제공하는 사 없음
- 우선순위 2(판매개시일): **5개 사 모두 제공 → 채택**
- 우선순위 3(공시일/등록일): 메리츠 `putupStDdTm`(게시일)만 존재. 보조 정보로만 기록
- 우선순위 4(판매기간 시작일): 판매개시일과 동일

날짜를 전혀 파악할 수 없는 버전은 제외하지 않고 `MANUAL_REVIEW_REQUIRED` 로 기록합니다.

### 6.2 문서유형 판별

| 회사 | 약관 | 상품요약서 | 사업방법서 | 제외 |
|---|---|---|---|---|
| DB | `INPL_FINM` | `CNSL_SMAR_FINM` | `BIZ_MDDC_FINM` | `PDC_EXPP_FINM`(상품설명서) |
| 롯데 | `alt=약관` | `alt=상품요약서` | `alt=사업방법서` | — |
| 메리츠 | `file1` | `file3` | `file2` | `file4`(상품설명서) |
| KB | `alt=보험약관` (`_1.pdf`) | `alt=상품요약서` (`_3.pdf`) | `alt=사업방법서` (`_2.pdf`) | — |
| 삼성 | `prdfilename1` | `prdfilename3` | `prdfilename2` | `prdfilename4`(상품설명서) |

필드 위치가 확정적이므로 문서유형은 필드 기준으로 1차 판정하고,
표시명(라벨)으로 `config.yaml` 의 키워드 매핑을 2차 적용합니다. 둘 다 실패하면 `UNKNOWN_DOCUMENT_TYPE`.

### 6.3 2026-07 실행 실측 결과 (2026-07-31)

| 회사 | 전체 수집 버전 | 2026-07 대상 버전 | 문서 링크 | 목록 수집 시간 |
|---|---:|---:|---:|---:|
| DB손해보험 | 6 (기간검색이라 대상만 조회) | 6 | 18 | 12초 |
| 롯데손해보험 | 4,391 | 49 | 145 | 3.4초 |
| 메리츠화재 | 183 (분류별 조회) | 183 | 491 | 149초 |
| KB손해보험 | 상품 40개 표본 | 1 | 2 | 87초 (표본) |
| 삼성화재 | 9,404 | 137 | 387 | 1.4초 |

- `date_basis` 는 전 건 `sale_start_date` (삼성화재 4건만 날짜 없음 → `MANUAL_REVIEW_REQUIRED`)
- 실제 다운로드 검증: DB 18건 전량 + 나머지 4개 사 각 2개 버전 표본 → 총 34개 파일, 107.1 MB, 전부 `SUCCESS`
- 재실행 시 동일 파일은 `DUPLICATE_SKIPPED` 로 건너뛰는 것까지 확인

### 6.4 접근 제한 관련

- 메리츠화재만 웹방화벽(WAF)이 동작합니다. 우회 로직은 구현하지 않았습니다.
- 나머지 4개 사에서 `403`/CAPTCHA 는 관측되지 않았습니다.
- 모든 사에서 `robots.txt` 상 공시실 경로에 대한 명시적 차단은 확인되지 않았으나,
  요청 간격 2초·도메인당 동시요청 1을 기본값으로 적용합니다.
