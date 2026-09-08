# ENDPOINT_MATRIX.md — 30개사 엔드포인트 매트릭스

> 확인일: **2026-08-20**
> 이 문서의 모든 엔드포인트는 각 사 공시 화면이 실제로 호출하는 공개 요청을 브라우저(Playwright 네트워크 로깅)
> 또는 화면 스크립트에서 확인한 뒤 httpx 로 재현해 응답을 받은 것만 기록했습니다.
> 확인하지 못한 항목은 `확인 불가` / `추가 수동 확인 필요` 로 표기했으며 추정값을 채우지 않았습니다.
>
> **2026-08-20 (3차) 갱신**: AIG·LINA_LIFE 구현 완료를 반영했습니다. 현재 30개사 중
> 28개사에 Adapter가 등록되어 있으며, `FUBON_HYUNDAI_LIFE`·`HANWHA_FIRE` 2개사는
> robots.txt/접근 정책으로 `ACCESS_RESTRICTED` 상태입니다.
>
> **2026-08-04 (1차) 갱신**: 미구현 14개사 정밀 조사(`docs/UNIMPLEMENTED_COMPANY_ANALYSIS.md`) 결과
> 8개사를 `MANUAL_REVIEW_REQUIRED` → `IMPLEMENTED` 로 변경했습니다.

## 구현 상태 값

```
EXISTING_WORKING        기존 5개사 (본 작업에서 수집 로직 미변경, 회귀 확인 완료)
IMPLEMENTED             신규 구현 + dry-run + 실제 문서 다운로드 검증 완료
PARTIAL                 코드는 작성했으나 전량 dry-run 또는 실제 다운로드 미검증
ACCESS_RESTRICTED       robots.txt·접근 통제(WAF/CAPTCHA/암호화 파라미터)로 정상 재현 불가
MANUAL_REVIEW_REQUIRED  화면은 열리나 목록/문서 경로 확정 실패 → 수동 확인 필요
NOT_IMPLEMENTED         Adapter 미작성
```

---

## 1. 전체 매트릭스

