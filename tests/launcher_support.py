from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
PYTHON_EXE = Path(sys.executable)
CONSOLE_EXE = PYTHON_EXE.with_name("gezhi.exe")
RESOURCE_LIMIT_STDERR = b"gezhi: error: command-line input exceeds safety limits\r\n"


def launcher_commands(arguments: Sequence[str]) -> tuple[list[str], list[str]]:
    suffix = list(arguments)
    return (
        [str(CONSOLE_EXE), *suffix],
        [str(PYTHON_EXE), "-m", "gezhi", *suffix],
    )


def subprocess_environment(
    *,
    pythonpath_roots: Sequence[Path] = (SOURCE_ROOT,),
    updates: Mapping[str, str] | None = None,
) -> dict[str, str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(str(root) for root in pythonpath_roots)
    if updates is not None:
        environment.update(updates)
    return environment


def run_launcher(
    command: Sequence[str],
    *,
    cwd: Path = REPOSITORY_ROOT,
    pythonpath_roots: Sequence[Path] = (SOURCE_ROOT,),
    environment_updates: Mapping[str, str] | None = None,
    timeout: float = 15.0,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        list(command),
        cwd=cwd,
        env=subprocess_environment(
            pythonpath_roots=pythonpath_roots,
            updates=environment_updates,
        ),
        capture_output=True,
        check=False,
        timeout=timeout,
    )


def run_both_launchers(
    arguments: Sequence[str],
    *,
    cwd: Path = REPOSITORY_ROOT,
    pythonpath_roots: Sequence[Path] = (SOURCE_ROOT,),
    environment_updates: Mapping[str, str] | None = None,
    timeout: float = 15.0,
) -> tuple[subprocess.CompletedProcess[bytes], subprocess.CompletedProcess[bytes]]:
    console_command, module_command = launcher_commands(arguments)
    return (
        run_launcher(
            console_command,
            cwd=cwd,
            pythonpath_roots=pythonpath_roots,
            environment_updates=environment_updates,
            timeout=timeout,
        ),
        run_launcher(
            module_command,
            cwd=cwd,
            pythonpath_roots=pythonpath_roots,
            environment_updates=environment_updates,
            timeout=timeout,
        ),
    )


def run_python_script(
    source: str,
    *,
    environment_updates: Mapping[str, str] | None = None,
    timeout: float = 15.0,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [str(PYTHON_EXE), "-c", source],
        cwd=REPOSITORY_ROOT,
        env=subprocess_environment(updates=environment_updates),
        capture_output=True,
        check=False,
        timeout=timeout,
    )


def start_python_script(source: str) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [str(PYTHON_EXE), "-c", source],
        cwd=REPOSITORY_ROOT,
        env=subprocess_environment(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )
