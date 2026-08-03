from __future__ import annotations

import pytest

from gezhi._raw_argv import RawArgvPreflightV1, RawArgvPreflightVerdictV1

OVERLONG_UNICODE_ARGV0 = "界" * 20_000


def _token_with_element_count(pattern: str, element_count: int) -> str:
    repetitions, remainder = divmod(element_count, len(pattern))
    return pattern * repetitions + pattern[:remainder]


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
    assert RawArgvPreflightV1.evaluate((OVERLONG_UNICODE_ARGV0, *suffix)) is expected


@pytest.mark.parametrize(
    "pattern",
    [
        pytest.param("a", id="ascii"),
        pytest.param("汉", id="han"),
        pytest.param("😀", id="astral"),
        pytest.param("é", id="composed"),
        pytest.param("e\u0301", id="decomposed"),
        pytest.param("\0", id="nul"),
        pytest.param("\x1f", id="control"),
        pytest.param("\ud800", id="lone-surrogate"),
    ],
)
@pytest.mark.parametrize(
    ("element_count", "expected"),
    [
        (8191, RawArgvPreflightVerdictV1.PASS),
        (8192, RawArgvPreflightVerdictV1.PASS),
        (8193, RawArgvPreflightVerdictV1.RESOURCE_LIMIT_EXCEEDED),
    ],
)
def test_character_matrix_counts_python_string_elements_and_excludes_argv0(
    pattern: str,
    element_count: int,
    expected: RawArgvPreflightVerdictV1,
) -> None:
    token = _token_with_element_count(pattern, element_count)
    assert len(token) == element_count

    assert RawArgvPreflightV1.evaluate(("launcher", token)) is expected
    assert RawArgvPreflightV1.evaluate((OVERLONG_UNICODE_ARGV0, token)) is expected


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