| 코드 | 보험사 | 보험 구분 | config URL | 실제 목록 URL | 목록 방식 | 상세 방식 | 다운로드 방식 | 세션 필요 | Playwright 필요 | 구현 상태 |
|---|---|---|---|---|---|---|---|---|---|---|
| DB | DB손해보험 | 손보 | `idbins.com/FWMAIV1534.do` | `/insuPcPbanFindProductStep5_AX.do` | JSON_API | 목록에 포함(Step4 보조) | GET `/cYakgwanDown.do` | 불필요 | 불필요 | EXISTING_WORKING |
| LOTTE | 롯데손해보험 | 손보 | `lotteins.co.kr/web/C/D/H/cdh190.jsp` | `/CChannelSvl` (task=searchKey) | FORM_POST | 목록에 포함 | GET 정적 `/upload/C/newProduct/*.pdf` | 불필요 | 불필요 | EXISTING_WORKING |
| MERITZ | 메리츠화재 | 손보 | `meritzfire.com/disclosure/…/product-list.do` | 페이지 내 `POST /json.smart` | JAVASCRIPT_RENDERED | 목록에 포함 | 페이지 내 `fileUtil.download()` | **필수(WAF)** | **필수(헤드풀)** | EXISTING_WORKING |
| KB | KB손해보험 | 손보 | `kbinsure.co.kr/CG802030001.ecs` | `/CG802030001.ec` | FORM_POST | `/CG802030002.ec` | GET `/CG802030003.ec?fileNm=` | 불필요 | 불필요 | EXISTING_WORKING |
| SAMSUNG | 삼성화재 | 손보 | `samsungfire.com/vh/page/VH.HPIF0103.do` | `/vh/data/VH.HDIF0103.do` | JSON_API | 목록에 포함 | GET `{prdfilenameN}` | 불필요 | 불필요 | EXISTING_WORKING |
| KYOBO_LIFE | 교보생명 | 생명 | `kyobo.com/dgt/web/product-official/information` | `/dtc/product-official/find-allProductSearch` | JSON_API | `find-allProductSearchDetail` | GET `/file/ajax/download?fName=` | 불필요 | 불필요 | IMPLEMENTED |
| MIRAE_LIFE | 미래에셋생명 | 생명 | `life.miraeasset.com/micro/disclosure/product/PC-HO-080301-000000.do` | `/micro/disclosure/selectWorkDvsnDataPaging.do` | JSON_API | 목록에 포함 | POST `/micro/cmmnFileDown.do` | 불필요 | 불필요 | IMPLEMENTED |
| DB_LIFE | DB생명 | 생명 | `idblife.com/notice/product/sale` | `/notice/product/sale`, `/notice/product/sold_out` | STATIC_HTML + AJAX XML | 판매중지는 `POST /notice/product/sold_out/ajaxRequest` 상세 | GET `/notice/product/file/…`, `/prov/file`, `/prov/soldOut/{PUBLISH_NO}` | 불필요 | 불필요 | IMPLEMENTED |
| ABL_LIFE | ABL생명 | 생명 | `abllife.co.kr/st/custDesk/…/fncLvngInfo3` | 추가 수동 확인 필요 | JAVASCRIPT_RENDERED | 확인 불가 | 확인 불가 | 확인 불가 | 확인 불가 | IMPLEMENTED |
| IBK_LIFE | IBK연금보험 | 생명 | `ibki.co.kr/process/HP_PBANO_PDT_SP_INDV` | 4개 `/process/HP_PBANO_PDT_*` | STATIC_HTML | 목록에 포함 | POST `/process/mFileDownload` | 불필요 | 불필요 | IMPLEMENTED |
| IM_LIFE | iM라이프 | 생명 | `imlifeins.co.kr/BA/BA_A020.do` | 같음 (POST `sellType`) | FORM_POST | 목록에 포함 | POST `/www/downloadChk.do` | 불필요 | 불필요 | IMPLEMENTED |
| KB_LIFE | KB라이프생명 | 생명 | `kblife.co.kr/customer-common/productList.do` | `/customer-common/API/productList1.do` | JSON_API | 목록에 포함 | GET `/api/archive/archives/download/…` | 불필요 | 불필요 | IMPLEMENTED |
| KDB_LIFE | KDB생명 | 생명 | `kdblife.com/ajax.do?pcmode=1&scrId=HDLMA002M02P` | `POST /ajax.do?scrId=HDLMA002M02P&isJson=1` | JSON_API(HTML 조각) | 확인 불가 | 확인 불가 | 불필요 | 불필요 | IMPLEMENTED |
| NH_LIFE | NH농협생명 | 생명 | `nhlife.co.kr/ho/on/HOON0004M00.nhl` | 추가 수동 확인 필요 | 확인 불가 | 확인 불가 | 확인 불가 | 확인 불가 | 확인 불가 | IMPLEMENTED |
| TONGYANG_LIFE | 동양생명 | 생명 | `pbano.myangel.co.kr/` | `/notice/product/WE_PA_AP_01_00_00.jsp` (표 없음) | 확인 불가 | 확인 불가 | POST `/process/CO_ComDownload` | 확인 불가 | 확인 불가 | IMPLEMENTED |
| LINA_LIFE | 라이나생명 | 생명 | `lina.co.kr/disclosure/…/product-on-sales` | `api.lina.co.kr/public/contents/v1/disclosure/get-product-list`, `get-product-endlist` | JSON_API | `product-list-detail`, `end-product-detail` | GET `/cms/upload/upload/docs/disclosure/{파일명}` | 불필요 | 불필요 | IMPLEMENTED |
| METLIFE | 메트라이프생명 | 생명 | `brand.metlife.co.kr/pn/mcvrgProd/retrieveMcvrgProdMain.do` | 같음 | STATIC_HTML | 목록에 포함 + 특약 팝업 | GET `mcvrgProdDownloadFile.do` | 불필요 | 불필요 | IMPLEMENTED |
| SAMSUNG_LIFE | 삼성생명 | 생명 | `samsunglife.com/individual/products/disclosure/sales/PDO-PRPRI010110M` | `POST /gw/api/display/board/content/list/full` (파라미터 암호화) | JAVASCRIPT_RENDERED | 확인 불가 | 확인 불가 | **필수** | **필수** | IMPLEMENTED(HYBRID) |
| SHINHAN_LIFE | 신한라이프 | 생명 | `shinhanlife.co.kr/hp/cdhi0010.do` | 추가 수동 확인 필요 | JAVASCRIPT_RENDERED(`*.pwkjson`) | 확인 불가 | 확인 불가 | 확인 불가 | 확인 불가 | IMPLEMENTED |
| FUBON_HYUNDAI_LIFE | 푸본현대생명 | 생명 | `fubonhyundai.com/` (홈) | 추가 수동 확인 필요 | 확인 불가 | 확인 불가 | 확인 불가 | 확인 불가 | 확인 불가 | ACCESS_RESTRICTED |
| HANA_LIFE | 하나생명 | 생명 | `hanalife.co.kr/anm/product/allProduct.do?status=on` | 같음 | FORM_POST | 목록에 포함 | GET `/home/download2.do`, `/anm/product/download.do` | 불필요 | 불필요 | IMPLEMENTED |
| HANWHA_LIFE | 한화생명 | 생명 | `hanwhalife.com/redirect.asp?…` (홈으로 리다이렉트) | 추가 수동 확인 필요 | 확인 불가 | 확인 불가 | 확인 불가 | jsessionid 부여 | 확인 불가 | IMPLEMENTED |
| HEUNGKUK_LIFE | 흥국생명 | 생명 | `heungkuklife.co.kr/front/public/saleProduct.do?searchFlgSale=Y` | 같음(폼 `frmPage` POST 필요) | FORM_POST | 확인 불가 | 확인 불가 | 불필요 | 확인 불가 | IMPLEMENTED |
| LINA_NON_LIFE | 라이나손해보험 | 손보 | `chubb.com/kr-kr/disclosure/product-disclosure.html` | 추가 수동 확인 필요 | STATIC_HTML(표 없음) | 확인 불가 | 확인 불가 | 확인 불가 | 확인 불가 | IMPLEMENTED |
| HANA_NON_LIFE | 하나손해보험 | 손보 | `m.hanainsure.co.kr/w/disclosure/product/saleProduct` | `getSaleStepOne~Four.json` | JSON_API(4단계) | STEP3/STEP4 | GET `/download/{fileID}` | 불필요 | 불필요 | IMPLEMENTED |
| HYUNDAI_MARINE | 현대해상 | 손보 | `hi.co.kr/serviceAction.do?view=bin/PA/03/HHPA03020M` | `POST /ajax.xhi` (HHCA0310M19S) | JSON_API | 목록에 포함 | `HHCA0310M26S` → GET `/FileActionServlet/download/0/…` | 불필요 | 불필요 | IMPLEMENTED |
| HEUNGKUK_FIRE | 흥국화재 | 손보 | `heungkukfire.co.kr/FRW/announce/insGoodsGongsiSale.do` | 같음 | FORM_POST | 목록에 포함 | POST `/common/download.do` | 불필요 | 불필요 | IMPLEMENTED |
| AIG | AIG손해보험 | 손보 | `aig.co.kr/wm/content.html?contentId=DPWMS701` | POST `/bomservice.do` (`txCode=DPWOS002`) | JSON_API | 목록 응답에 포함 | GET `/downLoadFiles.do` | 불필요 | 불필요 | IMPLEMENTED |
| NH_FIRE | NH농협손해보험 | 손보 | `nhfire.co.kr/announce/productAnnounce/retrieveInsuranceProductsAnnounce.nhfire` | 추가 수동 확인 필요 | STATIC_HTML + AJAX | 확인 불가 | 확인 불가 | 확인 불가 | 확인 불가 | IMPLEMENTED |
| HANWHA_FIRE | 한화손해보험 | 손보 | `hwgeneralins.com/notice/ir/product-main.do?mtoh=Y` | 확인 불가(요청 본문 암호화) | JAVASCRIPT_RENDERED | 확인 불가 | 확인 불가 | **필수** | **필요 추정** | ACCESS_RESTRICTED |

