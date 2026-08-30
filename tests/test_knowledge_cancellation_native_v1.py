from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from launcher_support import (
    PYTHON_EXE,
    REPOSITORY_ROOT,
    SOURCE_ROOT,
    launcher_commands,
    subprocess_environment,
)

_CANCELLATION_PROBE = (
    Path(__file__).parent / "support" / "knowledge_cancellation_probe_v1.py"
)


def _run_native_probe_v1(mode: str, dll_path: Path) -> dict[str, object]:
    completed = subprocess.run(
        [PYTHON_EXE, str(_CANCELLATION_PROBE), mode, str(dll_path)],
        check=True,
        capture_output=True,
        cwd=REPOSITORY_ROOT,
        timeout=15,
    )
    assert completed.stderr == b""
    return json.loads(completed.stdout)


def test_native_handler_and_conditional_seal_share_one_admission_gate(
    tmp_path: Path,
) -> None:
    dll_path = tmp_path / "gezhi_cancel_test_v1.dll"
    completed = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-File",
            str(REPOSITORY_ROOT / "tools" / "build-knowledge-cancellation.ps1"),
            "-OutputPath",
            str(dll_path),
            "-TestHooks",
        ],
        check=True,
        capture_output=True,
        cwd=REPOSITORY_ROOT,
        timeout=30,
    )
    receipt = json.loads(completed.stdout.splitlines()[-1].decode("ascii"))
    assert receipt["test_hooks"] is True
    assert receipt["toolset"] == "14.44.35207"
    assert receipt["windows_sdk"] == "10.0.26100.0"
    probe = _run_native_probe_v1("dispatch-first", dll_path)
    assert probe["mode"] == "dispatch-first"
    assert type(probe["observed_ns"]) is int and probe["observed_ns"] > 0


def test_native_answer_id_cutover_wins_before_a_later_callback(
    tmp_path: Path,
) -> None:
    dll_path = tmp_path / "gezhi_cancel_cutover_test_v1.dll"
    subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-File",
            str(REPOSITORY_ROOT / "tools" / "build-knowledge-cancellation.ps1"),
            "-OutputPath",
            str(dll_path),
            "-TestHooks",
        ],
        check=True,
        capture_output=True,
        cwd=REPOSITORY_ROOT,
        timeout=30,
    )
    probe = _run_native_probe_v1("cutover-first", dll_path)
    assert probe["mode"] == "cutover-first"
    assert type(probe["observed_ns"]) is int and probe["observed_ns"] > 0


def test_concurrent_native_callbacks_publish_complete_generations(
    tmp_path: Path,
) -> None:
    dll_path = tmp_path / "gezhi_cancel_concurrent_test_v1.dll"
    subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-File",
            str(REPOSITORY_ROOT / "tools" / "build-knowledge-cancellation.ps1"),
            "-OutputPath",
            str(dll_path),
            "-TestHooks",
        ],
        check=True,
        capture_output=True,
        cwd=REPOSITORY_ROOT,
        timeout=30,
    )

    assert _run_native_probe_v1("concurrent-callbacks", dll_path) == {
        "generation": 8,
        "mode": "concurrent-callbacks",
    }


def test_native_cutover_cannot_cross_a_poisoned_publication_window(
    tmp_path: Path,
) -> None:
    dll_path = tmp_path / "gezhi_cancel_poison_test_v1.dll"
    subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-File",
            str(REPOSITORY_ROOT / "tools" / "build-knowledge-cancellation.ps1"),
            "-OutputPath",
            str(dll_path),
            "-TestHooks",
        ],
        check=True,
        capture_output=True,
        cwd=REPOSITORY_ROOT,
        timeout=30,
    )

    assert _run_native_probe_v1("poisoned-publication", dll_path) == {
        "mode": "poisoned-publication",
        "proof": "rejected",
    }


def test_test_hooks_require_an_explicit_nonproduction_output_path() -> None:
    production = REPOSITORY_ROOT / "src" / "gezhi" / "_native" / "gezhi_cancel_v1.dll"
    before = hashlib.sha256(production.read_bytes()).hexdigest()

    completed = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-File",
            str(REPOSITORY_ROOT / "tools" / "build-knowledge-cancellation.ps1"),
            "-TestHooks",
        ],
        check=False,
        capture_output=True,
        cwd=REPOSITORY_ROOT,
        timeout=15,
    )

    assert completed.returncode != 0
    assert b"explicit OutputPath" in completed.stderr
    assert hashlib.sha256(production.read_bytes()).hexdigest() == before


