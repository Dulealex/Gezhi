from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
PYTHON_EXE = Path(sys.executable)
CONSOLE_EXE = PYTHON_EXE.with_name("gezhi.exe")
RESOURCE_LIMIT_STDERR = b"gezhi: error: command-line input exceeds safety limits\r\n"


def _launcher_commands(arguments: tuple[str, ...]) -> tuple[list[str], list[str]]:
    return (
        [str(CONSOLE_EXE), *arguments],
        [str(PYTHON_EXE), "-m", "gezhi", *arguments],
    )


def _run_launcher(
    command: list[str],
    *,
    cwd: Path = REPOSITORY_ROOT,
    environment_updates: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(SOURCE_ROOT)
    if environment_updates is not None:
        environment.update(environment_updates)
    return subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        capture_output=True,
        check=False,
    )


def test_help_uses_the_fixed_product_name_and_has_no_completion_options() -> None:
    results = [_run_launcher(command) for command in _launcher_commands(("--help",))]

    assert [
        (result.returncode, result.stdout, result.stderr) for result in results
    ] == [
        (0, results[0].stdout, b""),
        (0, results[0].stdout, b""),
    ]
    assert b"Usage: gezhi " in results[0].stdout
    assert b"--install-completion" not in results[0].stdout
    assert b"--show-completion" not in results[0].stdout


def test_completion_environment_inputs_are_ignored_by_both_launchers() -> None:
    completion_environment = {
        "_GEZHI_COMPLETE": "complete_bash",
        "_TYPER_COMPLETE_ARGS": "untrusted completion words",
        "_TYPER_COMPLETE_WORD_TO_COMPLETE": "untrusted",
    }
    results = [
        _run_launcher(command, environment_updates=completion_environment)
        for command in _launcher_commands(())
    ]

    assert [
        (result.returncode, result.stdout, result.stderr) for result in results
    ] == [(0, b"", b""), (0, b"", b"")]


@pytest.mark.parametrize(
    "literal_token",
    [
        pytest.param("*.txt", id="glob-star"),
        pytest.param("?.txt", id="glob-question"),
        pytest.param("[ab].txt", id="glob-class"),
        pytest.param("~", id="home"),
        pytest.param("%GEZHI_EXPANSION%", id="percent-environment"),
        pytest.param("$GEZHI_EXPANSION", id="dollar-environment"),
    ],
)
def test_windows_expansion_tokens_reach_typer_unchanged(
    tmp_path: Path,
    literal_token: str,
) -> None:
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    results = [
        _run_launcher(
            command,
            cwd=tmp_path,
            environment_updates={"GEZHI_EXPANSION": "expanded-value"},
        )
        for command in _launcher_commands((literal_token,))
    ]
    expected_error = f"No such command '{literal_token}'.".encode("ascii")

    for result in results:
        assert result.returncode == 1
        assert result.stdout == b""
        assert expected_error in result.stderr


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
    results = [_run_launcher(command) for command in _launcher_commands(arguments)]

    assert [
        (result.returncode, result.stdout, result.stderr) for result in results
    ] == [
        (2, b"", RESOURCE_LIMIT_STDERR),
        (2, b"", RESOURCE_LIMIT_STDERR),
    ]