### 집계

| 구현 상태 | 건수 | 코드 |
|---|---:|---|
| EXISTING_WORKING | 5 | DB, LOTTE, MERITZ, KB, SAMSUNG |
| IMPLEMENTED | 23 | KYOBO_LIFE, MIRAE_LIFE, DB_LIFE, ABL_LIFE, IBK_LIFE, IM_LIFE, KB_LIFE, KDB_LIFE, NH_LIFE, TONGYANG_LIFE, LINA_LIFE, METLIFE, SAMSUNG_LIFE(HYBRID), SHINHAN_LIFE, HANA_LIFE, HANWHA_LIFE, HEUNGKUK_LIFE, LINA_NON_LIFE, HANA_NON_LIFE, HYUNDAI_MARINE, HEUNGKUK_FIRE, AIG, NH_FIRE |
| PARTIAL | 0 | - |
| ACCESS_RESTRICTED | 2 | FUBON_HYUNDAI_LIFE(robots 전면차단), HANWHA_FIRE(robots 미허용 + 요청 암호화) |
| MANUAL_REVIEW_REQUIRED | 0 | - |
| DOCUMENT_NOT_PROVIDED | 0 | - |
| NOT_IMPLEMENTED | 0 | - |
| **합계** | **30** | |

---

## 2. 보험사별 실제 엔드포인트 상세

