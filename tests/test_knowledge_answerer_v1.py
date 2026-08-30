from __future__ import annotations

import json

import pytest

from gezhi import _knowledge_answerer as answerer


@pytest.mark.parametrize(
    ("value", "question_block", "expected"),
    [
        ("# 标题", False, r"\# 标题"),
        ("&quest;", False, r"\&quest\;"),
        ("[x](y)", False, r"\[x\]\(y\)"),
        ("    # x", False, "&#32;&#32;&#32;&#32;\\# x"),
        ("甲\n乙", False, "甲&#10;乙"),
        ("甲\n乙", True, "甲\\\n乙"),
    ],
)
def test_plain_text_to_commonmark_vectors_are_exact(
    value: str,
    question_block: bool,
    expected: str,
) -> None:
    assert answerer._plain_text_v1(value, question_block=question_block) == expected


def test_citation_targets_use_fixed_bases_and_single_entity_decoding() -> None:
    assert answerer._doi_link_v1("10.1000/x&quest;y/z?") == (
        r"[DOI：10\.1000\/x\&quest\;y\/z\?]"
        "(<https://doi.org/10.1000/x&amp;quest;y%2Fz%3F>)"
    )
    assert answerer._arxiv_link_v1("hep-th/9901001v2") == (
        r"[arXiv：hep\-th\/9901001v2]"
        "(<https://arxiv.org/abs/hep-th/9901001v2>)"
    )


def test_answer_output_schema_is_closed_and_versioned() -> None:
    schema_bytes = answerer.answer_output_schema_bytes_v1()
    schema = json.loads(schema_bytes)

    assert schema_bytes.endswith(b"\n")
    assert schema["$id"] == ("https://gezhi.local/schemas/answer-output-v1.schema.json")
    assert schema["additionalProperties"] is False
    assert schema["required"] == [
        "schema_version",
        "answer_status",
        "answer_units",
        "qualification_units",
        "insufficiency_reason",
    ]
    assert set(schema["properties"]) == set(schema["required"])
