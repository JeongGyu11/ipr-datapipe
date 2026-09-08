"""KB손해보험 Adapter.

수집 방식: 폼 POST + 정적 HTML 파싱 (SITE_ANALYSIS.md §4)
  - 목록: POST /CG802030001.ec  (devonTargetRow = 1, 11, 21 … 행 오프셋 페이지네이션)
  - 상세: POST /CG802030002.ec  (bojongNo, gubun, bojongSeq) -> 버전별 판매기간 + 문서 링크
  - 문서: GET  /CG802030003.ec?fileNm=...

주의: 목록에 날짜가 없어 대상 월 버전을 찾으려면 모든 상품의 상세를 열어야 한다.
      전체 순회 시 약 4,400 요청 / 약 2시간 30분(요청간격 2초)이 소요된다.
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import date
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from crawler.base_adapter import BaseInsurerAdapter, FetchResult
from crawler.http_client import AccessDeniedError
from crawler.kb_checkpoint_service import KBCheckpointService
from crawler.validators import looks_like_html
from models.document import Document
from models.product_version import ProductVersion
from utils.date_utils import parse_date
from utils.file_utils import filename_from_url, guess_extension

BASE = "https://www.kbinsure.co.kr"
LIST_URL = f"{BASE}/CG802030001.ec"
DETAIL_URL = f"{BASE}/CG802030002.ec"
PAGE_SIZE = 10

_DETAIL_CALL = re.compile(r"detail\(\s*'([^']*)'\s*,\s*'([^']*)'\s*,\s*'([^']*)'\s*\)")
_GO_PAGE = re.compile(r"goPage\('(\d+)'\)")
_TITLE = re.compile(r"^\s*\[(?P<category>[^\]]*)\]\s*(?P<name>.+?)\s*$")


class KBInsuranceAdapter(BaseInsurerAdapter):
    code = "KB"
    collection_method = "2순위 - 폼 POST + 정적 HTML 파싱 (목록 페이지네이션 + 상세 순회)"
    detail_checkpoint_filename = "detail_checkpoint.v2.jsonl"

    def collect_product_versions(self, start_date: date, end_date: date) -> list[ProductVersion]:
        """상품별 상세에서 발견한 모든 버전을 반환한다.

        KB 목록에는 날짜가 없고 상세 응답 한 건에 여러 과거 버전이 함께
        있으므로, 기간 필터는 공통 manager가 수행한다. ``start_date``와
        ``end_date``는 BaseAdapter 호환을 위해 받지만 여기서는 사용하지 않는다.
        """
        self.stats["status_coverage_complete"] = False
        max_products = self.runtime_options.get("max_products")
        max_products = int(max_products) if max_products else None

        products, total_available = self._collect_products(limit=max_products)
        if max_products and total_available and total_available > len(products):
            self.log.warning(
                "[KB] max_products=%d 적용: 등록 상품 약 %d개 중 %d개만 조회합니다 (coverage_capped).",
                max_products, total_available, len(products),
            )
            self.stats["coverage_capped"] = True
            self.stats["products_total"] = total_available
            self.stats["products_skipped"] = total_available - len(products)

        self.stats["products_scanned"] = len(products)
        # A configured limit is intentionally partial even when the server's
        # estimated total happens to equal the limit: status reconciliation
        # must never infer absence from a capped traversal.  Keep the flag
        # false until every detail has completed below.
        self.log.info("[KB] 상품 %d개의 상세를 조회합니다.", len(products))

        versions: list[ProductVersion] = []
        checkpoint = self._checkpoint_service()
        reused = 0
        failed = 0
        for index, product in enumerate(products, start=1):
            if index % 50 == 0:
                self.log.info("[KB] 상세 조회 진행 %d/%d", index, len(products))
            active_match = self._matches_active_product(product)
            # ACTIVE manifest identities must be revalidated against today's
            # detail, even when a completed checkpoint exists.  The fresh
            # response is recorded below and therefore reused by subsequent
            # runs without a second request in this pass.
            cached = None if active_match else (checkpoint.reusable(product) if checkpoint is not None else None)
            if cached is not None:
                product_versions = cached.versions
                reused += 1
            else:
                try:
                    product_versions, complete = self._collect_versions_with_status(product)
                except AccessDeniedError:
                    if checkpoint is not None:
                        checkpoint.record_failure(product, "access denied")
                    raise
                except Exception as exc:  # noqa: BLE001 - 상품 단위 재개를 위해 기록
                    if checkpoint is not None:
                        checkpoint.record_failure(product, f"{type(exc).__name__}: {exc}")
                    failed += 1
                    self.log.exception("[KB] 상세 조회 예외 %s", product.get("product_code", ""))
                    continue
                if not complete:
                    if checkpoint is not None:
                        checkpoint.record_failure(product, "상세 응답을 완전히 해석하지 못했습니다")
                    failed += 1
                    continue
                if checkpoint is not None:
                    checkpoint.record_success(product, product_versions)
            for version in product_versions:
                versions.append(version)
        self.stats["detail_checkpoint_reused"] = reused
        self.stats["detail_checkpoint_failed"] = failed
        if failed:
            raise RuntimeError(
                f"KB 상품 상세 {failed}건을 완전히 수집하지 못했습니다. "
                "완료된 상품은 체크포인트에 보존되므로 같은 기간으로 재실행해 주세요."
            )
        self.stats["status_coverage_complete"] = (not bool(max_products)) and failed == 0
        return versions

    def _matches_active_product(self, product: dict) -> bool:
        rows = self.active_status_rows
        if not rows:
            return False
        source_id = "|".join((str(product.get("bojong_no") or ""), str(product.get("gubun") or ""), str(product.get("bojong_seq") or "")))
        return self.matches_active_status_reference(
            source_product_id=source_id,
            product_name=product.get("product_name") or "",
        )

    def _checkpoint_service(self) -> KBCheckpointService | None:
        """옵션이 설정된 경우에만 KB 상세 체크포인트를 활성화한다.

        Manager가 기간 scope별 경로를 ``detail_checkpoint_path``로 전달한다.
        기본값은 None으로 두어 예상치 못한 캐시 재사용을 하지 않는다.
        """
        options = self.runtime_options
        root = options.get("detail_checkpoint_path")
        if not root:
            return None
        if not hasattr(self, "_detail_checkpoint"):
            scope = str(options.get("detail_checkpoint_scope") or "default")
            self._detail_checkpoint = KBCheckpointService(root, scope=scope)
        return self._detail_checkpoint

    def configure_detail_checkpoint(self, root: str, scope: str = "default") -> KBCheckpointService:
        """실행 관리자가 기간 scope를 명시해 체크포인트를 켠다.

        immutable 회사 정의를 변경하지 않고 별도의 runtime option을 갱신한다.
        같은 Adapter 인스턴스에서 scope를 바꿀 때는 기존 서비스도 교체하여
        서로 다른 백필 결과가 섞이지 않게 한다.
        """
        self.runtime_options = {
            **self.runtime_options,
            "detail_checkpoint_path": root,
            "detail_checkpoint_scope": scope,
        }
        self._detail_checkpoint = KBCheckpointService(root, scope=scope)
        return self._detail_checkpoint

    # ------------------------------------------------------------------
    def _form(self, **overrides) -> dict:
        payload = {
            "devonTargetRow": "1",
            "devonOrderBy": "",
            "gubun": "",
            "goodsNm": "",
            "onsaleYn": "",
            "bojongNo": "",
            "bojongSeq": "",
            "search_onsale_yn": " ",
            "search_bojong_no": "",
            "search_gubun": " ",
            "search_goods_nm": "",
        }
        payload.update(overrides)
        return payload

    def _collect_products(self, limit: int | None = None) -> tuple[list[dict], int]:
        """전 페이지를 순회하며 상품 목록을 모은다.

        limit 이 주어지면 그만큼 모은 즉시 목록 순회를 멈춘다(테스트용).
        반환값은 (상품 목록, 사이트에 등록된 전체 상품 추정 수).
        """
        products: list[dict] = []
        seen: set[tuple] = set()
        offset = 1
        last_offset: int | None = None

        while True:
            response = self.client.post(LIST_URL, data=self._form(devonTargetRow=str(offset)))
            if response.status_code != 200:
                raise RuntimeError(f"KB 목록 조회 실패 offset={offset} HTTP {response.status_code}")
            soup = BeautifulSoup(response.text, "lxml")

            if last_offset is None:
                offsets = [int(x) for x in _GO_PAGE.findall(response.text)]
                last_offset = max(offsets) if offsets else offset
                self.log.info("[KB] 마지막 페이지 오프셋 %d (약 %d개 상품)", last_offset, last_offset + PAGE_SIZE - 1)

            rows = self._parse_list_rows(soup)
            if not rows:
                raise RuntimeError(f"KB 목록을 해석하지 못했습니다 offset={offset}")
            new_rows = 0
            for row in rows:
                key = (row["bojong_no"], row["gubun"], row["bojong_seq"])
                if key in seen:
                    continue
                seen.add(key)
                products.append(row)
                new_rows += 1
            if new_rows == 0:
                raise RuntimeError(f"KB 목록 페이지가 반복되었습니다 offset={offset}")
            if limit is not None and len(products) >= limit:
                products = products[:limit]
                break

            offset += PAGE_SIZE
            if last_offset is not None and offset > last_offset:
                break

        total_available = (last_offset + PAGE_SIZE - 1) if last_offset else len(products)
        return products, total_available

    @staticmethod
    def _parse_list_rows(soup: BeautifulSoup) -> list[dict]:
        table = soup.find("table", class_="tb_list")
        if table is None:
            return []
        rows = []
        for tr in table.find_all("tr"):
            cells = tr.find_all("td")
            if len(cells) < 4:
                continue
            anchor = cells[3].find("a")
            if anchor is None:
                continue
            match = _DETAIL_CALL.search(anchor.get("href") or "")
            if not match:
                continue
            rows.append(
                {
                    "sale_status": cells[0].get_text(" ", strip=True),
                    "category": cells[1].get_text(" ", strip=True),
                    "product_code": cells[2].get_text(" ", strip=True),
                    "product_name": anchor.get_text(" ", strip=True),
                    "bojong_no": match.group(1),
                    "gubun": match.group(2),
                    "bojong_seq": match.group(3),
                }
            )
        return rows

    # ------------------------------------------------------------------
    def _collect_versions(self, product: dict) -> list[ProductVersion]:
        versions, _ = self._collect_versions_with_status(product)
        return versions

    def _collect_versions_with_status(self, product: dict) -> tuple[list[ProductVersion], bool]:
        """상세 버전과 응답 완전성 여부를 함께 반환한다."""
        response = self.client.post(
            DETAIL_URL,
            data=self._form(
                bojongNo=product["bojong_no"],
                gubun=product["gubun"],
                bojongSeq=product["bojong_seq"],
            ),
        )
        if response.status_code != 200:
            self.log.warning(
                "[KB] 상세 조회 실패 %s HTTP %d", product["product_code"], response.status_code
            )
            return [], False

        soup = BeautifulSoup(response.text, "lxml")
        outer = soup.find("table", class_="tb_view")
        if outer is None:
            return [], False

        product_name = product["product_name"]
        category = product["category"]
        first_cell = outer.find(["td", "th"])
        if first_cell is not None:
            match = _TITLE.match(first_cell.get_text(" ", strip=True))
            if match:
                category = match.group("category") or category
                product_name = match.group("name") or product_name

        table = outer.find("table") or outer
        versions: list[ProductVersion] = []
        candidate_rows = 0
        for row_index, tr in enumerate(table.find_all("tr"), start=1):
            cells = tr.find_all("td")
            # 일반 상품은 약관/사업방법서/요약서까지 5열이지만, 퇴직연금
            # 운용관리계약서는 판매기간 + 계약서의 3열 구조를 사용한다.
            if len(cells) < 3:
                continue
            candidate_rows += 1
            start_text = cells[0].get_text(" ", strip=True)
            start = parse_date(start_text)
            end = parse_date(cells[1].get_text(" ", strip=True))
            if start is None:
                # 사이트 원문에 상품코드나 잘못된 7자리 날짜가 들어간 실제
                # 행이 있다. 행 자체를 버리면 상세 전체가 영구 실패하므로
                # 날짜미상 버전으로 보존한다. 종료일이 범위보다 과거라면
                # 공통 select_versions가 안전하게 제외한다.
                self.log.warning(
                    "[KB] 판매개시일 해석 불가 product=%s row=%d value=%r",
                    product.get("product_code", ""),
                    row_index,
                    start_text,
                )

            version = ProductVersion(
                company_code=self.code,
                company_name=self.name,
                storage_name=self.company.storage_name,
                product_name_raw=product_name,
                product_category=category,
                source_product_id="|".join(
                    str(product[name] or "").strip()
                    for name in ("bojong_no", "gubun", "bojong_seq")
                ),
                sale_status="판매중" if end is None else "판매중지",
                sale_start_date=start,
                sale_end_date=end,
                source_page_url=self.base_url,
                version_key=(
                    f"{start:%Y%m%d}_판매개시"
                    if start is not None
                    else f"날짜미상_{row_index}"
                ),
                extra={
                    "kb_product_key": {
                        "bojong_no": product["bojong_no"],
                        "gubun": product["gubun"],
                        "bojong_seq": product["bojong_seq"],
                    }
                },
            )
            for cell in cells[2:5]:
                anchor = cell.find("a", href=True)
                if anchor is None:
                    continue
                image = anchor.find("img")
                label = (image.get("alt") if image else "") or anchor.get_text(" ", strip=True)
                label = label.replace("PDF 보기", "").strip()
                href = anchor["href"].strip()
                # 문서가 없는 칸은 'javascript:stop();' 같은 자리표시자 링크가 들어 있다.
                if not href or href.lower().startswith("javascript"):
                    continue
                url = href if href.startswith("http") else BASE + href
                filename = ""
                file_match = re.search(r"fileNm=([^&]+)", href)
                if file_match:
                    filename = file_match.group(1)
                document = self.make_document(label=label, url=url, filename=filename)
                if document is not None:
                    version.documents.append(document)
            versions.append(version)
        # KB의 정상 상세에는 적어도 한 개의 판매기간 행이 있다. 파싱 불가
        # 날짜도 날짜미상 버전으로 보존하므로 후보 행 수와 버전 수는 같아야 한다.
        # 테이블만 있고 후보 행이 없으면 WAF/마크업 변경 가능성이 있으므로
        # 성공 캐시로 남기지 않는다.
        return versions, candidate_rows > 0 and len(versions) == candidate_rows

    # ------------------------------------------------------------------
    def fetch_document(self, document: Document) -> FetchResult:
        """KB 첨부파일을 내려받는다.

        KB의 일반 첨부파일명은 ASCII라 기본 GET으로 충분하지만,
        ``KB다이렉트개인용자동차보험``의 일부 사업방법서처럼 파일명에
        한글이 포함된 링크는 서버가 UTF-8 query를 파일명으로 인식하지
        못하고 EUC-KR HTML 오류 페이지를 반환한다. 이 경우에만 동일한
        ``fileNm`` 값을 EUC-KR percent-encoding한 URL로 한 번 재시도한다.
        HTML 응답을 정상 파일로 우회 저장하지 않으며, 두 시도가 모두
        HTML이면 기본 FetchResult를 그대로 반환해 기존 검증/재시도 상태를
        유지한다.
        """
        result = super().fetch_document(document)
        if not self._needs_euckr_retry(document, result):
            return result

        for url in self._euckr_file_url_variants(document.document_url):
            if url == document.document_url:
                continue
            retry_result = super().fetch_document(replace(document, document_url=url))
            if retry_result.ok and not self._is_html_error(retry_result.content):
                self.log.info("[KB] EUC-KR fileNm 인코딩으로 재시도 성공: %s", document.original_filename)
                return retry_result
            result = retry_result
        return result

    @staticmethod
    def _is_html_error(content: bytes) -> bool:
        """KB 오류 응답의 HTML/HTML 주석 선두 변형을 판정한다."""
        head = (content or b"").lstrip().lower()
        return looks_like_html(content) or head.startswith(b"<!--")

    @staticmethod
    def _needs_euckr_retry(document: Document, result: FetchResult) -> bool:
        """재시도를 레거시 KB의 HTML 오류 응답으로 한정한다.

        파일명에 한글이 있고 PDF가 예상되는 경우라도 DRM/압축 등 정상적인
        비-PDF 응답을 임의로 다시 요청하지 않도록, 본문이 HTML 또는 HTML
        주석으로 시작할 때만 ``True``를 반환한다. KB 오류 응답 중에는
        ``<!-- Fast...``처럼 주석이 첫 바이트인 변형이 있어 공통
        ``looks_like_html``보다 좁은 보완 검사를 둔다.
        """
        if not result.ok:
            return False
        filename = filename_from_url(document.document_url)
        if not filename or not any(ord(char) > 127 for char in filename):
            return False
        extension = (
            guess_extension(url=document.original_filename)
            or guess_extension(url=document.document_url)
        )
        if extension.lower() != ".pdf":
            return False
        return KBInsuranceAdapter._is_html_error(result.content)

    @staticmethod
    def _euckr_file_url_variants(url: str) -> list[str]:
        """``fileNm`` query를 EUC-KR로 명시 인코딩한 URL을 만든다.

        원본 href가 이미 percent-encoded일 수도 있으므로 먼저 한 번
        decode한 뒤 다시 인코딩한다. fileNm 이 없는 URL은 변경하지 않는다.
        ``safe=''``로 경로 구분자를 포함한 예약문자도 모두 percent-encoding한다.
        """
        if not url:
            return []
        parsed = urlsplit(url)
        pairs = parsed.query.split("&") if parsed.query else []
        changed = False
        encoded_pairs: list[str] = []
        for pair in pairs:
            key, separator, value = pair.partition("=")
            if key.lower() != "filenm" or not separator:
                encoded_pairs.append(pair)
                continue
            try:
                encoded = quote(unquote(value), encoding="euc-kr", errors="strict", safe="")
            except (UnicodeEncodeError, ValueError):
                encoded = value
            changed = changed or encoded != value
            encoded_pairs.append(f"{key}={encoded}")
        if not changed:
            return []
        return [urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "&".join(encoded_pairs), parsed.fragment))]