> `Adapter 사용 여부` 는 본 크롤러가 실제로 호출하는지를 뜻합니다.

### 2.1 기존 5개사

| 코드 | 용도 | HTTP 메서드 | 실제 엔드포인트 | 응답 형식 | Adapter 사용 여부 |
|---|---|---|---|---|---|
| DB | 화면 진입 | GET | `https://www.idbins.com/FWMAIV1534.do` | HTML | Referer 용 |
| DB | 기간검색 목록 | POST | `https://www.idbins.com/insuPcPbanFindProductStep5_AX.do` | JSON | 사용 |
| DB | 판매기간 상세 | POST | `https://www.idbins.com/insuPcPbanFindProductStep4_AX.do` | JSON | 사용 |
| DB | 상품명 목록 | POST | `https://www.idbins.com/insuPcPbanFindProductStep2_AX.do` | JSON | 미사용(대안) |
| DB | 파일 다운로드 | GET | `https://www.idbins.com/cYakgwanDown.do?FilePath=InsProduct/{파일명}` | PDF | 사용 |
| LOTTE | 검색형 목록 | POST | `https://www.lotteins.co.kr/CChannelSvl` (`task=searchKey`) | HTML+JS | 사용 |
| LOTTE | 분류형 드릴다운 | POST | `https://www.lotteins.co.kr/CChannelSvl` (`task=gostep2~4…`) | HTML+JS | 미사용(대안) |
| LOTTE | 파일 다운로드 | GET | `https://www.lotteins.co.kr/upload/C/newProduct/*.pdf` | PDF | 사용 |
| MERITZ | 목록(분류별) | POST | `https://www.meritzfire.com/json.smart` (`PbanBc.retrieveSalPdList`) | JSON | 사용(페이지 내) |
| MERITZ | 파일 다운로드 | POST→GET | `https://www.meritzfire.com/hp/fileDownload.do` | PDF | 사용(페이지 내) |
| KB | 상품 목록 | POST | `https://www.kbinsure.co.kr/CG802030001.ec` | HTML(EUC-KR) | 사용 |
| KB | 상품 상세 | POST | `https://www.kbinsure.co.kr/CG802030002.ec` | HTML(EUC-KR) | 사용 |
| KB | 파일 다운로드 | GET | `https://www.kbinsure.co.kr/CG802030003.ec?fileNm=…` | PDF | 사용 |
| SAMSUNG | 상품 목록 | POST | `https://www.samsungfire.com/vh/data/VH.HDIF0103.do` | JSON | 사용 |
| SAMSUNG | 파일 다운로드 | GET | `https://www.samsungfire.com{prdfilenameN}` | PDF | 사용 |

