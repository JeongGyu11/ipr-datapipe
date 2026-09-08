"""문서유형 매핑 테스트."""

import pytest

from models.document import DocumentType


@pytest.mark.parametrize(
    "label,expected",
    [
        ("약관", DocumentType.POLICY),
        ("보통약관", DocumentType.POLICY),
        ("특별약관", DocumentType.POLICY),
        ("보험약관", DocumentType.POLICY),
        ("상품약관", DocumentType.POLICY),
        ("상품요약서", DocumentType.SUMMARY),
        ("상품요약", DocumentType.SUMMARY),
        ("요약서", DocumentType.SUMMARY),
        ("사업방법서", DocumentType.METHOD),
        ("사업방법", DocumentType.METHOD),
    ],
)
def test_classify_known_labels(classifier, label, expected):
    assert classifier.classify(label) == expected


def test_summary_wins_over_policy(classifier):
    """'상품요약서' 안에 '약관'이 없지만, 긴 키워드 우선 규칙을 확인한다."""
    assert classifier.classify("상품요약서(약관 포함)") == DocumentType.SUMMARY


def test_classify_uses_filename_when_label_is_empty(classifier):
    assert classifier.classify("", "약관_31073(08)_20260701.pdf") == DocumentType.POLICY
    assert classifier.classify("", "요약_31073(08)_20260701.pdf") == DocumentType.SUMMARY


def test_unknown_label_is_not_dropped(classifier):
    """판별 불가 문서는 제외하지 않고 UNKNOWN_DOCUMENT_TYPE 으로 남긴다."""
    assert classifier.classify("기타첨부자료") == DocumentType.UNKNOWN


@pytest.mark.parametrize(
    "label",
    [
        "보험료 예시",
        "보험료예시",
        "가입설계서",
        "핵심설명서",
        "비교안내서",
        "확인서",
        "안내장",
        "브로슈어",
        "상품설명서",
        "청약서",
    ],
)
def test_excluded_documents(classifier, label):
    assert classifier.is_excluded(label) is True


@pytest.mark.parametrize("label", ["약관", "상품요약서", "사업방법서"])
def test_target_documents_are_not_excluded(classifier, label):
    assert classifier.is_excluded(label) is False


def test_folder_names():
    assert DocumentType.FOLDER_NAME[DocumentType.POLICY] == "약관"
    assert DocumentType.FOLDER_NAME[DocumentType.SUMMARY] == "상품요약서"
    assert DocumentType.FOLDER_NAME[DocumentType.METHOD] == "사업방법서"
