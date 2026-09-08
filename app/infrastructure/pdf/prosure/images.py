"""PDF 내장 이미지와 렌더링 영역을 파일 산출물로 저장한다."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from app.domain.pdf_load import ParsedImage

MIN_IMAGE_PIXEL_DIMENSION = 64
MIN_IMAGE_DISPLAY_AREA_RATIO = 0.005
RENDER_SCALE = 2.0
TABLE_RENDER_PADDING_POINTS = 2.0


def _bbox_list(value: Any) -> list[float]:
    return [float(item) for item in value]


def _bbox_sort_key(bbox: Any) -> tuple[float, float, float, float]:
    """Return the reading-order key for a PyMuPDF ``(left, top, right, bottom)`` bbox.

    PDF APIs expose coordinates as left/top/right/bottom, while reading order is
    conventionally top/left/bottom/right.  Keeping this conversion in one helper
    avoids accidentally relying on the order in which image objects occur in the
    PDF content stream.
    """

    left, top, right, bottom = _bbox_list(bbox)
    return top, left, bottom, right


def _render_region_bytes(page: Any, bbox: list[float]) -> bytes:
    import pymupdf

    clip = pymupdf.Rect(*bbox) & page.rect
    if clip.is_empty or clip.width <= 0 or clip.height <= 0:
        raise ValueError("렌더링할 이미지 영역이 비어 있습니다.")
    pixmap = page.get_pixmap(
        matrix=pymupdf.Matrix(RENDER_SCALE, RENDER_SCALE),
        clip=clip,
        alpha=False,
    )
    payload = pixmap.tobytes("png")
    return payload


def _extract_payload(document: Any, page: Any, info: dict[str, Any]) -> tuple[bytes, str, str]:
    xref = int(info.get("xref") or 0)
    if xref > 0:
        extracted = document.extract_image(xref)
        payload = bytes(extracted.get("image") or b"")
        extension = str(extracted.get("ext") or "").lower()
        if payload and extension in {"png", "jpg", "jpeg"}:
            return payload, "jpg" if extension == "jpeg" else extension, "EMBEDDED"

        import pymupdf

        pixmap = pymupdf.Pixmap(document, xref)
        if pixmap.colorspace is None:
            raise ValueError(f"지원하지 않는 이미지 색공간: xref={xref}")
        if pixmap.n > 4:
            pixmap = pymupdf.Pixmap(pymupdf.csRGB, pixmap)
        return pixmap.tobytes("png"), "png", "EMBEDDED"

    bbox = _bbox_list(info["bbox"])
    return _render_region_bytes(page, bbox), "png", "RENDERED_REGION"


def extract_embedded_images(
    source_pdf: Path,
    output_dir: Path,
) -> tuple[list[ParsedImage], dict[int, list[dict[str, Any]]], list[dict[str, Any]]]:
    """의미 있는 내장 이미지를 추출하고 문서 내 동일 이미지는 한 번만 저장한다."""

    try:
        import pymupdf
    except ImportError:
        return [], {}, [{"code": "IMAGE_EXTRACTION_UNAVAILABLE", "message": "PyMuPDF가 필요합니다."}]

    images_dir = output_dir / "02_images"
    images_dir.mkdir(parents=True, exist_ok=True)
    parsed_images: list[ParsedImage] = []
    page_occurrences: dict[int, list[dict[str, Any]]] = {}
    warnings: list[dict[str, Any]] = []
    by_sha256: dict[str, ParsedImage] = {}

    with pymupdf.open(source_pdf) as document:
        for page_no, page in enumerate(document, start=1):
            page_area = float(page.rect.width * page.rect.height)
            accepted_index = 0
            try:
                candidates = page.get_image_info(hashes=True, xrefs=True)
            except Exception as exc:
                warnings.append(
                    {"code": "IMAGE_DETECTION_FAILED", "page_no": page_no, "message": str(exc)}
                )
                continue

            for info in candidates:
                bbox = _bbox_list(info.get("bbox") or (0, 0, 0, 0))
                display_width = max(0.0, bbox[2] - bbox[0])
                display_height = max(0.0, bbox[3] - bbox[1])
                area_ratio = (
                    min(1.0, display_width * display_height / page_area) if page_area > 0 else 0.0
                )
                pixel_width = int(info.get("width") or 0)
                pixel_height = int(info.get("height") or 0)
                if (
                    min(pixel_width, pixel_height) < MIN_IMAGE_PIXEL_DIMENSION
                    or area_ratio < MIN_IMAGE_DISPLAY_AREA_RATIO
                ):
                    continue

                accepted_index += 1
                try:
                    payload, extension, extraction_mode = _extract_payload(document, page, info)
                    digest = hashlib.sha256(payload).hexdigest()
                    occurrence = {
                        "page_no": page_no,
                        "bbox": bbox,
                        "displayed_area_ratio": area_ratio,
                    }
                    existing = by_sha256.get(digest)
                    if existing is not None:
                        existing.occurrences.append(occurrence)
                        page_occurrences.setdefault(page_no, []).append(
                            {
                                "image_id": existing.image_id,
                                "bbox": bbox,
                                "image_path": existing.image_path,
                            }
                        )
                        continue

                    image_id = f"page_{page_no:04d}_image_{accepted_index:03d}"
                    image_path = images_dir / f"{image_id}.{extension}"
                    image_path.write_bytes(payload)
                    parsed = ParsedImage(
                        image_id=image_id,
                        first_page_no=page_no,
                        pixel_width=pixel_width,
                        pixel_height=pixel_height,
                        format=extension.upper(),
                        image_path=image_path.relative_to(output_dir).as_posix(),
                        sha256=digest,
                        extraction_mode=extraction_mode,
                        occurrences=[occurrence],
                    )
                    parsed_images.append(parsed)
                    by_sha256[digest] = parsed
                    page_occurrences.setdefault(page_no, []).append(
                        {"image_id": image_id, "bbox": bbox, "image_path": parsed.image_path}
                    )
                except Exception as exc:
                    warnings.append(
                        {
                            "code": "IMAGE_EXTRACTION_FAILED",
                            "page_no": page_no,
                            "image_index": accepted_index,
                            "message": str(exc),
                        }
                    )

    # ``get_image_info`` follows the PDF content stream, which is not guaranteed
    # to match the visual reading order.  Normalize both occurrence views before
    # handing them to callers (and therefore to page markdown generation).
    for occurrences in page_occurrences.values():
        occurrences.sort(key=lambda item: _bbox_sort_key(item["bbox"]))
    for parsed in parsed_images:
        parsed.occurrences.sort(
            key=lambda item: (
                int(item["page_no"]),
                *_bbox_sort_key(item["bbox"]),
            )
        )

    return parsed_images, page_occurrences, warnings


class TableRegionRenderer:
    """Reusable PNG renderer backed by one open PyMuPDF document.

    The renderer deliberately lets errors from an individual ``render`` call
    propagate.  Callers rendering a collection of tables can then isolate a
    failed table while continuing with the remaining regions.
    """

    def __init__(self, source_pdf: Path) -> None:
        self.source_pdf = Path(source_pdf)
        self._document: Any | None = None

    def __enter__(self) -> "TableRegionRenderer":
        import pymupdf

        if self._document is not None:
            raise RuntimeError("표 렌더러 문서가 이미 열려 있습니다.")
        self._document = pymupdf.open(self.source_pdf)
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> bool:
        self.close()
        # Never swallow a table-specific rendering failure.
        return False

    def close(self) -> None:
        """Close the shared document (idempotent, for explicit lifecycle control)."""

        document, self._document = self._document, None
        if document is not None:
            document.close()

    def render(
        self,
        page_no: int,
        bbox: list[float],
        output_path: Path,
    ) -> Path:
        """Render one table region to ``output_path``.

        ``RuntimeError`` is raised when used outside a context manager.  All
        document/page/pixmap errors are intentionally uncaught for per-table
        failure isolation by the caller.
        """

        if self._document is None:
            raise RuntimeError("TableRegionRenderer는 with 문 안에서 사용해야 합니다.")
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        page = self._document[page_no - 1]
        padded_bbox = [
            bbox[0] - TABLE_RENDER_PADDING_POINTS,
            bbox[1] - TABLE_RENDER_PADDING_POINTS,
            bbox[2] + TABLE_RENDER_PADDING_POINTS,
            bbox[3] + TABLE_RENDER_PADDING_POINTS,
        ]
        output_path.write_bytes(_render_region_bytes(page, padded_bbox))
        return output_path

    # Descriptive alias for callers that prefer the legacy function's name.
    render_table_region = render


def render_table_region(
    source_pdf: Path,
    *,
    page_no: int,
    bbox: list[float],
    output_path: Path,
) -> Path:
    """Compatibility wrapper that renders one region with a temporary renderer."""

    with TableRegionRenderer(source_pdf) as renderer:
        return renderer.render(page_no, bbox, output_path)


__all__ = [
    "MIN_IMAGE_DISPLAY_AREA_RATIO",
    "MIN_IMAGE_PIXEL_DIMENSION",
    "RENDER_SCALE",
    "TABLE_RENDER_PADDING_POINTS",
    "TableRegionRenderer",
    "extract_embedded_images",
    "render_table_region",
]