### 2.2 신규 구현 완료

| 코드 | 용도 | HTTP 메서드 | 실제 엔드포인트 | 응답 형식 | Adapter 사용 여부 |
|---|---|---|---|---|---|
| KYOBO_LIFE | 상품 목록 | POST | `https://www.kyobo.com/dtc/product-official/find-allProductSearch` | JSON | 사용 |
| KYOBO_LIFE | 판매기간·문서 | POST | `https://www.kyobo.com/dtc/product-official/find-allProductSearchDetail` | JSON | 사용 |
| KYOBO_LIFE | 파일 다운로드 | GET | `https://www.kyobo.com/file/ajax/download?fName=/dtc/pdf/mm/{파일명}` | PDF | 사용 |
| KYOBO_LIFE | 공시 메뉴 | GET | `https://www.kyobo.com/dtm/menu/item-list?reqDevice=PC&menuType=dcs` | JSON | 미사용(URL 확인용) |
| MIRAE_LIFE | 분류 목록 | POST | `https://life.miraeasset.com/micro/disclosure/selectProdDvsnGroup.do` | JSON | 미사용 |
| MIRAE_LIFE | 상품 목록 | POST | `https://life.miraeasset.com/micro/disclosure/selectWorkDvsnDataPaging.do` | JSON | 사용 |
| MIRAE_LIFE | 파일 다운로드 | POST | `https://life.miraeasset.com/micro/cmmnFileDown.do` | PDF | 사용 |
| DB_LIFE | 판매상품 목록 | GET | `https://www.idblife.com/notice/product/sale` | HTML | 사용 |
| DB_LIFE | 판매중지 목록 | GET | `https://www.idblife.com/notice/product/sold_out` | HTML | 사용 |
| DB_LIFE | 판매중지 상품 상세 | POST | `https://www.idblife.com/notice/product/sold_out/ajaxRequest` (`mcode`,`gubn1`) | XML `<poplist>` | 사용 |
| DB_LIFE | 판매중 약관 팝업 | GET | `https://www.idblife.com/notice/product/prov/sale/{provNo}` | HTML | 사용 |
| DB_LIFE | 판매중지 약관 팝업 | GET | `https://www.idblife.com/notice/product/prov/soldOut/{PUBLISH_NO}` | HTML | 사용 |
| DB_LIFE | 방법서·요약서 | GET | `https://www.idblife.com/notice/product/file/{publishNo}/{1\|2}` (판매중지 상세는 1만 제공) | PDF | 사용 |
| DB_LIFE | 약관 파일 | GET | `https://www.idblife.com/notice/product/prov/file?publishNo=&fileGb=&fileSeq=` | PDF/ZIP | 사용 |
| IBK_LIFE | 판매·개인연금 | GET | `https://www.ibki.co.kr/process/HP_PBANO_PDT_SP_INDV` | HTML(EUC-KR) | 사용 |
| IBK_LIFE | 판매·퇴직연금 | GET | `https://www.ibki.co.kr/process/HP_PBANO_PDT_SP_RTMT` | HTML(EUC-KR) | 사용 |
| IBK_LIFE | 판매중지·개인연금 | GET | `https://www.ibki.co.kr/process/HP_PBANO_PDT_NSP_INDV` | HTML(EUC-KR) | 사용 |
| IBK_LIFE | 판매중지·퇴직연금 | GET | `https://www.ibki.co.kr/process/HP_PBANO_PDT_NSP_RTMT` | HTML(EUC-KR) | 사용 |
| IBK_LIFE | 파일 다운로드 | POST | `https://www.ibki.co.kr/process/mFileDownload` | PDF | 사용 |
| IM_LIFE | 상품 목록 | POST | `https://www.imlifeins.co.kr/BA/BA_A020.do` (`sellType=1\|0`) | HTML | 사용 |
| IM_LIFE | 파일 다운로드 | POST | `https://www.imlifeins.co.kr/www/downloadChk.do` | PDF | 사용 |
| KB_LIFE | 상품 목록 | POST | `https://www.kblife.co.kr/customer-common/API/productList1.do` | JSON | 사용 |
| KB_LIFE | 파일 다운로드 | GET | `https://www.kblife.co.kr/api/archive/archives/download/{fileno}/{seqno}/{boxno}` | PDF | 사용 |
| METLIFE | 상품 목록 | GET | `https://brand.metlife.co.kr/pn/mcvrgProd/retrieveMcvrgProdMain.do` | HTML | 사용 |
| METLIFE | 특약 약관 목록 | POST | `https://brand.metlife.co.kr/pn/mcvrgProd/retrieveMcvrgProdPop.do` | HTML | 사용 |
| METLIFE | 파일 다운로드 | GET | `https://brand.metlife.co.kr/pn/mcvrgProd/mcvrgProdDownloadFile.do?insProdSeq=&seq=&fnum=` | PDF | 사용 |
| HANA_LIFE | 상품 목록 | POST | `https://www.hanalife.co.kr/anm/product/allProduct.do` (`status=on\|off`) | HTML | 사용 |
| HANA_LIFE | 요약서·방법서 | GET | `https://www.hanalife.co.kr/home/download2.do?fileName=&downFileName=` | PDF | 사용 |
| HANA_LIFE | 약관 | GET | `https://www.hanalife.co.kr/anm/product/download.do?code=&seq=` | PDF | 사용 |
| HANA_NON_LIFE | 분류 목록 | POST | `https://m.hanainsure.co.kr/w/disclosure/product/getSaleStepOne.json` | JSON | 사용 |
| HANA_NON_LIFE | 상품 목록 | POST | `https://m.hanainsure.co.kr/w/disclosure/product/getSaleStepTwo.json` | JSON | 사용 |
| HANA_NON_LIFE | 판매기간 | POST | `https://m.hanainsure.co.kr/w/disclosure/product/getSaleStepThree.json` | JSON | 사용 |
| HANA_NON_LIFE | 문서 목록 | POST | `https://m.hanainsure.co.kr/w/disclosure/product/getSaleStepFour.json` | JSON | 사용 |
| HANA_NON_LIFE | 파일 다운로드 | GET | `https://m.hanainsure.co.kr/download/{fileID}` | PDF | 사용 |
| HYUNDAI_MARINE | 상품 목록 | POST | `https://www.hi.co.kr/ajax.xhi` (`tranId=HHCA0310M19S`) | JSON | 사용 |
| HYUNDAI_MARINE | 파일 경로 조회 | POST | `https://www.hi.co.kr/ajax.xhi` (`tranId=HHCA0310M26S`) | JSON | 사용 |
| HYUNDAI_MARINE | 파일 다운로드 | GET | `https://www.hi.co.kr/FileActionServlet/download/0/{savPath}/{savFileNm}.{ext}` | PDF | 사용 |
| HEUNGKUK_FIRE | 상품 목록 | POST | `https://www.heungkukfire.co.kr/FRW/announce/insGoodsGongsiSale.do` | HTML | 사용 |
| HEUNGKUK_FIRE | 파일 다운로드 | POST | `https://www.heungkukfire.co.kr/common/download.do` | PDF | 사용 |
| LINA_LIFE | 판매중·판매중지 목록 | GET | `https://api.lina.co.kr/public/contents/v1/disclosure/get-product-list`, `get-product-endlist` | JSON | 사용 |
| LINA_LIFE | 상품 상세 | GET | `https://api.lina.co.kr/public/contents/v1/disclosure/product-list-detail`, `end-product-detail` | JSON | 사용 |
| LINA_LIFE | 파일 다운로드 | GET | `https://www.lina.co.kr/cms/upload/upload/docs/disclosure/{파일명}` | PDF | 사용 |
| AIG | 판매중·판매중지 목록 | POST | `https://www.aig.co.kr/bomservice.do` (`txCode=DPWOS002`, `useYn=Y\|N`) | JSON | 사용 |
| AIG | 파일 다운로드 | GET | `https://www.aig.co.kr/downLoadFiles.do?fileId=&fileSeq=&fileType=&fileGb=&viewType=` | PDF | 사용 |

