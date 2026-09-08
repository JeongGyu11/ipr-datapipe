"""DB생명 Adapter.

수집 방식: STATIC_HTML + AJAX XML (docs/sites/DB_LIFE.md)
  - 목록: GET /notice/product/sale        (판매상품)
          GET /notice/product/sold_out    (판매중지상품)
          파라미터 gubn1(1=개인 / 2=단체 / 4=방카), gubn2, gubn3, page
          페이지당 10행, 총 페이지 수는 ``data-total-page`` 로 제공
  - 판매중지 상세: POST /notice/product/sold_out/ajaxRequest {mcode,gubn1}
  - 문서: 사업방법서/상품요약서 → GET /notice/product/file/{publishNo}/{n}
          약관 → GET /notice/product/prov/{sale|soldOut}/{provNo} 팝업 HTML 안의
                 /notice/product/prov/file?publishNo=&fileGb=&fileSeq= 링크 전부

주의: 이 사이트는 구형 TLS 스택이라 기본 SSL 컨텍스트로는 연결이 실패합니다
      (WRONG_SIGNATURE_TYPE). legacy_ssl=True 를 사용합니다.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any
from xml.etree import ElementTree

from crawler.adapters.common import absolute, clean, parse_period, soup, table_rows
from crawler.base_adapter import BaseInsurerAdapter
from crawler.detail_checkpoint_service import DetailCheckpointService
from crawler.http_client import AccessDeniedError
from models.document import Document
from models.product_version import ProductVersion
from utils.date_utils import parse_date

BASE = "https://www.idblife.com"
LIST_PATH = {"sale": f"{BASE}/notice/product/sale", "sold_out": f"{BASE}/notice/product/sold_out"}
SOLD_OUT_DETAIL_URL = f"{BASE}/notice/product/sold_out/ajaxRequest"

#: gubn1 -> 판매채널 구분 (화면 탭)
CHANNELS = [("1", "개인상품"), ("2", "단체상품"), ("4", "방카상품")]
MAX_PAGES = 300


class DBLifeAdapter(BaseInsurerAdapter):
    code = "DB_LIFE"
    legacy_ssl = True
    collection_method = "STATIC_HTML + AJAX_XML - 판매/판매중지 × 채널별 페이지네이션·상세 순회"
    detail_checkpoint_filename = "detail_checkpoint.v2.jsonl"

    def collect_product_versions(self, start_date: date, end_date: date) -> list[ProductVersion]:
        # 동일 인스턴스를 재사용해도 이전 범위의 실패/진행 통계가 새 실행의
        # 성공 여부를 오염시키지 않게 수집 단위 통계를 초기화한다.
        self.stats.update(
            html_rows=0,
            attempted=0,
            reused=0,
            failed=0,
            detail_checkpoint_attempted=0,
            detail_checkpoint_reused=0,
            detail_checkpoint_failed=0,
            sold_out_versions=0,
            status_coverage_complete=False,
        )
        self._status_traversal_capped = False
        self._sold_out_seen = set()
        versions: list[ProductVersion] = []
        for mode, status in (("sale", "판매중"), ("sold_out", "판매중지")):
            for gubn1, channel in CHANNELS:
                try:
                    versions.extend(self._collect(mode, status, gubn1, channel))
                except AccessDeniedError:
                    # 접근 통제는 상품 단위 실패로 삼키지 않고 회사 실행을
                    # 즉시 중단하여 운영자가 원인을 확인하게 한다.
                    raise
        self.log.info("[DB_LIFE] 상품 버전 %d건 수집", len(versions))
        self.stats["html_rows"] = len(versions)
        if int(self.stats.get("failed", 0)):
            self.stats["status_coverage_complete"] = False
            raise RuntimeError(
                f"DB생명 판매중지 상품 상세 {self.stats.get('failed', 0)}건을 수집하지 못했습니다. "
                "완료된 상품은 체크포인트에 보존되므로 같은 기간으로 재실행해 주세요."
            )
        self.stats["status_coverage_complete"] = not self._status_traversal_capped
        return versions

    # ------------------------------------------------------------------
    def _collect(self, mode: str, status: str, gubn1: str, channel: str) -> list[ProductVersion]:
        out: list[ProductVersion] = []
        if mode == "sold_out":
            # 같은 mcode가 페이지/반응형 마크업에 반복되어도 상세 POST는 1회만 한다.
            if not hasattr(self, "_sold_out_seen"):
                self._sold_out_seen = set()
        page = 1
        total_pages = 1
        while page <= min(total_pages, MAX_PAGES):
            response = self.client.get(
                LIST_PATH[mode], params={"gubn1": gubn1, "gubn2": "", "gubn3": "", "page": str(page)}
            )
            if response.status_code == 403:
                raise AccessDeniedError(f"DB생명 {mode}/{channel} page={page} HTTP 403")
            if response.status_code != 200:
                raise RuntimeError(f"DB생명 {mode}/{channel} page={page} HTTP {response.status_code}")
            document = soup(response.text)
            if mode == "sold_out":
                # DB생명은 판매중지 상세 AJAX 요청에 페이지별 CSRF 토큰을 요구한다.
                # meta의 헤더명을 그대로 사용해 서버 측 이름 변경에도 대응한다.
                csrf_header_meta = document.select_one("meta[name='_csrf_header']")
                csrf_token_meta = document.select_one("meta[name='_csrf']")
                csrf_header = clean(csrf_header_meta.get("content")) if csrf_header_meta else ""
                csrf_token = clean(csrf_token_meta.get("content")) if csrf_token_meta else ""
                self._sold_out_csrf_headers = (
                    {csrf_header: csrf_token} if csrf_header and csrf_token else {}
                )
            pagination = document.select_one("[data-total-page]")
            if pagination is not None and page == 1:
                total_pages = int(pagination.get("data-total-page") or 1)
                if total_pages > MAX_PAGES:
                    # Keep the historical safety cap, but make the resulting
                    # status traversal explicitly partial for reconciliation.
                    self.stats["status_coverage_complete"] = False
                    self._status_traversal_capped = True
            if mode == "sold_out":
                page_versions = self._collect_sold_out_page(document, gubn1, channel, self._sold_out_seen)
                # 판매중지 목록은 상품 행이 아니라 mcode 참조만 제공한다.
                # 빈 poplist 응답도 정상일 수 있으므로 HTML 페이지가 유효하면
                # 페이지네이션을 계속한다.
                out.extend(page_versions)
                if not document.select("a.mctg[name='mcode'][data-value]"):
                    break
            else:
                table = document.select_one("table")
                rows = table_rows(table) if table is not None else []
                if not rows:
                    break
                for row in rows:
                    version = self._to_version(row, mode, status, channel)
                    if version is not None:
                        out.append(version)
            page += 1
        self.log.info("[DB_LIFE] %s/%s -> %d건 (%d페이지)", mode, channel, len(out), total_pages)
        return out

    # ------------------------------------------------------------------
    def configure_detail_checkpoint(self, root: str, scope: str = "default") -> DetailCheckpointService:
        """판매중지 상품 상세 결과를 기간 scope별로 재사용하도록 설정한다."""
        self.runtime_options = {
            **self.runtime_options,
            "detail_checkpoint_path": root,
            "detail_checkpoint_scope": scope,
        }
        self._detail_checkpoint = DetailCheckpointService(
            root,
            scope=scope,
            filename=self.detail_checkpoint_filename,
            key_fn=self._detail_key,
            adapter_version="DB_LIFE.sold_out.v1",
        )
        self.stats["detail_checkpoint_scope"] = str(scope)
        return self._detail_checkpoint

    def _checkpoint_service(self) -> DetailCheckpointService | None:
        options = self.runtime_options
        root = options.get("detail_checkpoint_path")
        if not root:
            return None
        if not hasattr(self, "_detail_checkpoint"):
            self._detail_checkpoint = DetailCheckpointService(
                root,
                scope=str(options.get("detail_checkpoint_scope") or "default"),
                filename=self.detail_checkpoint_filename,
                key_fn=self._detail_key,
                adapter_version="DB_LIFE.sold_out.v1",
            )
            self.stats["detail_checkpoint_scope"] = str(
                options.get("detail_checkpoint_scope") or "default"
            )
        return self._detail_checkpoint

    @staticmethod
    def _detail_key(product: dict[str, Any]) -> str:
        return f"{str(product.get('gubn1') or '').strip()}|{str(product.get('mcode') or '').strip()}"

    def _collect_sold_out_page(
        self, document, gubn1: str, channel: str, seen: set[str] | None = None
    ) -> list[ProductVersion]:
        refs = self._parse_sold_out_refs(document, gubn1, channel)
        checkpoint = self._checkpoint_service()
        versions: list[ProductVersion] = []
        attempted = reused = failed = 0
        # A page can repeat the same mcode in responsive/desktop markup. The
        # checkpoint key intentionally collapses those duplicates as well.
        seen = seen if seen is not None else set()
        for product in refs:
            key = self._detail_key(product)
            if key in seen:
                continue
            seen.add(key)
            cached = checkpoint.reusable(product) if checkpoint else None
            # A completed sold-out checkpoint may predate the current ACTIVE
            # manifest refresh.  If it identifies an active row, force one
            # fresh detail request so a move to sold_out cannot be inferred
            # from stale cached state.  Non-active cached products remain
            # reusable as before.
            if cached is not None and self._cached_matches_active(cached.versions):
                cached = None
            if cached is not None:
                versions.extend(cached.versions)
                reused += 1
                continue
            attempted += 1
            try:
                detail_versions = self._fetch_sold_out_detail(product, channel)
            except AccessDeniedError as exc:
                if checkpoint:
                    checkpoint.record_failure(product, f"{type(exc).__name__}: {exc}")
                raise
            except Exception as exc:  # noqa: BLE001 - 상품 단위 재개를 위해 기록
                failed += 1
                if checkpoint:
                    checkpoint.record_failure(product, f"{type(exc).__name__}: {exc}")
                self.log.exception("[DB_LIFE] 판매중지 상세 실패 mcode=%s", product.get("mcode"))
                continue
            if checkpoint:
                checkpoint.record_success(product, detail_versions)
            versions.extend(detail_versions)

        totals = {
            "attempted": attempted,
            "reused": reused,
            "failed": failed,
        }
        for key, amount in totals.items():
            self.stats[key] = int(self.stats.get(key, 0)) + amount
        # Manager/공통 로그가 사용하는 명시적 이름도 함께 제공한다.
        self.stats["detail_checkpoint_attempted"] = int(self.stats.get("detail_checkpoint_attempted", 0)) + attempted
        self.stats["detail_checkpoint_reused"] = int(self.stats.get("detail_checkpoint_reused", 0)) + reused
        self.stats["detail_checkpoint_failed"] = int(self.stats.get("detail_checkpoint_failed", 0)) + failed
        self.stats["sold_out_versions"] = int(self.stats.get("sold_out_versions", 0)) + len(versions)
        return versions

    def _cached_matches_active(self, versions: list[ProductVersion]) -> bool:
        rows = self.active_status_rows
        if not rows:
            return False
        for version in versions:
            if self.matches_active_status_reference(
                source_product_id=version.source_product_id,
                product_name=version.product_name_raw,
                sale_start_date=version.sale_start_date,
                target_date=version.target_date,
            ):
                return True
        return False

    def _parse_sold_out_refs(self, document, gubn1: str, channel: str) -> list[dict[str, str]]:
        refs: list[dict[str, str]] = []
        for anchor in document.select("a.mctg[name='mcode'][data-value]"):
            mcode = clean(anchor.get("data-value"))
            if not mcode:
                continue
            # 분류/목록명은 화면 표시를 보존하되, 실제 식별자는 mcode다.
            name = clean(anchor)
            parent = anchor.find_parent(["tr", "li", "div"])
            row_text = clean(parent) if parent is not None else name
            category = clean(anchor.get("data-category") or anchor.get("data-category-name"))
            if not category and parent is not None:
                heading = parent.find(["h2", "h3", "h4", "dt"])
                category = clean(heading) if heading is not None else ""
            category = category or name or channel
            refs.append({
                "mcode": mcode,
                "category": category,
                "list_name": name or row_text,
                "gubn1": str(gubn1),
            })
        return refs

    def _fetch_sold_out_detail(self, product: dict[str, str], channel: str) -> list[ProductVersion]:
        request_headers = {
            "Referer": LIST_PATH["sold_out"],
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/xml,text/xml,*/*;q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            **getattr(self, "_sold_out_csrf_headers", {}),
        }
        response = self.client.post(
            SOLD_OUT_DETAIL_URL,
            data={"mcode": product["mcode"], "gubn1": product["gubn1"]},
            headers=request_headers,
        )
        if response.status_code == 403:
            raise AccessDeniedError(f"판매중지 상세 mcode={product.get('mcode')} HTTP 403")
        if response.status_code != 200:
            raise RuntimeError(f"판매중지 상세 HTTP {response.status_code}")
        try:
            payload = getattr(response, "content", b"") or getattr(response, "text", "")
            if isinstance(payload, str):
                payload = payload.encode("utf-8")
            root = ElementTree.fromstring(payload)
        except (ElementTree.ParseError, UnicodeError, AttributeError) as exc:
            raise ValueError("판매중지 상세 XML 해석 실패") from exc
        if str(root.tag).rsplit("}", 1)[-1].lower() in {"html", "body"}:
            raise ValueError("판매중지 상세가 XML이 아닌 HTML입니다")
        rows = [node for node in root.iter() if str(node.tag).rsplit("}", 1)[-1].lower() == "poplist"]
        out: list[ProductVersion] = []
        for row in rows:
            fields = {
                str(child.tag).rsplit("}", 1)[-1].upper(): clean(child.text)
                for child in list(row)
            }
            fields.update({str(key).upper(): clean(value) for key, value in row.attrib.items()})
            publish_no = fields.get("PUBLISH_NO", "").strip()
            name = fields.get("PRODUCT_NAME", "").strip()
            if not publish_no or not name:
                raise ValueError("판매중지 상세 필수 식별자(PRODUCT_NAME/PUBLISH_NO) 누락")
            sale_start = parse_date(fields.get("SALE_START_DATE"))
            sale_end = parse_date(fields.get("SALE_END_DATE"))
            version = ProductVersion(
                company_code=self.code,
                company_name=self.name,
                storage_name=self.company.storage_name,
                product_name_raw=name,
                product_category=" / ".join(x for x in (channel, fields.get("MAIN_CTG", "")) if x),
                source_product_id=publish_no,
                version_key=f"{sale_start:%Y%m%d}_판매개시" if sale_start else "판매중지",
                sale_status="판매중지",
                sale_start_date=sale_start,
                sale_end_date=sale_end,
                source_page_url=LIST_PATH["sold_out"],
                extra={"mode": "sold_out", "mcode": product["mcode"], "gubn1": product["gubn1"]},
            )
            if fields.get("FILE1_NAME"):
                doc = self.make_document(
                    label="사업방법서",
                    url=f"{BASE}/notice/product/file/{publish_no}/1",
                    filename=fields["FILE1_NAME"],
                )
                if doc is not None:
                    version.documents.append(doc)
            if fields.get("FILE3_NAME"):
                version.extra["provUrl"] = f"{BASE}/notice/product/prov/soldOut/{publish_no}"
            out.append(version)
        return out

    def _to_version(self, row, mode: str, status: str, channel: str) -> ProductVersion | None:
        headers = [clean(th) for th in row.find_all("th")]
        cells = row.find_all("td")
        if len(headers) < 3 or len(cells) < 3:
            return None
        category = " / ".join(x for x in (channel, headers[0], headers[1]) if x)
        name = headers[2]
        sale_start, sale_end = parse_period(clean(cells[0]))

        version = ProductVersion(
            company_code=self.code,
            company_name=self.name,
            storage_name=self.company.storage_name,
            product_name_raw=name,
            product_category=category,
            sale_status="판매중지" if sale_end else status,
            sale_start_date=sale_start,
            sale_end_date=sale_end,
            source_page_url=LIST_PATH[mode],
            extra={"mode": mode},
        )
        if sale_start:
            version.version_key = f"{sale_start:%Y%m%d}_판매개시"

        for index, label in ((1, "사업방법서"), (2, "상품요약서")):
            if index >= len(cells):
                continue
            link = cells[index].find("a", href=True)
            if link is None:
                continue
            url = absolute(LIST_PATH[mode], link["href"])
            m = re.search(r"/file/(\d+)/", url)
            if m:
                version.source_product_id = version.source_product_id or m.group(1)
            doc = self.make_document(label=label, url=url, filename="")
            if doc is not None:
                version.documents.append(doc)

        # 약관은 팝업 HTML 안에 여러 파일이 들어 있으므로 URL 만 보관하고 뒤에서 펼친다.
        if len(cells) > 3:
            link = cells[3].find("a", href=True)
            if link is not None:
                version.extra["provUrl"] = absolute(LIST_PATH[mode], link["href"])
        return version

    # ------------------------------------------------------------------
    def collect_documents(self, product_version: ProductVersion) -> list[Document]:
        """약관 팝업을 열어 주계약/제도성 특약/취합본 약관을 모두 수집한다."""
        documents = list(product_version.documents)
        prov_url = product_version.extra.get("provUrl")
        if not prov_url:
            return documents
        try:
            response = self.client.get(prov_url)
        except Exception as exc:  # noqa: BLE001
            self.log.warning("[DB_LIFE] 약관 팝업 실패(%s): %s", product_version.product_name_raw, exc)
            return documents
        if response.status_code != 200:
            return documents

        document = soup(response.text)
        section = ""
        for node in document.select("h2, ul.lists12 li a[href]"):
            if node.name == "h2":
                section = clean(node)
                continue
            href = absolute(BASE, node["href"].replace(" ", ""))
            if not href:
                continue
            title = clean(node)
            doc = self.make_document(
                label=f"약관 - {section}" if section else "약관",
                url=href,
                filename=title,
            )
            if doc is not None:
                documents.append(doc)
        product_version.documents = documents
        return documents
