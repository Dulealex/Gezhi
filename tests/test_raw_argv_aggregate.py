from __future__ import annotations

import pytest

from gezhi._raw_argv import RawArgvPreflightV1, RawArgvPreflightVerdictV1


@pytest.mark.parametrize(
    ("suffix", "expected"),
    [
        (
            ("a" * 8192, "b" * 8191),
            RawArgvPreflightVerdictV1.PASS,
        ),
        (
            ("a" * 8192, "b" * 8192),
            RawArgvPreflightVerdictV1.PASS,
        ),
        (
            ("a" * 8192, "b" * 8192, "c"),
            RawArgvPreflightVerdictV1.RESOURCE_LIMIT_EXCEEDED,
        ),
    ],
)
def test_aggregate_limit_is_the_exact_sum_and_argv0_is_excluded(
    suffix: tuple[str, ...],
    expected: RawArgvPreflightVerdictV1,
) -> None:
    assert RawArgvPreflightV1.evaluate(("launcher", *suffix)) is expected
    assert RawArgvPreflightV1.evaluate(("x" * 20_000, *suffix)) is expected
