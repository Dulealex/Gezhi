from __future__ import annotations

import pytest

from gezhi._raw_argv import RawArgvPreflightV1, RawArgvPreflightVerdictV1


@pytest.mark.parametrize(
    ("token_size", "expected"),
    [
        (8191, RawArgvPreflightVerdictV1.PASS),
        (8192, RawArgvPreflightVerdictV1.PASS),
        (8193, RawArgvPreflightVerdictV1.RESOURCE_LIMIT_EXCEEDED),
    ],
)
def test_per_argument_limit_is_inclusive_and_argv0_is_excluded(
    token_size: int,
    expected: RawArgvPreflightVerdictV1,
) -> None:
    suffix = "a" * token_size

    assert RawArgvPreflightV1.evaluate(("launcher", suffix)) is expected
    assert RawArgvPreflightV1.evaluate(("x" * 20_000, suffix)) is expected
