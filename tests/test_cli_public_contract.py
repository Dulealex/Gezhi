from __future__ import annotations

from typing import Any

import pytest
from launcher_support import RESOURCE_LIMIT_STDERR, run_both_launchers


def test_help_has_launcher_parity_and_ignores_completion_environment() -> None:
    baseline = run_both_launchers(("--help",))
    completion_environment = {
        "_GEZHI_COMPLETE": "complete_bash",
        "_TYPER_COMPLETE_ARGS": "untrusted completion words",
        "_TYPER_COMPLETE_WORD_TO_COMPLETE": "untrusted",
    }
    with_completion_environment = run_both_launchers(
        ("--help",),
        environment_updates=completion_environment,
    )

    assert [
        (result.returncode, result.stdout, result.stderr) for result in baseline
    ] == [
        (0, baseline[0].stdout, b""),
        (0, baseline[0].stdout, b""),
    ]
    assert [result.stdout for result in with_completion_environment] == [
        baseline[0].stdout,
        baseline[0].stdout,
    ]
    assert all(result.returncode == 0 for result in with_completion_environment)
    assert all(result.stderr == b"" for result in with_completion_environment)
    assert b"Usage: gezhi " in baseline[0].stdout
    assert b"--install-completion" not in baseline[0].stdout
    assert b"--show-completion" not in baseline[0].stdout


def test_parser_call_receives_exact_snapshot_suffix_and_fixed_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gezhi import _cli

    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    class _ParserCallSpy:
        def __call__(self, *args: Any, **kwargs: Any) -> None:
            calls.append((args, kwargs))

    spy = _ParserCallSpy()
    monkeypatch.setattr(_cli, "_build_cli", lambda: spy)
    literal_arguments = (
        "first",
        "*.txt",
        "~",
        "%GEZHI_EXPANSION%",
        "$GEZHI_EXPANSION",
        "二",
    )

    assert _cli.run_cli(literal_arguments) == 0
    assert len(calls) == 1
    positional, keywords = calls[0]
    assert positional == ()
    assert keywords["args"] == literal_arguments
    assert keywords["prog_name"] == "gezhi"
    assert keywords["windows_expand_args"] is False


@pytest.mark.parametrize(
    "arguments",
    [
        pytest.param(("--json", "x" * 8193), id="literal-json"),
        pytest.param(("--help", "x" * 8193), id="literal-help"),
        pytest.param(("--version", "x" * 8193), id="literal-version"),
        pytest.param(("literature", "x" * 8193), id="known-spelling"),
        pytest.param(("not-a-command", "x" * 8193), id="unknown-spelling"),
    ],
)
def test_resource_rejection_precedes_all_token_semantics(
    arguments: tuple[str, ...],
) -> None:
    results = run_both_launchers(arguments)

    assert [
        (result.returncode, result.stdout, result.stderr) for result in results
    ] == [
        (2, b"", RESOURCE_LIMIT_STDERR),
        (2, b"", RESOURCE_LIMIT_STDERR),
    ]
