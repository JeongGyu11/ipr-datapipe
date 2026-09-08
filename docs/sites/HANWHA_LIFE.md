# 한화생명 상품공시실 분석

## 1. 기본 정보

- 보험사 코드: `HANWHA_LIFE`
- 보험사명: 한화생명
- 보험 구분: 생명보험(life)
- config URL: https://www.hanwhalife.com/redirect.asp?%2Fannounce%2Fgoods%2Fgoods%2Fgoodlist01.asp=
- 실제 상품 목록 URL: 추가 수동 확인 필요
- 판매 중 상품 URL: 추가 수동 확인 필요
- 판매 중지 상품 URL: 추가 수동 확인 필요
- 확인일: 2026-07-31

## 2. 사이트 특징

- 렌더링 방식: 확인 불가
- 상품 카테고리: 확인 불가
- 판매채널 구분: 확인 불가
- 검색 조건: 확인 불가
- 날짜 제공 방식: 확인 불가
- 페이지네이션 방식: 확인 불가
- 상품 버전 표시 방식: 확인 불가
- 이전 판매기간 제공 여부: 확인 불가
- 팝업 또는 모달 사용 여부: 확인 불가

## 3. 실제 엔드포인트

| 구분 | 메서드 | 엔드포인트 | 주요 파라미터 | 응답 형식 |
|---|---|---|---|---|
| 세션 초기화 | GET | `/redirect.asp?…` | - | **`/index.jsp;jsessionid=…?goUrl=/` 로 리다이렉트됨(200, 50KB)** |
| 상품 목록 | - | 확인 불가 | - | - |
| 상품 상세 | - | 확인 불가 | - | - |
| 판매기간 | - | 확인 불가 | - | - |
| 첨부파일 목록 | - | 확인 불가 | - | - |
| 파일 다운로드 | - | 확인 불가 | - | - |

## 4. 필수 요청 정보

- Referer: 설정함(config 의 url)
- Origin: 불필요
- User-Agent: config.crawler.user_agent
- Cookie: 불필요
- 세션: `jsessionid` 부여됨
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

- Adapter 파일: `crawler/adapters/hanwha_life.py` (`HanwhaLifeAdapter`)
- 등록: `crawler/adapters/__init__.py` (`"HANWHA_LIFE": HanwhaLifeAdapter`)
- 수집 방식: JSON_API (분류·상품·판매기간 API)
- Playwright 사용 여부: 사용 안 함
- 선택한 구현 방식의 이유: 현행 공시실의 목록·상세 POST API를 직접 재현
- 공통 유틸리티 사용 내역: `BaseInsurerAdapter.client`(HttpClient),
  `utils.date_utils.parse_date`, `utils.file_utils.filename_from_content_disposition` 사용

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
- 기타 문제: **구형 TLS** — 기본 SSL 컨텍스트로는 `UNSAFE_LEGACY_RENEGOTIATION_DISABLED` 로 연결 실패. `options.legacy_ssl: true` 를 config 에 미리 설정해 두었습니다. 다만 config URL 이 홈으로 리다이렉트되어 실제 공시 목록 화면 URL 을 확정하지 못함

## 9. 확인 근거

- 확인한 화면: 리다이렉트 결과 홈 화면
- 확인한 Network 요청: `GET /redirect.asp?…` → `GET /index.jsp;jsessionid=…?goUrl=/`
- 테스트 상품: 미검증
- 테스트 파일: 미검증
- 레거시 근거(2026-07-31 수동 조사): `C:/…/scratchpad/net.py` Playwright 네트워크 로깅 출력 — 현재 저장구조/리포지토리에 포함되지 않음

---

## 10. 후속 조사 (2026-08-04)

- **최종 분류**: `INVALID_CONFIG_URL` (기존 MANUAL_REVIEW_REQUIRED 에서 원인 구체화)
- **현재 실패 단계**: **공시실 탐색**
- **정확한 원인**
  - config URL 의 옛 ASP 경로(`/announce/goods/goods/goodlist01.asp`)가 더 이상 존재하지 않아
    `https://www.hanwhalife.com/index.jsp;jsessionid=…?goUrl=/` 로 **리다이렉트**됩니다(200 / 50,171 B).
  - 홈 화면을 Playwright 로 렌더링한 뒤 `a`/`button` 을 전수 조사했지만
    '공시' 를 포함한 링크가 **한 건도 잡히지 않아** 새 공시실 URL 을 확정하지 못했습니다.
  - 구형 TLS(`UNSAFE_LEGACY_RENEGOTIATION_DISABLED`) 문제는 `options.legacy_ssl: true` 로
    이미 해결되어 **접속 자체는 정상**입니다. TLS 는 현재 원인이 아닙니다.
- **후속 작업**: 브라우저에서 전체메뉴/사이트맵을 열어 현행 상품공시실 URL 을 확인하고
  `config.yaml` 의 `resolved_disclosure_url` 을 갱신한 뒤 구조 분석을 다시 수행해야 합니다.

---

## 11. 2026-08-04 구현 결과

- **최종 분류**: `INVALID_CONFIG_URL` → **`IMPLEMENTED_HTTP`**
- **실제 상품공시실 URL(2026-08-04 확인)**
  - 판매상품 `https://www.hanwhalife.com/main/disclosure/goods/disclosurenotice/DF_GDDN000_P10000.do?MENU_ID1=DF_GDGL000&MENU_ID2=DF_GDGL000_P10000`
  - 판매중지는 목록 API 의 `sellFlag=N` 으로 구분
- **URL 발견 경로**: `robots.txt` → `sitemap_index.jsp` → `sitemap_pc.jsp` →
  `/static/main/disclosure/fund/DC_FD00000_P10000.htm` 의 '공시실' 링크 → 공시실 메인의 '판매상품' 링크
- **엔드포인트**
  | 구분 | 메서드 | 엔드포인트 | 파라미터 |
  |---|---|---|---|
  | 분류 목록 | POST | `/main/disclosure/goods/goodslist/getList.do` | `PType=1&sellFlag=Y\|N&__MENU_ID=DF_GDGL000` |
  | 상품 목록 | POST | 〃 | `PType=2&sellType&goodsType` |
  | 판매기간·문서 | POST | 〃 | `PType=3&goodsIndex=<IDX>` |
  | 파일 다운로드 | POST | `https://file.hanwhalife.com/www/announce/goods/download_chk.asp` | `file_name=<EUC-KR URL 인코딩>` |
- **응답 필드**: `SELL_START_DT`/`SELL_END_DT`, `FILE_NAME1` 상품요약서 / `FILE_NAME2` 사업방법서 / `FILE_NAME3~` 약관(복수)
- **주의**: 다운로드는 **본 사이트가 아닌 `file.hanwhalife.com`** 이고 파일명을 **EUC-KR** 로 인코딩해야 합니다.
  구형 TLS 라 `options.legacy_ssl: true` 필요.
- **검증(2026-08-04)**: 상품 4건 표본 → 4버전 / 문서 16건.
  약관 30,532,753 B · 사업방법서 775,855 B · 상품요약서 7,369,817 B 모두 `%PDF-1` 200.
- **Adapter**: `crawler/adapters/hanwha_life.py`