@pytest.mark.parametrize(
    "output_path",
    (
        str(REPOSITORY_ROOT / "src" / "gezhi" / "_native" / "gezhi_cancel_v1.dll"),
        str(
            REPOSITORY_ROOT / "src" / "gezhi" / "_native" / "gezhi_cancel_v1.dll"
        ).swapcase(),
        r"src\gezhi\_native\..\_native\gezhi_cancel_v1.dll",
        "\\\\?\\"
        + str(REPOSITORY_ROOT / "src" / "gezhi" / "_native" / "gezhi_cancel_v1.dll"),
    ),
    ids=("absolute", "case-alias", "relative-dotdot-alias", "extended-path-alias"),
)
def test_test_hooks_reject_production_output_aliases_before_tool_discovery(
    output_path: str,
) -> None:
    production = REPOSITORY_ROOT / "src" / "gezhi" / "_native" / "gezhi_cancel_v1.dll"
    before = hashlib.sha256(production.read_bytes()).hexdigest()

    completed = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-File",
            str(REPOSITORY_ROOT / "tools" / "build-knowledge-cancellation.ps1"),
            "-OutputPath",
            output_path,
            "-TestHooks",
        ],
        check=False,
        capture_output=True,
        cwd=REPOSITORY_ROOT,
        env=subprocess_environment(
            updates={
                "ProgramFiles(x86)": str(REPOSITORY_ROOT / "missing-program-files-x86")
            }
        ),
        timeout=15,
    )

    assert completed.returncode != 0
    assert b"refuses the production DLL OutputPath" in completed.stderr
    assert b"vswhere" not in completed.stderr
    assert hashlib.sha256(production.read_bytes()).hexdigest() == before


def test_test_hooks_never_overwrite_an_existing_output(
    tmp_path: Path,
) -> None:
    existing_output = tmp_path / "existing-test-hook-output.dll"
    existing_output.write_bytes(b"existing bytes")

    completed = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-File",
            str(REPOSITORY_ROOT / "tools" / "build-knowledge-cancellation.ps1"),
            "-OutputPath",
            str(existing_output),
            "-TestHooks",
        ],
        check=False,
        capture_output=True,
        cwd=REPOSITORY_ROOT,
        env=subprocess_environment(
            updates={
                "ProgramFiles(x86)": str(REPOSITORY_ROOT / "missing-program-files-x86")
            }
        ),
        timeout=15,
    )

    assert completed.returncode != 0
    assert b"requires a new OutputPath" in completed.stderr
    assert b"vswhere" not in completed.stderr
    assert existing_output.read_bytes() == b"existing bytes"


def test_public_ask_uses_no_source_profile_without_a_console() -> None:
    arguments = ("knowledge", "ask", " ", "--json")

    for command in launcher_commands(arguments):
        result = subprocess.run(
            command,
            cwd=REPOSITORY_ROOT,
            env=subprocess_environment(pythonpath_roots=(SOURCE_ROOT,)),
            capture_output=True,
            check=False,
            timeout=15,
            creationflags=0x08000000,
        )
        assert result.returncode == 2, (result.stdout + result.stderr).decode(
            errors="replace"
        )
        assert result.stderr == b""
        assert json.loads(result.stdout) == {
            "command": "knowledge.ask",
            "diagnostics": [
                {"code": "knowledge.ask.invalid_question.v1", "context": {}}
            ],
            "outcome": "blocked",
            "result": None,
            "schema_version": "gezhi.cli_result.v1",
        }


def test_redirected_stdio_with_a_hidden_console_uses_the_native_profile() -> None:
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    completed = subprocess.run(
        [PYTHON_EXE, str(_CANCELLATION_PROBE), "interactive-profile"],
        cwd=REPOSITORY_ROOT,
        env=subprocess_environment(pythonpath_roots=(SOURCE_ROOT,)),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        timeout=15,
        creationflags=0x00000010,
        startupinfo=startupinfo,
    )

    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    assert completed.stderr == b""
    assert json.loads(completed.stdout) == {
        "mode": "interactive-profile",
        "source": "native",
    }
