from __future__ import annotations

import pytest

from gezhi._raw_argv import RawArgvPreflightV1, RawArgvPreflightVerdictV1


@pytest.mark.parametrize(
    ("argument_count", "expected"),
    [
        (127, RawArgvPreflightVerdictV1.PASS),
        (128, RawArgvPreflightVerdictV1.PASS),
        (129, RawArgvPreflightVerdictV1.RESOURCE_LIMIT_EXCEEDED),
    ],
)
def test_argument_count_limit_is_inclusive_and_counts_empty_tokens(
    argument_count: int,
    expected: RawArgvPreflightVerdictV1,
) -> None:
    suffix = ("",) * argument_count

    assert RawArgvPreflightV1.evaluate(("launcher", *suffix)) is expected
    assert RawArgvPreflightV1.evaluate(("x" * 20_000, *suffix)) is expected


@pytest.mark.parametrize(
    "at_limit",
    [
        pytest.param("a" * 8192, id="ascii"),
        pytest.param("汉" * 8192, id="han"),
        pytest.param("😀" * 8192, id="astral"),
        pytest.param("é" * 8192, id="composed"),
        pytest.param("e\u0301" * 4096, id="decomposed"),
        pytest.param("\0" * 8192, id="nul"),
        pytest.param("\x1f" * 8192, id="control"),
        pytest.param("\ud800" * 8192, id="lone-surrogate"),
    ],
)
def test_character_matrix_uses_python_string_elements_without_encoding(
    at_limit: str,
) -> None:
    assert RawArgvPreflightV1.evaluate(("launcher", at_limit)) is (
        RawArgvPreflightVerdictV1.PASS
    )
    assert RawArgvPreflightV1.evaluate(("launcher", at_limit + "x")) is (
        RawArgvPreflightVerdictV1.RESOURCE_LIMIT_EXCEEDED
    )


def test_raw_whitespace_is_rejected_before_later_normalization() -> None:
    assert RawArgvPreflightV1.evaluate(("launcher", " " * 8192 + "x")) is (
        RawArgvPreflightVerdictV1.RESOURCE_LIMIT_EXCEEDED
    )


def test_multiple_exceeded_dimensions_return_the_same_no_payload_verdict() -> None:
    snapshot = ("launcher", "x" * 8193, *("",) * 128)

    assert RawArgvPreflightV1.evaluate(snapshot) is (
        RawArgvPreflightVerdictV1.RESOURCE_LIMIT_EXCEEDED
    )


def test_memory_error_is_not_mapped_to_a_resource_verdict() -> None:
    class _MemoryExhaustedString(str):
        def __len__(self) -> int:
            raise MemoryError

    with pytest.raises(MemoryError):
        RawArgvPreflightV1.evaluate(("launcher", _MemoryExhaustedString("value")))
