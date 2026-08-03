from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
PYTHON_EXE = Path(sys.executable)
CONSOLE_EXE = PYTHON_EXE.with_name("gezhi.exe")
RESOURCE_LIMIT_STDERR = b"gezhi: error: command-line input exceeds safety limits\r\n"


def _launcher_commands(arguments: list[str]) -> tuple[list[str], list[str]]:
    return (
        [str(CONSOLE_EXE), *arguments],
        [str(PYTHON_EXE), "-m", "gezhi", *arguments],
    )


def _run_launcher(command: list[str]) -> subprocess.CompletedProcess[bytes]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(SOURCE_ROOT)
    return subprocess.run(
        command,
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        check=False,
    )


def test_both_launchers_reject_argument_count_limit_plus_one() -> None:
    results = [_run_launcher(command) for command in _launcher_commands([""] * 129)]

    assert [
        (result.returncode, result.stdout, result.stderr) for result in results
    ] == [
        (2, b"", RESOURCE_LIMIT_STDERR),
        (2, b"", RESOURCE_LIMIT_STDERR),
    ]
