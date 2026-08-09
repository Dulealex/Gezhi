from __future__ import annotations

import subprocess
import sys
import time
from io import BytesIO
from pathlib import Path
from subprocess import Popen as PopenType
from typing import Any, cast

import pytest

from gezhi import _bounded_probe as bounded_probe
from gezhi._bounded_probe import (
    ProbeOutputLimitExceeded,
    run_bounded_probe_v1,
)


def test_probe_capture_accepts_the_exact_combined_limit() -> None:
    result = run_bounded_probe_v1(
        (
            sys.executable,
            "-I",
            "-B",
            "-c",
            "import os; os.write(1, b'a' * 2048); os.write(2, b'b' * 2048)",
        ),
        timeout_seconds=10,
        output_limit=4_096,
        creation_flags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )

    assert (result.returncode, len(result.stdout), len(result.stderr)) == (
        0,
        2_048,
        2_048,
    )


def test_probe_capture_kills_a_child_at_limit_plus_one() -> None:
    with pytest.raises(ProbeOutputLimitExceeded):
        run_bounded_probe_v1(
            (
                sys.executable,
                "-I",
                "-B",
                "-c",
                "import os; os.write(1, b'x' * 65536)",
            ),
            timeout_seconds=10,
            output_limit=4_096,
            creation_flags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )


def test_probe_timeout_settles_a_descendant_that_inherits_the_pipes(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "escaped.txt"
    grandchild = (
        "import pathlib,time;"
        "time.sleep(2);"
        f"pathlib.Path({str(marker)!r}).write_text('escaped')"
    )
    root = (
        "import os,subprocess,sys;"
        f"subprocess.Popen([sys.executable,'-I','-B','-c',{grandchild!r}]);"
        "os.write(1,b'ready')"
    )
    started = time.monotonic()

    with pytest.raises(subprocess.TimeoutExpired):
        run_bounded_probe_v1(
            (sys.executable, "-I", "-B", "-c", root),
            timeout_seconds=0.75,
            output_limit=4_096,
            creation_flags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    assert time.monotonic() - started < 1.5
    time.sleep(2.1)
    assert not marker.exists()


def test_assignment_failure_terminates_the_still_suspended_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[PopenType[bytes]] = []
    real_popen = bounded_probe.subprocess.Popen

    def popen(*args: object, **kwargs: object) -> PopenType[bytes]:
        process = cast(PopenType[bytes], cast(Any, real_popen)(*args, **kwargs))
        created.append(process)
        return process

    def reject_assignment(_job: int, _process: int) -> int:
        bounded_probe.ctypes.set_last_error(5)
        return 0

    monkeypatch.setattr(bounded_probe.subprocess, "Popen", popen)
    monkeypatch.setattr(
        bounded_probe,
        "_ASSIGN_PROCESS_TO_JOB_OBJECT",
        reject_assignment,
    )

    with pytest.raises(
        bounded_probe.ProbeLifecycleError,
        match="AssignProcessToJobObject",
    ):
        run_bounded_probe_v1(
            (sys.executable, "-I", "-B", "-c", "import time; time.sleep(30)"),
            timeout_seconds=5,
            output_limit=4_096,
            creation_flags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    assert len(created) == 1
    assert created[0].poll() is not None


def test_probe_preserves_keyboard_interrupt_after_settling_the_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class InterruptedProcess:
        stdout = BytesIO()
        stderr = BytesIO()
        returncode = 0

        def wait(self, *, timeout: float) -> int:
            del timeout
            raise KeyboardInterrupt

    process = InterruptedProcess()
    settled: list[object] = []
    monkeypatch.setattr(bounded_probe, "_create_kill_on_close_job", lambda: 7)
    monkeypatch.setattr(
        bounded_probe.subprocess,
        "Popen",
        lambda *_args, **_kwargs: process,
    )
    monkeypatch.setattr(bounded_probe, "_process_handle", lambda _process: 11)
    monkeypatch.setattr(
        bounded_probe,
        "_ASSIGN_PROCESS_TO_JOB_OBJECT",
        lambda _job, _process: 1,
    )
    monkeypatch.setattr(bounded_probe, "_NT_RESUME_PROCESS", lambda _process: 0)
    monkeypatch.setattr(
        bounded_probe,
        "_terminate_job_best_effort",
        lambda job: settled.append(("terminated", job)),
    )
    monkeypatch.setattr(
        bounded_probe,
        "_settle_process_tree",
        lambda observed, job: settled.append(("settled", observed, job)),
    )
    monkeypatch.setattr(bounded_probe, "_CLOSE_HANDLE", lambda _job: 1)

    with pytest.raises(KeyboardInterrupt):
        run_bounded_probe_v1(
            ("probe.exe",),
            timeout_seconds=5,
            output_limit=4_096,
        )

    assert settled == [
        ("terminated", 7),
        ("settled", process, 7),
    ]


def test_probe_preserves_keyboard_interrupt_when_tree_settlement_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class InterruptedProcess:
        stdout = BytesIO()
        stderr = BytesIO()
        returncode = 0

        def wait(self, *, timeout: float) -> int:
            del timeout
            raise KeyboardInterrupt

    closed: list[int] = []

    def close_job(job: int) -> int:
        closed.append(job)
        return 1

    monkeypatch.setattr(bounded_probe, "_create_kill_on_close_job", lambda: 7)
    monkeypatch.setattr(
        bounded_probe.subprocess,
        "Popen",
        lambda *_args, **_kwargs: InterruptedProcess(),
    )
    monkeypatch.setattr(bounded_probe, "_process_handle", lambda _process: 11)
    monkeypatch.setattr(
        bounded_probe,
        "_ASSIGN_PROCESS_TO_JOB_OBJECT",
        lambda _job, _process: 1,
    )
    monkeypatch.setattr(bounded_probe, "_NT_RESUME_PROCESS", lambda _process: 0)
    monkeypatch.setattr(bounded_probe, "_terminate_job_best_effort", lambda _job: None)
    monkeypatch.setattr(
        bounded_probe,
        "_settle_process_tree",
        lambda _process, _job: (_ for _ in ()).throw(
            RuntimeError("tree settlement failed")
        ),
    )
    monkeypatch.setattr(
        bounded_probe,
        "_CLOSE_HANDLE",
        close_job,
    )

    with pytest.raises(KeyboardInterrupt):
        run_bounded_probe_v1(
            ("probe.exe",),
            timeout_seconds=5,
            output_limit=4_096,
        )

    assert closed == [7]


def test_unexpected_reader_failure_is_a_probe_lifecycle_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenStream(BytesIO):
        def read(self, size: int | None = -1) -> bytes:
            del size
            raise ValueError("reader algorithm failed")

    class CompletedProcess:
        stdout = BrokenStream()
        stderr = BytesIO()
        returncode = 0

        def wait(self, *, timeout: float) -> int:
            del timeout
            return 0

    monkeypatch.setattr(bounded_probe, "_create_kill_on_close_job", lambda: 7)
    monkeypatch.setattr(
        bounded_probe.subprocess,
        "Popen",
        lambda *_args, **_kwargs: CompletedProcess(),
    )
    monkeypatch.setattr(bounded_probe, "_process_handle", lambda _process: 11)
    monkeypatch.setattr(
        bounded_probe,
        "_ASSIGN_PROCESS_TO_JOB_OBJECT",
        lambda _job, _process: 1,
    )
    monkeypatch.setattr(bounded_probe, "_NT_RESUME_PROCESS", lambda _process: 0)
    monkeypatch.setattr(bounded_probe, "_job_active_processes", lambda _job: 0)
    monkeypatch.setattr(bounded_probe, "_settle_process_tree", lambda _process, _job: None)
    monkeypatch.setattr(bounded_probe, "_CLOSE_HANDLE", lambda _job: 1)

    with pytest.raises(
        bounded_probe.ProbeLifecycleError,
        match="probe pipe read failed",
    ):
        run_bounded_probe_v1(
            ("probe.exe",),
            timeout_seconds=5,
            output_limit=4_096,
        )


def test_reader_settlement_failure_is_not_hidden_by_an_earlier_fault(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SuspendedProcess:
        stdout = BytesIO()
        stderr = BytesIO()
        returncode = None

    monkeypatch.setattr(bounded_probe, "_create_kill_on_close_job", lambda: 7)
    monkeypatch.setattr(
        bounded_probe.subprocess,
        "Popen",
        lambda *_args, **_kwargs: SuspendedProcess(),
    )
    monkeypatch.setattr(bounded_probe, "_process_handle", lambda _process: 11)
    monkeypatch.setattr(
        bounded_probe,
        "_ASSIGN_PROCESS_TO_JOB_OBJECT",
        lambda _job, _process: 1,
    )
    monkeypatch.setattr(bounded_probe, "_NT_RESUME_PROCESS", lambda _process: -1)
    monkeypatch.setattr(bounded_probe, "_terminate_job_best_effort", lambda _job: None)
    monkeypatch.setattr(bounded_probe, "_settle_process_tree", lambda _process, _job: None)
    monkeypatch.setattr(
        bounded_probe,
        "_join_readers",
        lambda _readers, _streams: (_ for _ in ()).throw(
            bounded_probe.ProbeLifecycleError("probe pipe readers did not settle")
        ),
    )
    monkeypatch.setattr(bounded_probe, "_CLOSE_HANDLE", lambda _job: 1)

    with pytest.raises(
        bounded_probe.ProbeLifecycleError,
        match="probe pipe readers did not settle",
    ):
        run_bounded_probe_v1(
            ("probe.exe",),
            timeout_seconds=5,
            output_limit=4_096,
        )
