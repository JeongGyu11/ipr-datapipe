"""NH농협손해보험 Adapter.

수집 방식: XML AJAX 3단계 (docs/sites/NH_FIRE.md)
  STEP1 POST /front/announce/retrievePdtDcd.ajax  {type=ajax, pdtSelYn, pdtGrCd}
        → 상품구분(pdtDcd) 목록
  STEP2 POST /front/announce/retrievePdtCd.ajax   {+ pdtDcd}
        → 상품(pdtCd, pdtNm) 목록
  STEP3 POST /front/announce/retrievePdtInfo.ajax {+ pdtCd}
        → 판매기간(pdtSelStDt/pdtSelEdDt)과 파일ID(fileId) + 파일순번
  문서   POST /imageView/downloadFile.ajax {fileId, afileSeqn}
        afileSeqn 1=약관 / 2=상품요약서 / 3=상품안내장(제외) / 4=사업방법서 / 5=업무방법서(제외)

응답은 devon xSync 의 XML(`<태그><![CDATA[값]]></태그>`)이며 태그별로 값이 순서대로 나열됩니다.
"""

from __future__ import annotations

import re
from datetime import date

from crawler.base_adapter import BaseInsurerAdapter
from models.product_version import ProductVersion
from utils.date_utils import parse_date

BASE = "https://www.nhfire.co.kr"
PAGE_URL = f"{BASE}/announce/productAnnounce/retrieveInsuranceProductsAnnounce.nhfire"
STEP1 = f"{BASE}/front/announce/retrievePdtDcd.ajax"
STEP2 = f"{BASE}/front/announce/retrievePdtCd.ajax"
STEP3 = f"{BASE}/front/announce/retrievePdtInfo.ajax"
DOWNLOAD_URL = f"{BASE}/imageView/downloadFile.ajax"

#: 화면의 상품군 탭
PDT_GROUPS = [("01", "장기보험"), ("02", "일반보험"), ("03", "정책보험"), ("04", "농작물재해보험")]
MODES = [("Y", "판매중"), ("N", "판매중지")]

#: 응답 필드 -> (화면 표시명, afileSeqn 필드)
DOC_FIELDS = [
    ("plcndAfileNm", "약관", "plcndAfileSeqn"),
    ("smmrAfileNm", "상품요약서", "smmrAfileSeqn"),
    ("bzMtdAfileNm", "사업방법서", "bzMtdAfileSeqn"),
]


def _column(xml: str, tag: str) -> list[str]:
    """xSync XML 에서 태그 값 목록을 순서대로 뽑는다."""
    return re.findall(rf"<{tag}><!\[CDATA\[(.*?)\]\]></{tag}>", xml, re.S)


class NHFireAdapter(BaseInsurerAdapter):
    code = "NH_FIRE"
    collection_method = "XML_AJAX - retrievePdtDcd/PdtCd/PdtInfo 3단계 순회"

    def collect_product_versions(self, start_date: date, end_date: date) -> list[ProductVersion]:
        self.client.get(PAGE_URL)   # 세션 쿠키 확보
        versions: list[ProductVersion] = []
        for sel_yn, status in MODES:
            for group_code, group_name in PDT_GROUPS:
                versions.extend(self._collect(sel_yn, status, group_code, group_name))
        self.log.info("[NH_FIRE] 상품 버전 %d건 수집", len(versions))
        self.stats["api_rows"] = len(versions)
        return versions

    # ------------------------------------------------------------------
    def _post(self, url: str, data: dict) -> str:
        response = self.client.post(
            url, data=data,
            headers={"Referer": PAGE_URL, "X-Requested-With": "XMLHttpRequest"},
        )
        if response.status_code != 200:
            self.log.warning("[NH_FIRE] %s 실패 HTTP %d", url, response.status_code)
            return ""
        return response.text

    def _collect(self, sel_yn, status, group_code, group_name) -> list[ProductVersion]:
        xml = self._post(STEP1, {"type": "ajax", "pdtSelYn": sel_yn, "pdtGrCd": group_code})
        dcds = _column(xml, "pdtDcd")
        dcd_names = _column(xml, "pdtDcdNm")

        out: list[ProductVersion] = []
        for index, dcd in enumerate(dcds):
            dcd_name = dcd_names[index] if index < len(dcd_names) else ""
            xml2 = self._post(STEP2, {"type": "ajax", "pdtSelYn": sel_yn,
                                      "pdtGrCd": group_code, "pdtDcd": dcd})
            codes = _column(xml2, "pdtCd")
            names = _column(xml2, "pdtNm")
            self.log.info("[NH_FIRE] %s / %s %s -> 상품 %d건", status, group_name, dcd_name, len(codes))
            for j, code in enumerate(codes):
                product_name = names[j] if j < len(names) else code
                out.extend(self._versions(sel_yn, status, group_name, dcd_name, code, product_name))
        return out

    def _versions(self, sel_yn, status, group_name, dcd_name, code, product_name) -> list[ProductVersion]:
        xml = self._post(STEP3, {"type": "ajax", "pdtSelYn": sel_yn, "pdtCd": code})
        if not xml:
            return []
        starts = _column(xml, "pdtSelStDt")
        ends = _column(xml, "pdtSelEdDt")
        file_ids = _column(xml, "fileId")
        names = _column(xml, "pdtNm")
        columns = {tag: _column(xml, tag) for _, _, tag in DOC_FIELDS}
        columns.update({tag: _column(xml, tag) for tag, _, _ in DOC_FIELDS})

        out: list[ProductVersion] = []
        for i in range(len(starts)):
            sale_start = parse_date(starts[i])
            sale_end = parse_date(ends[i]) if i < len(ends) else None
            version = ProductVersion(
                company_code=self.code,
                company_name=self.name,
                storage_name=self.company.storage_name,
                product_name_raw=(names[i] if i < len(names) else product_name).strip(),
                product_category=" / ".join(x for x in (group_name, dcd_name) if x),
                source_product_id=code,
                sale_status="판매중지" if sale_end else status,
                sale_start_date=sale_start,
                sale_end_date=sale_end,
                source_page_url=PAGE_URL,
            )
            if sale_start:
                version.version_key = f"{sale_start:%Y%m%d}_판매개시"
            file_id = file_ids[i] if i < len(file_ids) else ""
            for name_tag, label, seqn_tag in DOC_FIELDS:
                file_names = columns.get(name_tag) or []
                seqns = columns.get(seqn_tag) or []
                if i >= len(file_names) or not file_names[i].strip() or not file_id:
                    continue
                seqn = seqns[i] if i < len(seqns) else ""
                if not seqn:
                    continue
                doc = self.make_document(
                    label=label,
                    url=f"{DOWNLOAD_URL}?fileId={file_id}&afileSeqn={seqn}",
                    filename=file_names[i].strip(),
                )
                if doc is not None:
                    version.documents.append(doc)
            out.append(version)
        return out
