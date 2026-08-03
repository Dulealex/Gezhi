from __future__ import annotations

from launcher_support import RESOURCE_LIMIT_STDERR, run_both_launchers


def test_both_launchers_reject_argument_count_limit_plus_one() -> None:
    results = run_both_launchers([""] * 129)

    assert [
        (result.returncode, result.stdout, result.stderr) for result in results
    ] == [
        (2, b"", RESOURCE_LIMIT_STDERR),
        (2, b"", RESOURCE_LIMIT_STDERR),
    ]
