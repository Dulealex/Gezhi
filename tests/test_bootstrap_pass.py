from __future__ import annotations

from test_bootstrap_launchers import _launcher_commands, _run_launcher


def test_both_launchers_share_the_t01_minimal_cli_smoke() -> None:
    # This only proves that PASS reaches the temporary empty graph. T02 owns
    # the lasting parser and no-argument behavior.
    results = [_run_launcher(command) for command in _launcher_commands([])]

    assert [
        (result.returncode, result.stdout, result.stderr) for result in results
    ] == [
        (0, b"", b""),
        (0, b"", b""),
    ]
