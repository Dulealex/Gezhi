from __future__ import annotations

import pytest

from gezhi._literature_intake import (
    AddInputInvalidV1,
    AddLocalPdfRequestV1,
    validate_add_request_v1,
)


def _request(**changes: str | None) -> AddLocalPdfRequestV1:
    values: dict[str, str | None] = {
        "pdf_path": r"E:\input\paper.pdf",
        "work_id": None,
        "doi": None,
        "arxiv_id": None,
        "citation": None,
    }
    values.update(changes)
    return AddLocalPdfRequestV1(**values)  # type: ignore[arg-type]


def test_add_input_accepts_exact_canonical_values_without_repair() -> None:
    validated = validate_add_request_v1(
        _request(
            pdf_path=r"\\?\E:\input\paper.pdf",
            work_id="wrk_123e4567-e89b-42d3-a456-426614174000",
            doi="10.1234.56/Ab C_(x)/v2",
            arxiv_id="hep-th/9901001v2",
            citation="  A\r\nB\rC  ",
        )
    )

    assert validated.pdf_path == r"\\?\E:\input\paper.pdf"
    assert validated.work_id == "wrk_123e4567-e89b-42d3-a456-426614174000"
    assert validated.doi == "10.1234.56/Ab C_(x)/v2"
    assert validated.arxiv_id == "hep-th/9901001v2"
    assert validated.citation == "A\nB\nC"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("pdf_path", r"relative\paper.pdf"),
        ("pdf_path", r"\\server\share\paper.pdf"),
        ("pdf_path", r"E:\input\paper.pdf:stream"),
        ("work_id", "wrk_123e4567-e89b-52d3-a456-426614174000"),
        ("work_id", "wrk_123E4567-E89B-42D3-A456-426614174000"),
        ("doi", "doi:10.1234/example"),
        ("doi", " 10.1234/example"),
        ("doi", "10.1234/line\nbreak"),
        ("arxiv_id", "arXiv:2401.00001"),
        ("arxiv_id", "2400.00001"),
        ("arxiv_id", "0704.0000"),
        ("arxiv_id", "1501.0000"),
        ("arxiv_id", "hep-th/9901000"),
        ("citation", "\x00"),
        ("citation", "   "),
    ],
)
def test_add_input_rejects_invalid_field_without_repair(
    field: str,
    value: str,
) -> None:
    with pytest.raises(AddInputInvalidV1) as caught:
        validate_add_request_v1(_request(**{field: value}))

    assert caught.value.field == field


@pytest.mark.parametrize(
    "arxiv_id",
    [
        "0704.0001",
        "1412.9999v1",
        "1501.00001",
        "9912.99999v12",
        "hep-th/9107001",
        "math-ph/0703999v3",
    ],
)
def test_add_input_accepts_frozen_modern_and_legacy_arxiv_boundaries(
    arxiv_id: str,
) -> None:
    assert validate_add_request_v1(
        _request(arxiv_id=arxiv_id)
    ).arxiv_id == arxiv_id


def test_add_input_reports_first_invalid_field_in_contract_order() -> None:
    with pytest.raises(AddInputInvalidV1) as caught:
        validate_add_request_v1(
            _request(
                pdf_path="bad",
                work_id="bad",
                doi="bad",
                arxiv_id="bad",
                citation="",
            )
        )

    assert caught.value.field == "pdf_path"


def test_add_citation_applies_nfc_and_exact_limits() -> None:
    normalized = validate_add_request_v1(
        _request(citation=" e\u0301 ")
    ).citation
    assert normalized == "é"

    assert validate_add_request_v1(
        _request(citation="a" * 4096)
    ).citation == "a" * 4096

    with pytest.raises(AddInputInvalidV1) as caught:
        validate_add_request_v1(_request(citation="a" * 4097))
    assert caught.value.field == "citation"


@pytest.mark.parametrize("citation", ["\ud800", "a\x01b"])
def test_add_citation_rejects_unpaired_surrogates_and_controls(
    citation: str,
) -> None:
    with pytest.raises(AddInputInvalidV1) as caught:
        validate_add_request_v1(_request(citation=citation))

    assert caught.value.field == "citation"
