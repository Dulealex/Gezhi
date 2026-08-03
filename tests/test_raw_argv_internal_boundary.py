from __future__ import annotations

from typing import cast

import pytest

from gezhi._raw_argv import RawArgvPreflightV1


@pytest.mark.parametrize(
    "malformed_snapshot",
    [
        (),
        (1,),
        ("launcher", object()),
    ],
)
def test_malformed_snapshot_enters_the_internal_boundary(
    malformed_snapshot: tuple[object, ...],
) -> None:
    with pytest.raises((TypeError, ValueError)):
        RawArgvPreflightV1.evaluate(cast(tuple[str, ...], malformed_snapshot))
