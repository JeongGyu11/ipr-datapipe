"""파일명 특수문자 제거 / 축약 테스트."""

import pytest

from utils.file_utils import (
    INVALID_CHARS,
    filename_from_content_disposition,
    filename_from_url,
    guess_extension,
    normalize_extension,
    normalize_storage_component,
    shorten,
    split_extension,
)


# 3. 파일명 특수문자 제거 ------------------------------------------------------
def test_sanitize_removes_all_windows_invalid_chars():
    name = "무배당 " + INVALID_CHARS + "보험"
    result = normalize_storage_component(name)
    for ch in INVALID_CHARS:
        assert ch not in result
    assert "보험" in result


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("A/B", "A_B"),
        ("A:B", "A_B"),
        ('say "hi"', "say__hi_"),
        ("a<b>c", "a_b_c"),
        ("q?mark*star|pipe", "q_mark_star_pipe"),
        ("back\\slash", "back_slash"),
    ],
)
def test_sanitize_specific_chars(raw, expected):
    assert normalize_storage_component(raw) == expected


def test_sanitize_strips_trailing_dot_and_space():
    assert normalize_storage_component("상품명. ") == "상품명"
    assert normalize_storage_component("  여백  ") == "여백"


def test_sanitize_replaces_internal_whitespace_with_underscore():
    assert normalize_storage_component("무배당   프로미라이프\t간편건강보험") == "무배당_프로미라이프_간편건강보험"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("A _123123.pdf", "A_123123.pdf"),
        ("A_ 123123.pdf", "A_123123.pdf"),
        ("_ A.pdf", "_A.pdf"),
        ("A B.pdf", "A_B.pdf"),
        ("A\t\nB.pdf", "A_B.pdf"),
        ("A\u00a0B.pdf", "A_B.pdf"),
        ("A\u3000B.pdf", "A_B.pdf"),
        ("A\u200b B.pdf", "A_B.pdf"),
        ("  A B.pdf  ", "A_B.pdf"),
        # 기존 underscore는 전역적으로 접지 않는다.
        ("A__B.pdf", "A__B.pdf"),
    ],
)
def test_storage_whitespace_rule(raw, expected):
    assert normalize_storage_component(raw) == expected


def test_sanitize_handles_reserved_names():
    assert normalize_storage_component("CON") == "CON_"
    assert normalize_storage_component("nul") == "nul_"


def test_sanitize_never_returns_empty():
    assert normalize_storage_component("") == "_"
    assert normalize_storage_component("///") == "___"
    assert normalize_storage_component(None) == "_"


def test_shorten_keeps_distinguishable_suffix():
    a = shorten("가" * 300 + "A", 40)
    b = shorten("가" * 300 + "B", 40)
    assert len(a) <= 40 and len(b) <= 40
    assert a != b   # 해시 접미사로 서로 구분된다


def test_split_extension():
    assert split_extension("약관_31073.pdf") == ("약관_31073", ".pdf")
    assert split_extension("FILE.PDF") == ("FILE", ".pdf")
    assert split_extension("noext") == ("noext", "")
    assert split_extension("archive.tar.gz") == ("archive.tar", ".gz")


@pytest.mark.parametrize(
    "raw,expected",
    [(" PDF ", ".pdf"), ("PDF", ".pdf"), (".hwpx", ".hwpx"), ("../pdf", "")],
)
def test_normalize_extension(raw, expected):
    assert normalize_extension(raw) == expected


def test_split_extension_trims_and_validates_extension():
    assert split_extension("A.PDF ") == ("A", ".pdf")
    assert split_extension("A.bad/extension") == ("A.bad/extension", "")


def test_filename_from_content_disposition():
    header = "inline;filename=%EC%95%BD%EA%B4%80_31073%2808%29_20260701.pdf;"
    assert filename_from_content_disposition(header) == "약관_31073(08)_20260701.pdf"
    assert filename_from_content_disposition('attachment; filename="a b.pdf"') == "a b.pdf"
    assert filename_from_content_disposition("attachment; filename*=UTF-8''%ED%95%9C.pdf") == "한.pdf"
    assert filename_from_content_disposition("") == ""


def test_filename_from_url_query_parameter():
    url = "https://www.kbinsure.co.kr/CG802030003.ec?fileNm=20260101_10101_1.pdf"
    assert filename_from_url(url) == "20260101_10101_1.pdf"
    assert filename_from_url("https://x/y/z/파일.pdf") == "파일.pdf"


def test_guess_extension_prefers_real_filename_over_servlet_path():
    """경로 확장자(.do/.ec)가 아니라 쿼리스트링의 실제 파일 확장자를 써야 한다."""
    db = "https://www.idbins.com/cYakgwanDown.do?FilePath=InsProduct/%EC%95%BD%EA%B4%80_31073.pdf"
    assert guess_extension(url=db) == ".pdf"
    kb = "https://www.kbinsure.co.kr/CG802030003.ec?fileNm=20260101_10101_1.pdf"
    assert guess_extension(url=kb) == ".pdf"


def test_guess_extension():
    assert guess_extension(url="https://x/a.PDF") == ".pdf"
    assert guess_extension(content_disposition='attachment; filename="b.hwp"') == ".hwp"
    assert guess_extension(content_type="application/pdf") == ".pdf"
    assert guess_extension(content_type="application/zip") == ".zip"
    assert guess_extension() == ""