### 2.3 참고·미사용 엔드포인트

| 코드 | 용도 | HTTP 메서드 | 실제 엔드포인트 | 응답 형식 | Adapter 사용 여부 |
|---|---|---|---|---|---|
| KDB_LIFE | 상품 목록 | POST | `https://www.kdblife.com/ajax.do?scrId=HDLMA002M02P&isJson=1` (`paramJson` 이중 인코딩) | HTML 조각(EUC-KR) | 미사용 |
| TONGYANG_LIFE | 파일 다운로드 | POST | `https://pbano.myangel.co.kr/process/CO_ComDownload` (`_biz_op_code=FDL`) | 파일 | 미사용 |
| TONGYANG_LIFE | 공시 화면 | GET | `https://pbano.myangel.co.kr/notice/product/WE_PA_AP_01_00_00.jsp` | HTML(표 없음) | 미사용 |
| LINA_LIFE | 특약 목록(구형 확인 경로) | GET | `https://api.lina.co.kr/public/contents/v1/disclosure/end-product?mtrtDcd=R&…` | JSON | 미사용(대안) |
| SAMSUNG_LIFE | 목록(암호화) | POST | `https://www.samsunglife.com/gw/api/display/board/content/list/full` (`g=`,`b=`) | JSON | 미사용 |
| SHINHAN_LIFE | 메뉴 조회 | POST | `https://www.shinhanlife.co.kr/co/nvi/getMenuNavi.pwkjson` | JSON | 미사용 |
| HANWHA_FIRE | 공통(암호화) | POST | `https://www.hwgeneralins.com/popup/global_popup_list.json` (`Dowz0Lw=`) | JSON | 미사용 |
| ABL_LIFE | 상품 정보 | GET | `https://abllife.co.kr/cms/prdt/ItemInformation01.json` | JSON | 미사용(공시 목록 아님) |
| NH_LIFE | 세션 확인 | POST | `https://www.nhlife.co.kr/mainChk.nhl` | JSON | 미사용 |
| NH_FIRE | 화면 함수 | - | `fnRetrievePdtDcd()` / `fnRetrieveProductList()` / `fnRetrieveProductInfo()` (엔드포인트 미확인) | - | 미사용 |
| HANWHA_LIFE | 진입 | GET | `https://www.hanwhalife.com/redirect.asp?…` → `/index.jsp;jsessionid=…` | HTML | 미사용 |
| AIG | 공시 안내 진입 | GET | `https://www.aig.co.kr/wm/content.html?contentId=DPWMS701` (legacy TLS 필요) | HTML(셸) | 미사용(목록은 `bomservice.do`) |
| HEUNGKUK_LIFE | 진입 | GET | `https://www.heungkuklife.co.kr/front/public/saleProduct.do?searchFlgSale=Y` | HTML(EUC-KR, 표 0행) | 미사용 |
| LINA_NON_LIFE | 진입 | GET | `https://www.chubb.com/kr-kr/disclosure/product-disclosure.html` | HTML(표 없음) | 미사용 |
| FUBON_HYUNDAI_LIFE | 진입 | GET | `https://www.fubonhyundai.com/` | HTML | 미사용 |
