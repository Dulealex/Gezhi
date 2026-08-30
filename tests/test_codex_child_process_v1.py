from __future__ import annotations

import ctypes
import hashlib
import json
import os
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from gezhi import _codex_child_process as child_process
from gezhi import _windows_data_root as windows_root
from gezhi._codex_child_process import (
    CODEX_JOB_STOP_EXIT_DWORD_V1,
    KNOWLEDGE_EVENTS_CAPTURE_CAP_V1,
    KNOWLEDGE_FINAL_CAPTURE_CAP_V1,
    LITERATURE_EVENTS_CAPTURE_CAP_V1,
    LITERATURE_FINAL_CAPTURE_CAP_V1,
    CodexChildTestHooksV1,
    CodexChildUnsafeHoldErrorV1,
    CodexChildWin32ErrorV1,
    NeverCancelledV1,
    PreAttemptRejectedV1,
    _classify_mechanical_outcome_v1,
    _run_codex_child_with_test_hooks_v1,
)
from gezhi._codex_child_process import (
    _run_codex_child_test_double_v1 as run_codex_child_v1,
)
from gezhi._codex_child_process import (
    run_codex_child_v1 as run_production_codex_child_v1,
)
from gezhi._codex_role_plan import (
    _freeze_test_double_launch_v1,
    freeze_codex_attempt_workspace_v1,
    freeze_codex_role_launch_v1,
    quote_windows_argv_v1,
)
from gezhi._codex_runtime import resolve_codex_runtime_v1
from tests.support.codex_pipe_observer_v1 import (
    measure_same_pipe_capacities_v1,
)
from tests.support.codex_runtime_fixture_v1 import (
    build_project_codex_runtime_fixture_v1,
)

_DOUBLE = Path(__file__).parent / "support" / "codex_child_executable_double_v1.py"


class _FixedCancellation:
    def __init__(self, observed_at_ns: int) -> None:
        self._observed_at_ns = observed_at_ns

    def observed_at_monotonic_ns(self) -> int:
        return self._observed_at_ns


class _LatchedCancellation:
    def __init__(self) -> None:
        self._observed_at_ns: int | None = None

    def trigger(self, observed_at_ns: int | None = None) -> None:
        assert self._observed_at_ns is None
        self._observed_at_ns = (
            time.monotonic_ns() if observed_at_ns is None else observed_at_ns
        )

    def observed_at_monotonic_ns(self) -> int | None:
        return self._observed_at_ns


class _CancelDuringObservation:
    def observed_at_monotonic_ns(self) -> int:
        return time.monotonic_ns()


class _CancelOnSecondObservation:
    def __init__(self) -> None:
        self.calls = 0

    def observed_at_monotonic_ns(self) -> int | None:
        self.calls += 1
        return None if self.calls == 1 else time.monotonic_ns()


class _FaultOnCancellationObservation:
    def __init__(self, call: int) -> None:
        self._fault_call = call
        self.calls = 0

    def observed_at_monotonic_ns(self) -> None:
        self.calls += 1
        if self.calls == self._fault_call:
            raise RuntimeError("injected cancellation observation fault")


class _FaultAfterCaptureInstall:
    def __init__(self, capture: Path) -> None:
        self._capture = capture

    def observed_at_monotonic_ns(self) -> None:
        if self._capture.exists():
            raise RuntimeError("injected terminal observation fault")


class _PersistentCancellationFaultAfter:
    def __init__(self, successful_calls: int) -> None:
        self._successful_calls = successful_calls
        self.calls = 0

    def observed_at_monotonic_ns(self) -> None:
        self.calls += 1
        if self.calls > self._successful_calls:
            raise RuntimeError("persistent cancellation observation fault")


class _CaptureGatedCancellation:
    def __init__(self, capture: Path, observed_at_ns: int) -> None:
        self._capture = capture
        self._observed_at_ns = observed_at_ns

    def observed_at_monotonic_ns(self) -> int | None:
        return self._observed_at_ns if self._capture.exists() else None


@pytest.fixture(autouse=True)
def _allow_pytest_temporary_short_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        windows_root,
        "_reject_hidden_short_alias",
        lambda _parent, _component: None,
    )


def _plan(
    tmp_path: Path,
    scenario: str,
    *,
    prompt: bytes = b"reader input",
    value: int = 0,
    timeout_seconds: float = 10,
    capture_profile: str = "knowledge",
    extra_arguments: tuple[str, ...] = (),
    existing_shared_deadline_monotonic_ns: int | None = None,
):
    working = tmp_path / "working"
    temporary = tmp_path / "temporary"
    attempts = tmp_path / "attempts"
    for path in (working, temporary, attempts):
        path.mkdir(parents=True)
    staging = attempts / ".01.codex-stage"
    capture = attempts / "01"
    final = staging / ".final_message.spool"
    arguments = (
        "-I",
        "-B",
        str(_DOUBLE),
        scenario,
        "--final",
        str(final),
        "--value",
        str(value),
        *extra_arguments,
    )
    return _freeze_test_double_launch_v1(
        executable=Path(sys.executable),
        arguments=arguments,
        prompt=prompt,
        attempt_ordinal=1,
        working_directory=working,
        capture_directory=capture,
        staging_directory=staging,
        temporary_directory=temporary,
        source_environment={"SystemRoot": os.environ["SystemRoot"]},
        timeout_seconds=timeout_seconds,
        capture_profile=capture_profile,
        existing_shared_deadline_monotonic_ns=existing_shared_deadline_monotonic_ns,
    )


def _production_plan(
    tmp_path: Path,
    *,
    role: str = "literature_reader_v1",
):  # type: ignore[no-untyped-def]
    project = tmp_path / "project"
    project.mkdir()
    build_project_codex_runtime_fixture_v1(project)
    schema = project / "schemas" / "role-output-v1.json"
    schema.parent.mkdir()
    schema.write_text("{}", encoding="utf-8")
    attempt = tmp_path / "attempt"
    attempt.mkdir()
    for name in ("captures", "sqlite", "temporary", "working"):
        (attempt / name).mkdir()
    literature = tmp_path / "literature-authoritative"
    knowledge = tmp_path / "knowledge-authoritative"
    codex_home = tmp_path / "codex-home"
    for path in (literature, knowledge, codex_home):
        path.mkdir()
    workspace = (
        freeze_codex_attempt_workspace_v1(
            role="literature_reader_v1",
            attempt_root=attempt,
            attempt_ordinal=1,
            literature_authoritative_root=literature,
        )
        if role == "literature_reader_v1"
        else freeze_codex_attempt_workspace_v1(
            role="knowledge_answerer_v1",
            attempt_root=attempt,
            attempt_ordinal=1,
            knowledge_authoritative_root=knowledge,
        )
    )
    plan = freeze_codex_role_launch_v1(
        runtime=resolve_codex_runtime_v1(project),
        role=role,
        prompt=b"production-boundary-test",
        attempt_ordinal=1,
        workspace=workspace,
        schema_path=schema,
        codex_home=codex_home,
        source_environment={"SystemRoot": os.environ["SystemRoot"]},
    )
    return plan, {
        "attempt-root": attempt,
        "working": attempt / "working",
        "temporary": attempt / "temporary",
        "sqlite": attempt / "sqlite",
        "capture-parent": attempt / "captures",
        "literature-authoritative": literature,
        "knowledge-authoritative": knowledge,
        "codex-home": codex_home,
        "schema": schema,
        "executable": Path(plan.executable_path),
    }


def test_success_traverses_real_kernel_seam_and_freezes_raw_captures(
    tmp_path: Path,
) -> None:
    prompt = (b"0123456789abcdef" * 8_193) + b"tail"
    plan = _plan(tmp_path, "success", prompt=prompt)

    evidence = run_codex_child_v1(plan, NeverCancelledV1())

    receipt = json.loads(evidence.events.path.read_bytes())
    assert receipt == {
        "type": "double.prompt",
        "length": len(prompt),
        "sha256": hashlib.sha256(prompt).hexdigest(),
    }
    assert evidence.final_message is not None
    assert evidence.final_message.path.read_bytes() == b'{"answer":"double-success"}\n'
    assert evidence.exit_code == 0
    assert evidence.mechanical_outcome == "clean"
    assert evidence.create_process_calls == 1
    assert evidence.stop_calls == 0
    assert evidence.provider_started_monotonic_ns is not None
    assert evidence.resource_ledger_count == 0


def test_production_entry_rejects_a_test_double_plan(tmp_path: Path) -> None:
    # Keep the role deadline deliberately outside this arbitration test.  The
    # only boundary under test is cancel == ready versus cancel > ready.
    plan = _plan(tmp_path, "success", timeout_seconds=60)

    with pytest.raises(TypeError, match="sealed production_codex"):
        run_production_codex_child_v1(plan, NeverCancelledV1())


def test_measured_pipe_capacities_prove_bidirectional_backpressure(
    tmp_path: Path,
) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_event = kernel32.CreateEventW
    create_event.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_wchar_p,
    ]
    create_event.restype = ctypes.c_void_p
    set_event = kernel32.SetEvent
    set_event.argtypes = [ctypes.c_void_p]
    set_event.restype = ctypes.c_int
    wait = kernel32.WaitForSingleObject
    wait.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    wait.restype = ctypes.c_ulong
    close = kernel32.CloseHandle
    close.argtypes = [ctypes.c_void_p]
    close.restype = ctypes.c_int
    suffix = uuid.uuid4().hex
    names = {
        "started": f"Local\\Gezhi.T13.StdoutStarted.{suffix}",
        "returned": f"Local\\Gezhi.T13.StdoutReturned.{suffix}",
        "stdin": f"Local\\Gezhi.T13.StdinGate.{suffix}",
    }
    handles = {
        name: int(create_event(None, True, False, value))
        for name, value in names.items()
    }
    assert all(handles.values())
    plan = _plan(
        tmp_path,
        "dual-backpressure",
        prompt=b"test seam replaces this prompt after measuring the pipe",
        extra_arguments=(
            "--stdout-bytes",
            "0",
            "--stdout-started-event",
            names["started"],
            "--stdout-returned-event",
            names["returned"],
            "--stdin-read-gate-event",
            names["stdin"],
        ),
    )
    hooks = CodexChildTestHooksV1(
        collector_read_gate=threading.Event(),
        collector_waiting_at_gate=threading.Event(),
        collector_read_observed=threading.Event(),
        stdin_write_call_active=threading.Event(),
        pipe_capacity_observer=measure_same_pipe_capacities_v1,
        prompt_factory=lambda stdin_capacity, _stdout_capacity: (
            b"p" * (4 * stdin_capacity + 17)
        ),
        command_line_factory=lambda _stdin_capacity, stdout_capacity: (
            quote_windows_argv_v1(
                tuple(
                    str(4 * stdout_capacity + 17)
                    if index == plan.argv.index("--stdout-bytes") + 1
                    else value
                    for index, value in enumerate(plan.argv)
                )
            )
        ),
    )
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                _run_codex_child_with_test_hooks_v1,
                plan,
                NeverCancelledV1(),
                hooks,
            )
            assert hooks.collector_waiting_at_gate is not None
            assert hooks.collector_waiting_at_gate.wait(5)
            assert wait(handles["started"], 5_000) == 0
            assert hooks.stdin_write_call_active is not None
            assert hooks.stdin_write_call_active.wait(5)
            assert wait(handles["returned"], 0) == 0x102
            assert hooks.collector_read_gate is not None
            hooks.collector_read_gate.set()
            assert wait(handles["returned"], 5_000) == 0
            assert set_event(handles["stdin"])
            evidence = future.result(timeout=10)
    finally:
        assert all(close(handle) for handle in handles.values())

    assert hooks.measured_stdin_pipe_capacity_bytes is not None
    assert hooks.measured_stdout_pipe_capacity_bytes is not None
    assert hooks.selected_prompt is not None
    assert hooks.selected_command_line is not None
    prompt = hooks.selected_prompt
    assert len(prompt) == 4 * hooks.measured_stdin_pipe_capacity_bytes + 17
    stdout_length = 4 * hooks.measured_stdout_pipe_capacity_bytes + 17
    assert evidence.events.byte_length == stdout_length
    assert evidence.events.path.read_bytes() == b"o" * stdout_length
    assert evidence.final_message is not None
    receipt = json.loads(evidence.final_message.path.read_bytes())
    assert receipt["sha256"] == hashlib.sha256(prompt).hexdigest()
    assert hooks.collector_read_seen_before_writer_join is True
    assert evidence.create_process_calls == 1
    assert evidence.stop_calls == 0
    assert evidence.resource_ledger_count == 0


def test_nonzero_exit_preserves_unsigned_exit_and_capture(tmp_path: Path) -> None:
    plan = _plan(tmp_path, "exit", value=37)

    evidence = run_codex_child_v1(plan, NeverCancelledV1())

    assert evidence.exit_code == 37
    assert evidence.mechanical_outcome == "provider_or_process_exit"
    assert evidence.events.byte_length > 0
    assert evidence.final_message is not None
    assert evidence.resource_ledger_count == 0


@pytest.mark.parametrize("scenario", ["hang", "descendant-hang", "no-read-hang"])
def test_deadline_stops_the_whole_job_and_settles_workers(
    tmp_path: Path,
    scenario: str,
) -> None:
    prompt = b"p" * 1_000_000 if scenario == "no-read-hang" else b"prompt"
    plan = _plan(
        tmp_path,
        scenario,
        prompt=prompt,
        timeout_seconds=0.35,
    )
    started = time.monotonic()

    evidence = run_codex_child_v1(plan, NeverCancelledV1())

    assert time.monotonic() - started < 5
    assert evidence.mechanical_outcome == "timeout"
    assert evidence.stop_calls == 1
    assert evidence.resource_ledger_count == 0
    assert evidence.events.path.is_file()
    assert evidence.final_message is not None


def test_stderr_is_nul_and_cannot_backpressure_the_child(tmp_path: Path) -> None:
    plan = _plan(tmp_path, "stderr-flood")

    evidence = run_codex_child_v1(plan, NeverCancelledV1())

    assert evidence.mechanical_outcome == "clean"
    assert evidence.exit_code == 0
    assert evidence.events.byte_length > 0


@pytest.mark.parametrize(
    ("length", "overflow"),
    [
        (KNOWLEDGE_EVENTS_CAPTURE_CAP_V1, False),
        (KNOWLEDGE_EVENTS_CAPTURE_CAP_V1 + 1, True),
    ],
)
def test_knowledge_events_overflow_latches_only_on_cap_plus_one(
    tmp_path: Path,
    length: int,
    overflow: bool,
) -> None:
    plan = _plan(
        tmp_path,
        "events-overflow-hang" if overflow else "events-bytes",
        value=length,
        timeout_seconds=30,
    )

    evidence = run_codex_child_v1(plan, NeverCancelledV1())

    assert evidence.events.byte_length == KNOWLEDGE_EVENTS_CAPTURE_CAP_V1
    assert evidence.events.overflow is overflow
    assert evidence.stop_calls == int(overflow)
    assert evidence.mechanical_outcome == ("process_error" if overflow else "clean")


@pytest.mark.parametrize(
    ("length", "overflow"),
    [
        (KNOWLEDGE_FINAL_CAPTURE_CAP_V1, False),
        (KNOWLEDGE_FINAL_CAPTURE_CAP_V1 + 1, True),
    ],
)
def test_knowledge_final_overflow_retains_the_exact_prefix(
    tmp_path: Path,
    length: int,
    overflow: bool,
) -> None:
    plan = _plan(tmp_path, "final-bytes", value=length)

    evidence = run_codex_child_v1(plan, NeverCancelledV1())

    assert evidence.final_message is not None
    assert evidence.final_message.byte_length == KNOWLEDGE_FINAL_CAPTURE_CAP_V1
    assert evidence.final_message.overflow is overflow
    assert evidence.mechanical_outcome == ("process_error" if overflow else "clean")


def test_active_final_overflow_witness_requests_one_job_stop(tmp_path: Path) -> None:
    plan = _plan(
        tmp_path,
        "final-overflow-hang",
        value=KNOWLEDGE_FINAL_CAPTURE_CAP_V1 + 1,
        timeout_seconds=60,
    )

    evidence = run_codex_child_v1(plan, NeverCancelledV1())

    assert evidence.final_message is not None
    assert evidence.final_message.overflow
    assert evidence.stop_calls == 1
    assert evidence.mechanical_outcome == "process_error"


def test_literature_active_final_overflow_stops_before_its_deadline(
    tmp_path: Path,
) -> None:
    plan = _plan(
        tmp_path,
        "final-overflow-hang",
        value=LITERATURE_FINAL_CAPTURE_CAP_V1 + 1,
        timeout_seconds=10,
        capture_profile="literature",
    )
    started = time.monotonic()

    evidence = run_codex_child_v1(plan, NeverCancelledV1())

    assert time.monotonic() - started < 5
    assert evidence.final_message is not None
    assert evidence.final_message.byte_length == LITERATURE_FINAL_CAPTURE_CAP_V1
    assert evidence.final_message.overflow
    assert evidence.stop_calls == 1
    assert evidence.mechanical_outcome == "process_error"


@pytest.mark.parametrize(
    ("length", "overflow"),
    [
        (LITERATURE_EVENTS_CAPTURE_CAP_V1, False),
        (LITERATURE_EVENTS_CAPTURE_CAP_V1 + 1, True),
    ],
)
def test_literature_events_overflow_latches_only_on_cap_plus_one(
    tmp_path: Path,
    length: int,
    overflow: bool,
) -> None:
    plan = _plan(
        tmp_path,
        "events-overflow-hang" if overflow else "events-bytes",
        value=length,
        timeout_seconds=5,
        capture_profile="literature",
    )

    evidence = run_codex_child_v1(plan, NeverCancelledV1())

    assert evidence.events.byte_length == LITERATURE_EVENTS_CAPTURE_CAP_V1
    assert evidence.events.overflow is overflow
    assert evidence.stop_calls == int(overflow)
    assert evidence.mechanical_outcome == ("process_error" if overflow else "clean")


@pytest.mark.parametrize(
    ("length", "overflow"),
    [
        (LITERATURE_FINAL_CAPTURE_CAP_V1, False),
        (LITERATURE_FINAL_CAPTURE_CAP_V1 + 1, True),
    ],
)
def test_literature_final_overflow_retains_the_exact_prefix(
    tmp_path: Path,
    length: int,
    overflow: bool,
) -> None:
    plan = _plan(
        tmp_path,
        "final-bytes",
        value=length,
        capture_profile="literature",
    )

    evidence = run_codex_child_v1(plan, NeverCancelledV1())

    assert evidence.final_message is not None
    assert evidence.final_message.byte_length == LITERATURE_FINAL_CAPTURE_CAP_V1
    assert evidence.final_message.overflow is overflow
    assert evidence.mechanical_outcome == ("process_error" if overflow else "clean")


def test_stdout_chunk_boundaries_do_not_change_raw_bytes(tmp_path: Path) -> None:
    plan = _plan(tmp_path, "chunk-boundaries")

    evidence = run_codex_child_v1(plan, NeverCancelledV1())

    expected = b"a" + (b"b" * 65_535) + (b"c" * 65_536) + (b"d" * 65_537)
    assert evidence.events.path.read_bytes() == expected
    assert evidence.mechanical_outcome == "clean"


def test_zero_byte_child_write_is_not_stdout_eof(tmp_path: Path) -> None:
    plan = _plan(tmp_path, "zero-stdout-write")

    evidence = run_codex_child_v1(plan, NeverCancelledV1())

    assert evidence.events.path.read_bytes() == b"after-zero"
    assert evidence.mechanical_outcome == "clean"


def test_root_exit_does_not_complete_before_a_descendant_releases_stdout(
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path, "finite-descendant")
    started = time.monotonic()

    evidence = run_codex_child_v1(plan, NeverCancelledV1())

    assert time.monotonic() - started >= 0.10
    assert evidence.events.path.read_bytes() == b"root-descendant"
    assert evidence.mechanical_outcome == "clean"


def test_no_console_and_exact_stdio_kinds(tmp_path: Path) -> None:
    plan = _plan(tmp_path, "inspect-handles")

    evidence = run_codex_child_v1(plan, NeverCancelledV1())

    assert json.loads(evidence.events.path.read_bytes()) == {
        "console": False,
        "stdin_type": 3,
        "stdout_type": 3,
        "stderr_type": 2,
        "sentinels": [],
        "prompt_length": len(b"reader input"),
        "prompt_sha256": hashlib.sha256(b"reader input").hexdigest(),
    }


def test_inheritable_handles_outside_the_allowlist_are_unavailable(
    tmp_path: Path,
) -> None:
    class SecurityAttributes(ctypes.Structure):
        _fields_ = (
            ("length", ctypes.c_ulong),
            ("descriptor", ctypes.c_void_p),
            ("inherit", ctypes.c_int),
        )

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_event = kernel32.CreateEventW
    create_event.argtypes = [
        ctypes.POINTER(SecurityAttributes),
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_wchar_p,
    ]
    create_event.restype = ctypes.c_void_p
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [ctypes.c_void_p]
    close_handle.restype = ctypes.c_int
    wait_for_single_object = kernel32.WaitForSingleObject
    wait_for_single_object.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    wait_for_single_object.restype = ctypes.c_ulong
    security = SecurityAttributes(ctypes.sizeof(SecurityAttributes), None, True)
    sentinels = tuple(
        int(create_event(ctypes.byref(security), True, False, None)) for _ in range(8)
    )
    assert all(sentinels)
    arguments = tuple(
        item for handle in sentinels for item in ("--sentinel", str(handle))
    )
    plan = _plan(
        tmp_path,
        "inspect-handles",
        extra_arguments=arguments,
    )
    try:
        evidence = run_codex_child_v1(plan, NeverCancelledV1())
        assert all(wait_for_single_object(handle, 0) == 0x102 for handle in sentinels)
    finally:
        assert all(close_handle(handle) for handle in sentinels)

    payload = json.loads(evidence.events.path.read_bytes())
    assert len(payload["sentinels"]) == len(sentinels)
    assert all(
        set(result) == {"accessible", "set_succeeded", "set_error"}
        for result in payload["sentinels"]
    )


def test_literature_does_not_synthesize_a_missing_final(tmp_path: Path) -> None:
    plan = _plan(tmp_path, "no-final", capture_profile="literature")

    evidence = run_codex_child_v1(plan, NeverCancelledV1())

    assert evidence.final_message is None
    assert not (Path(plan.capture_directory) / "final_message.txt").exists()
    assert evidence.mechanical_outcome == "clean"


def test_capture_is_installed_before_malformed_bytes_are_interpreted(
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path, "malformed")

    evidence = run_codex_child_v1(plan, NeverCancelledV1())

    assert evidence.events.path.read_bytes() == b"\xff{not-json\n"
    assert evidence.final_message is not None
    assert evidence.final_message.path.read_bytes() == b"\xffnot-json"
    assert evidence.mechanical_outcome == "clean"


@pytest.mark.parametrize("exit_code", [130, CODEX_JOB_STOP_EXIT_DWORD_V1])
def test_exit_dword_never_invents_parent_cancellation(
    tmp_path: Path,
    exit_code: int,
) -> None:
    plan = _plan(tmp_path, "exit", value=exit_code)

    evidence = run_codex_child_v1(plan, NeverCancelledV1())

    assert evidence.exit_code == exit_code
    assert evidence.mechanical_outcome == "provider_or_process_exit"


def test_latched_cancellation_stops_a_proven_pending_stdin_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(
        tmp_path,
        "no-read-hang",
        prompt=b"test seam replaces this after measuring the actual pipe",
        timeout_seconds=60,
    )
    hooks = CodexChildTestHooksV1(
        pipe_capacity_observer=measure_same_pipe_capacities_v1,
        prompt_factory=lambda stdin_capacity, _stdout_capacity: (
            b"p" * (4 * stdin_capacity + 17)
        ),
        stdin_write_call_active=threading.Event(),
    )
    cancellation = _LatchedCancellation()
    real_close = child_process._OwnedHandle.close
    wrong_owner_closes: list[str] = []

    def observe_close(handle) -> None:  # type: ignore[no-untyped-def]
        if (
            handle.label == "stdin-write"
            and not threading.current_thread().name.startswith("gezhi-codex-stdin-")
        ):
            wrong_owner_closes.append(threading.current_thread().name)
        real_close(handle)

    monkeypatch.setattr(child_process._OwnedHandle, "close", observe_close)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            _run_codex_child_with_test_hooks_v1,
            plan,
            cancellation,
            hooks,
        )
        assert hooks.stdin_write_call_active is not None
        assert hooks.stdin_write_call_active.wait(5)
        cancellation.trigger()
        evidence = future.result(timeout=10)

    assert wrong_owner_closes == []
    assert evidence.mechanical_outcome == "interrupted"
    assert evidence.create_process_calls == 1
    assert evidence.stop_calls == 1
    assert evidence.resource_ledger_count == 0


def test_cancel_before_commit_creates_no_attempt_or_capture(tmp_path: Path) -> None:
    plan = _plan(tmp_path, "success")

    result = run_codex_child_v1(
        plan,
        _FixedCancellation(time.monotonic_ns() - 1),
    )

    assert isinstance(result, PreAttemptRejectedV1)
    assert result.create_process_calls == 0
    assert result.resource_ledger_count == 0
    assert not Path(plan.capture_directory).exists()
    assert not Path(plan.staging_directory).exists()


@pytest.mark.parametrize(
    "fault",
    ["utc", "monotonic", "cancellation", "invalid-cancellation"],
)
def test_final_precommit_gate_fault_rolls_back_without_an_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    plan = _plan(tmp_path, "success")
    cancellation: object = NeverCancelledV1()

    def raise_fault(*_args: object) -> None:
        raise RuntimeError("injected final precommit gate fault")

    if fault == "utc":
        monkeypatch.setattr(child_process, "_utc_now", raise_fault)
    elif fault == "monotonic":
        monkeypatch.setattr(child_process, "_monotonic_now_ns_v1", raise_fault)
    elif fault == "cancellation":
        cancellation = _FaultOnCancellationObservation(1)
    else:
        cancellation = SimpleNamespace(
            observed_at_monotonic_ns=lambda: True,
        )

    result = run_codex_child_v1(plan, cancellation)  # type: ignore[arg-type]

    assert isinstance(result, PreAttemptRejectedV1)
    assert result.reason in {
        "commit_gate_failed:RuntimeError",
        "commit_gate_failed:ValueError",
    }
    assert result.create_process_calls == 0
    assert result.resource_ledger_count == 0
    assert not Path(plan.capture_directory).exists()
    assert not Path(plan.staging_directory).exists()


@pytest.mark.parametrize("fault_call", [2, 3])
def test_committed_cancellation_observer_fault_stops_and_settles(
    tmp_path: Path,
    fault_call: int,
) -> None:
    plan = _plan(tmp_path, "hang", timeout_seconds=60)
    cancellation = _FaultOnCancellationObservation(fault_call)

    evidence = run_codex_child_v1(plan, cancellation)

    assert evidence.mechanical_outcome == "process_error"
    assert evidence.stop_calls == 1
    assert evidence.resource_ledger_count == 0
    assert any(
        "cancellation_observation:RuntimeError" in fact
        for fact in evidence.lifecycle_facts
    )
    assert (evidence.provider_started_monotonic_ns is not None) is (fault_call == 3)
    assert "provider_started_timestamp_unavailable" not in evidence.lifecycle_facts


@pytest.mark.parametrize("fault_call", [2, 3])
def test_committed_monotonic_clock_fault_stops_and_settles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault_call: int,
) -> None:
    plan = _plan(tmp_path, "hang", timeout_seconds=60)
    real_clock = child_process._monotonic_now_ns_v1
    calls = 0

    def clock() -> int:
        nonlocal calls
        calls += 1
        if calls == fault_call:
            raise RuntimeError("injected committed clock fault")
        return real_clock()

    monkeypatch.setattr(child_process, "_monotonic_now_ns_v1", clock)
    evidence = run_codex_child_v1(plan, NeverCancelledV1())

    assert evidence.mechanical_outcome == "process_error"
    assert evidence.stop_calls == 1
    assert evidence.resource_ledger_count == 0
    assert any(
        "monotonic_clock:RuntimeError" in fact for fact in evidence.lifecycle_facts
    )
    assert evidence.provider_started_monotonic_ns is None
    assert ("provider_started_timestamp_unavailable" in evidence.lifecycle_facts) is (
        fault_call == 3
    )


@pytest.mark.parametrize("fault", ["cancellation", "monotonic"])
def test_terminal_observation_fault_returns_settled_process_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    plan = _plan(tmp_path, "success")
    capture = Path(plan.capture_directory)
    cancellation: object = NeverCancelledV1()
    if fault == "cancellation":
        cancellation = _FaultAfterCaptureInstall(capture)
    else:
        real_clock = child_process._monotonic_now_ns_v1

        def clock() -> int:
            if capture.exists():
                raise RuntimeError("injected terminal clock fault")
            return real_clock()

        monkeypatch.setattr(child_process, "_monotonic_now_ns_v1", clock)

    evidence = run_codex_child_v1(
        plan,
        cancellation,  # type: ignore[arg-type]
    )

    assert evidence.mechanical_outcome == "process_error"
    assert evidence.stop_calls == 0
    assert evidence.resource_ledger_count == 0
    assert capture.is_dir()
    assert (evidence.capture_ready_monotonic_ns is None) is (fault == "monotonic")


def test_persistent_observation_fault_is_latched_once(
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path, "hang", timeout_seconds=60)
    cancellation = _PersistentCancellationFaultAfter(successful_calls=2)

    evidence = run_codex_child_v1(plan, cancellation)

    fact = "cancellation_observation:RuntimeError"
    assert evidence.lifecycle_facts.count(fact) == 1
    assert cancellation.calls >= 3
    assert evidence.stop_calls == 1
    assert evidence.mechanical_outcome == "process_error"
    assert evidence.resource_ledger_count == 0


def test_cancellation_latched_inside_the_final_observation_prevents_commit(
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path, "success")

    result = run_codex_child_v1(plan, _CancelDuringObservation())

    assert isinstance(result, PreAttemptRejectedV1)
    assert result.reason == "cancelled_before_commit"
    assert result.create_process_calls == 0
    assert result.resource_ledger_count == 0


def test_cancellation_latched_inside_the_post_create_gate_prevents_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path, "success")
    cancellation = _CancelOnSecondObservation()

    def forbidden_resume(_thread: int) -> int:
        raise AssertionError("a cancellation observed at the gate must prevent resume")

    monkeypatch.setattr(child_process, "_RESUME_THREAD", forbidden_resume)

    evidence = run_codex_child_v1(plan, cancellation)

    assert evidence.provider_started_monotonic_ns is None
    assert evidence.mechanical_outcome == "interrupted"
    assert evidence.stop_calls == 1
    assert evidence.resource_ledger_count == 0


def test_existing_shared_deadline_before_commit_creates_no_attempt(
    tmp_path: Path,
) -> None:
    plan = _plan(
        tmp_path,
        "success",
        existing_shared_deadline_monotonic_ns=time.monotonic_ns() - 1,
    )

    result = run_codex_child_v1(plan, NeverCancelledV1())

    assert isinstance(result, PreAttemptRejectedV1)
    assert result.reason == "shared_deadline_before_commit"
    assert result.create_process_calls == 0
    assert result.resource_ledger_count == 0


@pytest.mark.parametrize("boundary", ["create", "assign"])
def test_shared_deadline_crossing_kernel_boundary_prevents_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
) -> None:
    real_clock = child_process._monotonic_now_ns_v1
    before_boundary_ns = real_clock()
    shared_deadline_ns = before_boundary_ns + 10
    crossed = False
    plan = _plan(
        tmp_path,
        "success",
        existing_shared_deadline_monotonic_ns=shared_deadline_ns,
    )
    real_create = child_process._CREATE_PROCESS
    real_assign = child_process._ASSIGN_PROCESS_TO_JOB_OBJECT

    def boundary_clock() -> int:
        return shared_deadline_ns + 1 if crossed else before_boundary_ns

    monkeypatch.setattr(
        child_process,
        "_monotonic_now_ns_v1",
        boundary_clock,
    )
    if boundary == "create":

        def create_then_cross(*args):  # type: ignore[no-untyped-def]
            nonlocal crossed
            result = int(real_create(*args))
            crossed = True
            return result

        monkeypatch.setattr(
            child_process,
            "_CREATE_PROCESS",
            create_then_cross,
        )
    else:

        def assign_then_cross(job: int, process: int) -> int:
            nonlocal crossed
            result = int(real_assign(job, process))
            crossed = True
            return result

        monkeypatch.setattr(
            child_process,
            "_ASSIGN_PROCESS_TO_JOB_OBJECT",
            assign_then_cross,
        )

    def forbidden_resume(_thread: int) -> int:
        raise AssertionError("expired shared deadline must prevent ResumeThread")

    monkeypatch.setattr(child_process, "_RESUME_THREAD", forbidden_resume)

    evidence = run_codex_child_v1(plan, NeverCancelledV1())

    assert crossed
    assert evidence.provider_started_monotonic_ns is None
    assert evidence.mechanical_outcome == "timeout"
    assert evidence.create_process_calls == 1
    assert evidence.stop_calls == 1
    assert evidence.resource_ledger_count == 0


@pytest.mark.parametrize(
    (
        "events_overflow",
        "structural",
        "cancel",
        "deadline",
        "ready",
        "exit_code",
        "expected",
    ),
    [
        (True, True, 3, 2, 4, 37, "process_error"),
        (False, True, 3, 2, 4, 37, "process_error"),
        (False, False, 2, 2, 2, 0, "interrupted"),
        (False, False, 3, 2, 4, 0, "timeout"),
        (False, False, 5, 6, 4, 0, "clean"),
        (False, False, None, None, 4, 37, "provider_or_process_exit"),
    ],
)
def test_terminal_arbitration_is_a_single_frozen_precedence(
    events_overflow: bool,
    structural: bool,
    cancel: int | None,
    deadline: int | None,
    ready: int,
    exit_code: int,
    expected: str,
) -> None:
    assert (
        _classify_mechanical_outcome_v1(
            events_overflow=events_overflow,
            final_overflow=False,
            has_structural_failure=structural,
            cancel_observed_at_ns=cancel,
            active_deadline_ns=deadline,
            classification_ready_at_ns=ready,
            exit_code=exit_code,
        )
        == expected
    )


@pytest.mark.parametrize(
    ("cancel_offset_ns", "expected"),
    [(0, "interrupted"), (1, "clean")],
)
def test_completion_barrier_arbitrates_equal_or_late_cancel_at_kernel_seam(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cancel_offset_ns: int,
    expected: str,
) -> None:
    # Keep the synthetic completion tick strictly inside the unrelated timeout.
    plan = _plan(tmp_path, "success", timeout_seconds=60)
    capture = Path(plan.capture_directory)
    real_clock = child_process._monotonic_now_ns_v1
    ready_tick_ns = real_clock() + 10_000_000_000

    def completion_clock() -> int:
        return ready_tick_ns if capture.exists() else real_clock()

    monkeypatch.setattr(
        child_process,
        "_monotonic_now_ns_v1",
        completion_clock,
    )
    cancellation = _CaptureGatedCancellation(
        capture,
        ready_tick_ns + cancel_offset_ns,
    )

    evidence = run_codex_child_v1(plan, cancellation)

    assert evidence.capture_ready_monotonic_ns == ready_tick_ns
    assert evidence.mechanical_outcome == expected
    assert evidence.create_process_calls == 1
    assert evidence.stop_calls == 0
    assert evidence.resource_ledger_count == 0
    assert evidence.events.path.is_file()


def test_deadline_before_cancel_wins_at_public_kernel_seam(tmp_path: Path) -> None:
    deadline_ns = time.monotonic_ns() + 300_000_000
    plan = _plan(
        tmp_path,
        "hang",
        timeout_seconds=60,
        existing_shared_deadline_monotonic_ns=deadline_ns,
    )
    cancellation = _FixedCancellation(deadline_ns + 1)

    evidence = run_codex_child_v1(plan, cancellation)

    assert evidence.mechanical_outcome == "timeout"
    assert evidence.shared_deadline_monotonic_ns == deadline_ns
    assert evidence.create_process_calls == 1
    assert evidence.stop_calls == 1
    assert evidence.resource_ledger_count == 0


def test_lifecycle_failure_beats_cancel_and_deadline_at_public_kernel_seam(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_clock = child_process._monotonic_now_ns_v1
    before_ready_ns = real_clock()
    deadline_ns = before_ready_ns + 10
    cancel_ns = before_ready_ns + 15
    ready_ns = before_ready_ns + 20
    clock_calls = 0
    plan = _plan(
        tmp_path,
        "hang",
        timeout_seconds=60,
        existing_shared_deadline_monotonic_ns=deadline_ns,
    )
    cancellation = _FixedCancellation(cancel_ns)
    real_query = child_process._QUERY_INFORMATION_JOB_OBJECT
    injected = False

    def precedence_clock() -> int:
        nonlocal clock_calls
        clock_calls += 1
        return before_ready_ns if clock_calls <= 3 else ready_ns

    def query(*args):  # type: ignore[no-untyped-def]
        nonlocal injected
        if not injected:
            injected = True
            ctypes.set_last_error(31)
            return 0
        return int(real_query(*args))

    monkeypatch.setattr(
        child_process,
        "_monotonic_now_ns_v1",
        precedence_clock,
    )
    monkeypatch.setattr(child_process, "_QUERY_INFORMATION_JOB_OBJECT", query)
    evidence = run_codex_child_v1(plan, cancellation)

    assert injected
    assert evidence.mechanical_outcome == "process_error"
    assert evidence.create_process_calls == 1
    assert evidence.stop_calls == 1
    assert evidence.resource_ledger_count == 0
    assert evidence.capture_ready_monotonic_ns == ready_ns
    assert deadline_ns < cancel_ns <= evidence.capture_ready_monotonic_ns
    assert any("job_query" in fact for fact in evidence.lifecycle_facts)


def test_create_process_failure_is_still_an_attempt_with_empty_pair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path, "success")

    def fail_create(*_args: object) -> int:
        ctypes.set_last_error(2)
        return 0

    monkeypatch.setattr(child_process, "_CREATE_PROCESS", fail_create)

    evidence = run_codex_child_v1(plan, NeverCancelledV1())

    assert evidence.create_process_calls == 1
    assert evidence.exit_code is None
    assert evidence.mechanical_outcome == "process_error"
    assert evidence.events.byte_length == 0
    assert evidence.final_message is not None
    assert evidence.final_message.byte_length == 0
    assert evidence.resource_ledger_count == 0


def test_assignment_failure_terminates_the_never_resumed_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path, "success")

    def fail_assignment(_job: int, _process: int) -> int:
        ctypes.set_last_error(5)
        return 0

    monkeypatch.setattr(
        child_process,
        "_ASSIGN_PROCESS_TO_JOB_OBJECT",
        fail_assignment,
    )

    evidence = run_codex_child_v1(plan, NeverCancelledV1())

    assert evidence.provider_started_monotonic_ns is None
    assert evidence.mechanical_outcome == "process_error"
    assert evidence.resource_ledger_count == 0


def test_assignment_adapter_exception_terminates_the_never_resumed_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path, "success")
    real_terminate = child_process._TERMINATE_PROCESS
    terminate_calls = 0

    def raise_assignment(_job: int, _process: int) -> int:
        raise RuntimeError("injected AssignProcess exception")

    def observe_terminate(process: int, code: int) -> int:
        nonlocal terminate_calls
        terminate_calls += 1
        return int(real_terminate(process, code))

    monkeypatch.setattr(
        child_process,
        "_ASSIGN_PROCESS_TO_JOB_OBJECT",
        raise_assignment,
    )
    monkeypatch.setattr(child_process, "_TERMINATE_PROCESS", observe_terminate)

    evidence = run_codex_child_v1(plan, NeverCancelledV1())

    assert terminate_calls == 1
    assert evidence.provider_started_monotonic_ns is None
    assert evidence.mechanical_outcome == "process_error"
    assert evidence.resource_ledger_count == 0
    assert any(
        "assign_process_to_job_exception:RuntimeError" in fact
        for fact in evidence.lifecycle_facts
    )


def test_create_process_adapter_exception_after_success_contains_suspended_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path, "success")
    real_create = child_process._CREATE_PROCESS
    real_terminate = child_process._TERMINATE_PROCESS
    real_close = child_process._CLOSE_HANDLE
    production_termination = threading.Event()
    watchdog_finished = threading.Event()
    watchdog_fallback_used = threading.Event()
    raw_handles: set[int] = set()
    production_closed_handles: set[int] = set()
    terminate_calls = 0
    assign_calls = 0
    resume_calls = 0
    watchdog: threading.Thread | None = None

    def create_then_raise(*args):  # type: ignore[no-untyped-def]
        nonlocal watchdog
        assert int(real_create(*args))
        process_info_pointer = args[-1]
        raw_process = int(process_info_pointer.contents.hProcess or 0)
        raw_thread = int(process_info_pointer.contents.hThread or 0)
        raw_handles.update((raw_process, raw_thread))

        def terminate_orphan_safeguard() -> None:
            if not production_termination.wait(2):
                watchdog_fallback_used.set()
                real_terminate(raw_process, CODEX_JOB_STOP_EXIT_DWORD_V1)
                real_close(raw_thread)
                real_close(raw_process)
            watchdog_finished.set()

        watchdog = threading.Thread(
            target=terminate_orphan_safeguard,
            name="create-success-exception-watchdog",
            daemon=True,
        )
        watchdog.start()
        raise RuntimeError("injected after successful CreateProcessW")

    def observe_terminate(process: int, code: int) -> int:
        nonlocal terminate_calls
        terminate_calls += 1
        production_termination.set()
        return int(real_terminate(process, code))

    def observe_close(handle: int) -> int:
        value = int(handle)
        result = int(real_close(handle))
        if value in raw_handles:
            production_closed_handles.add(value)
        return result

    def observe_assign(_job: int, _process: int) -> int:
        nonlocal assign_calls
        assign_calls += 1
        return 0

    def observe_resume(_thread: int) -> int:
        nonlocal resume_calls
        resume_calls += 1
        return 0

    monkeypatch.setattr(child_process, "_CREATE_PROCESS", create_then_raise)
    monkeypatch.setattr(child_process, "_TERMINATE_PROCESS", observe_terminate)
    monkeypatch.setattr(child_process, "_CLOSE_HANDLE", observe_close)
    monkeypatch.setattr(child_process, "_ASSIGN_PROCESS_TO_JOB_OBJECT", observe_assign)
    monkeypatch.setattr(child_process, "_RESUME_THREAD", observe_resume)

    evidence = run_codex_child_v1(plan, NeverCancelledV1())
    assert watchdog is not None
    assert watchdog_finished.wait(5)
    watchdog.join(timeout=0)

    assert not watchdog_fallback_used.is_set()
    assert terminate_calls == 1
    assert assign_calls == 0
    assert resume_calls == 0
    assert production_closed_handles == raw_handles
    assert evidence.provider_started_monotonic_ns is None
    assert evidence.mechanical_outcome == "process_error"
    assert evidence.resource_ledger_count == 0
    assert any(
        "create_process_exception:RuntimeError" in fact
        for fact in evidence.lifecycle_facts
    )


@pytest.mark.parametrize("slot_label", ["root-process", "primary-thread"])
def test_handle_adoption_exception_is_contained_after_create(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    slot_label: str,
) -> None:
    plan = _plan(tmp_path, "success")
    real_create = child_process._CREATE_PROCESS
    real_activate = child_process._OwnedHandle.activate
    real_terminate = child_process._TERMINATE_PROCESS
    real_close = child_process._CLOSE_HANDLE
    real_assign = child_process._ASSIGN_PROCESS_TO_JOB_OBJECT
    real_resume = child_process._RESUME_THREAD
    injected = False
    terminate_calls = 0
    assign_calls = 0
    resume_calls = 0
    raw_handles: set[int] = set()
    production_closed_handles: set[int] = set()

    def observe_create(*args):  # type: ignore[no-untyped-def]
        result = int(real_create(*args))
        if result:
            process_info_pointer = args[-1]
            raw_handles.update(
                (
                    int(process_info_pointer.contents.hProcess or 0),
                    int(process_info_pointer.contents.hThread or 0),
                )
            )
        return result

    def fail_selected_activation(slot, value):  # type: ignore[no-untyped-def]
        nonlocal injected
        if slot.label == slot_label and not injected:
            injected = True
            raise RuntimeError(f"injected {slot_label} adoption failure")
        return real_activate(slot, value)

    def observe_terminate(process: int, code: int) -> int:
        nonlocal terminate_calls
        terminate_calls += 1
        return int(real_terminate(process, code))

    def observe_close(handle: int) -> int:
        value = int(handle)
        result = int(real_close(handle))
        if value in raw_handles:
            production_closed_handles.add(value)
        return result

    def observe_assign(job: int, process: int) -> int:
        nonlocal assign_calls
        assign_calls += 1
        return int(real_assign(job, process))

    def observe_resume(thread: int) -> int:
        nonlocal resume_calls
        resume_calls += 1
        return int(real_resume(thread))

    monkeypatch.setattr(child_process, "_CREATE_PROCESS", observe_create)
    monkeypatch.setattr(
        child_process._OwnedHandle,
        "activate",
        fail_selected_activation,
    )
    monkeypatch.setattr(child_process, "_TERMINATE_PROCESS", observe_terminate)
    monkeypatch.setattr(child_process, "_CLOSE_HANDLE", observe_close)
    monkeypatch.setattr(
        child_process,
        "_ASSIGN_PROCESS_TO_JOB_OBJECT",
        observe_assign,
    )
    monkeypatch.setattr(child_process, "_RESUME_THREAD", observe_resume)

    evidence = run_codex_child_v1(plan, NeverCancelledV1())

    assert injected
    assert len(raw_handles) == 2
    assert terminate_calls == 1
    assert assign_calls == 0
    assert resume_calls == 0
    assert production_closed_handles == raw_handles
    assert evidence.provider_started_monotonic_ns is None
    assert evidence.mechanical_outcome == "process_error"
    assert evidence.resource_ledger_count == 0
    assert any(
        "process_handle_adoption:RuntimeError" in fact
        for fact in evidence.lifecycle_facts
    )


@pytest.mark.parametrize("boundary", ["create", "assign"])
def test_cancel_crossing_a_kernel_launch_boundary_never_resumes_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
) -> None:
    plan = _plan(tmp_path, "success")
    cancellation = _LatchedCancellation()
    real_create = child_process._CREATE_PROCESS
    real_assign = child_process._ASSIGN_PROCESS_TO_JOB_OBJECT

    if boundary == "create":

        def create_then_cancel(*args):  # type: ignore[no-untyped-def]
            result = int(real_create(*args))
            cancellation.trigger()
            return result

        monkeypatch.setattr(child_process, "_CREATE_PROCESS", create_then_cancel)
    else:

        def assign_then_cancel(job: int, process: int) -> int:
            result = int(real_assign(job, process))
            cancellation.trigger()
            return result

        monkeypatch.setattr(
            child_process,
            "_ASSIGN_PROCESS_TO_JOB_OBJECT",
            assign_then_cancel,
        )

    def forbidden_resume(_thread: int) -> int:
        raise AssertionError("post-create cancellation must prevent ResumeThread")

    monkeypatch.setattr(child_process, "_RESUME_THREAD", forbidden_resume)

    evidence = run_codex_child_v1(plan, cancellation)

    assert evidence.provider_started_monotonic_ns is None
    assert evidence.mechanical_outcome == "interrupted"
    assert evidence.stop_calls == 1
    assert evidence.events.byte_length == 0
    assert evidence.resource_ledger_count == 0


def test_cancel_equal_to_shared_deadline_wins_at_suspended_root_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_clock = child_process._monotonic_now_ns_v1
    before_boundary_ns = real_clock()
    shared_deadline_ns = before_boundary_ns + 10
    crossed = False
    cancellation = _LatchedCancellation()
    plan = _plan(
        tmp_path,
        "success",
        existing_shared_deadline_monotonic_ns=shared_deadline_ns,
    )
    real_assign = child_process._ASSIGN_PROCESS_TO_JOB_OBJECT

    def boundary_clock() -> int:
        return shared_deadline_ns if crossed else before_boundary_ns

    def assign_then_latch(job: int, process: int) -> int:
        nonlocal crossed
        result = int(real_assign(job, process))
        cancellation.trigger(shared_deadline_ns)
        crossed = True
        return result

    def forbidden_resume(_thread: int) -> int:
        raise AssertionError("equal cancel/deadline must prevent ResumeThread")

    monkeypatch.setattr(
        child_process,
        "_monotonic_now_ns_v1",
        boundary_clock,
    )
    monkeypatch.setattr(
        child_process,
        "_ASSIGN_PROCESS_TO_JOB_OBJECT",
        assign_then_latch,
    )
    monkeypatch.setattr(child_process, "_RESUME_THREAD", forbidden_resume)

    evidence = run_codex_child_v1(plan, cancellation)

    assert crossed
    assert evidence.provider_started_monotonic_ns is None
    assert evidence.mechanical_outcome == "interrupted"
    assert evidence.shared_deadline_monotonic_ns == shared_deadline_ns
    assert evidence.create_process_calls == 1
    assert evidence.stop_calls == 1
    assert evidence.resource_ledger_count == 0


@pytest.mark.parametrize("resume_result", [0, 2, 0xFFFFFFFF])
def test_resume_anomaly_never_releases_the_prompt_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    resume_result: int,
) -> None:
    plan = _plan(tmp_path, "success")
    monkeypatch.setattr(
        child_process,
        "_RESUME_THREAD",
        lambda _thread: resume_result,
    )

    evidence = run_codex_child_v1(plan, NeverCancelledV1())

    assert evidence.provider_started_monotonic_ns is None
    assert evidence.events.byte_length == 0
    assert evidence.mechanical_outcome == "process_error"
    assert evidence.stop_calls == 1


def test_resume_adapter_exception_after_real_resume_stops_the_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path, "hang", timeout_seconds=60)
    real_assign = child_process._ASSIGN_PROCESS_TO_JOB_OBJECT
    real_resume = child_process._RESUME_THREAD
    real_terminate_job = child_process._TERMINATE_JOB_OBJECT
    production_stop = threading.Event()
    watchdog_finished = threading.Event()
    watchdog_fallback_used = threading.Event()
    assigned_job = 0
    terminate_calls = 0
    go_release_calls = 0
    watchdog: threading.Thread | None = None

    def observe_assign(job: int, process: int) -> int:
        nonlocal assigned_job
        result = int(real_assign(job, process))
        if result:
            assigned_job = int(job)
        return result

    def resume_then_raise(thread: int) -> int:
        nonlocal watchdog
        assert int(real_resume(thread)) == 1
        assert assigned_job not in {0, child_process._INVALID_HANDLE_VALUE}

        def terminate_orphan_safeguard() -> None:
            if not production_stop.wait(2):
                watchdog_fallback_used.set()
                real_terminate_job(
                    assigned_job,
                    CODEX_JOB_STOP_EXIT_DWORD_V1,
                )
            watchdog_finished.set()

        watchdog = threading.Thread(
            target=terminate_orphan_safeguard,
            name="resume-success-exception-watchdog",
            daemon=True,
        )
        watchdog.start()
        raise RuntimeError("injected after successful ResumeThread")

    def observe_terminate_job(job: int, code: int) -> int:
        nonlocal terminate_calls
        terminate_calls += 1
        production_stop.set()
        return int(real_terminate_job(job, code))

    monkeypatch.setattr(
        child_process,
        "_ASSIGN_PROCESS_TO_JOB_OBJECT",
        observe_assign,
    )
    monkeypatch.setattr(child_process, "_RESUME_THREAD", resume_then_raise)
    monkeypatch.setattr(
        child_process,
        "_TERMINATE_JOB_OBJECT",
        observe_terminate_job,
    )
    real_release_writer_go = child_process._release_writer_go

    def count_go_release(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal go_release_calls
        go_release_calls += 1
        return real_release_writer_go(*args, **kwargs)

    monkeypatch.setattr(child_process, "_release_writer_go", count_go_release)

    evidence = None
    escaped_error: BaseException | None = None
    try:
        evidence = run_codex_child_v1(plan, NeverCancelledV1())
    except BaseException as error:  # noqa: BLE001 - red-path orphan safeguard.
        escaped_error = error
    assert watchdog is not None
    assert watchdog_finished.wait(5)
    watchdog.join(timeout=0)

    assert escaped_error is None
    assert evidence is not None
    assert not watchdog_fallback_used.is_set()
    assert terminate_calls == 1
    assert go_release_calls == 0
    assert evidence.provider_started_monotonic_ns is None
    assert evidence.mechanical_outcome == "process_error"
    assert evidence.stop_calls == 1
    assert evidence.resource_ledger_count == 0
    assert any(
        "resume_thread_exception:RuntimeError" in fact
        for fact in evidence.lifecycle_facts
    )


def test_go_signal_failure_stops_and_settles_the_started_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path, "success")
    real_create_event = child_process._create_event
    real_set_event = child_process._SET_EVENT
    go_handle: int | None = None
    failed = False

    def observe_event(label, ledger):  # type: ignore[no-untyped-def]
        nonlocal go_handle
        event = real_create_event(label, ledger)
        if label == "go-event":
            go_handle = event.value
        return event

    def fail_go_once(handle: int) -> int:
        nonlocal failed
        if go_handle is not None and handle == go_handle and not failed:
            failed = True
            ctypes.set_last_error(6)
            return 0
        return int(real_set_event(handle))

    monkeypatch.setattr(child_process, "_create_event", observe_event)
    monkeypatch.setattr(child_process, "_SET_EVENT", fail_go_once)

    evidence = run_codex_child_v1(plan, NeverCancelledV1())

    assert failed
    assert evidence.mechanical_outcome == "process_error"
    assert evidence.stop_calls == 1
    assert evidence.resource_ledger_count == 0
    assert any("go_signal:" in fact for fact in evidence.lifecycle_facts)


def test_abort_signal_failure_uses_the_polled_fail_safe_and_settles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path, "success")
    real_create_event = child_process._create_event
    real_set_event = child_process._SET_EVENT
    abort_handle: int | None = None
    failed = False

    def observe_event(label, ledger):  # type: ignore[no-untyped-def]
        nonlocal abort_handle
        event = real_create_event(label, ledger)
        if label == "abort-event":
            abort_handle = event.value
        return event

    def fail_abort_once(handle: int) -> int:
        nonlocal failed
        if abort_handle is not None and handle == abort_handle and not failed:
            failed = True
            ctypes.set_last_error(6)
            return 0
        return int(real_set_event(handle))

    monkeypatch.setattr(child_process, "_create_event", observe_event)
    monkeypatch.setattr(child_process, "_SET_EVENT", fail_abort_once)
    monkeypatch.setattr(child_process, "_RESUME_THREAD", lambda _thread: 0)

    evidence = run_codex_child_v1(plan, NeverCancelledV1())

    assert failed
    assert evidence.mechanical_outcome == "process_error"
    assert evidence.stop_calls == 1
    assert evidence.resource_ledger_count == 0
    assert any("abort_signal:" in fact for fact in evidence.lifecycle_facts)


def test_abort_latch_stops_writes_after_go_when_abort_signal_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path, "no-read-hang", timeout_seconds=60)
    cancellation = _LatchedCancellation()
    real_create_event = child_process._create_event
    real_set_event = child_process._SET_EVENT
    abort_handle: int | None = None
    first_write_active = threading.Event()
    release_first_write = threading.Event()
    abort_failed = threading.Event()
    write_calls = 0

    def observe_event(label, ledger):  # type: ignore[no-untyped-def]
        nonlocal abort_handle
        event = real_create_event(label, ledger)
        if label == "abort-event":
            abort_handle = event.value
        return event

    def fail_abort_signal(handle: int) -> int:
        if abort_handle is not None and handle == abort_handle:
            abort_failed.set()
            ctypes.set_last_error(6)
            return 0
        return int(real_set_event(handle))

    def controlled_write(
        _handle: int,
        _buffer: object,
        _requested: int,
        written_pointer: object,
        _overlapped: object,
    ) -> int:
        nonlocal write_calls
        write_calls += 1
        written = ctypes.cast(
            written_pointer,
            ctypes.POINTER(ctypes.c_ulong),
        )
        if write_calls == 1:
            first_write_active.set()
            assert release_first_write.wait(5)
            written.contents.value = 1
            return 1
        written.contents.value = 0
        ctypes.set_last_error(109)
        return 0

    monkeypatch.setattr(child_process, "_create_event", observe_event)
    monkeypatch.setattr(child_process, "_SET_EVENT", fail_abort_signal)
    monkeypatch.setattr(child_process, "_WRITE_FILE", controlled_write)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            run_codex_child_v1,
            plan,
            cancellation,
        )
        assert first_write_active.wait(5)
        cancellation.trigger()
        assert abort_failed.wait(5)
        release_first_write.set()
        evidence = future.result(timeout=10)

    assert write_calls == 1
    assert evidence.stop_calls == 1
    assert evidence.mechanical_outcome == "process_error"
    assert evidence.resource_ledger_count == 0
    assert any("abort_signal:" in fact for fact in evidence.lifecycle_facts)


def test_writer_abort_wait_failure_is_a_structural_stop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path, "hang", timeout_seconds=60)
    real_create_event = child_process._create_event
    real_wait = child_process._WAIT_FOR_SINGLE_OBJECT
    abort_handle: int | None = None
    injected = False

    def observe_event(label, ledger):  # type: ignore[no-untyped-def]
        nonlocal abort_handle
        event = real_create_event(label, ledger)
        if label == "abort-event":
            abort_handle = event.value
        return event

    def fail_abort_wait(handle: int, milliseconds: int) -> int:
        nonlocal injected
        if (
            abort_handle is not None
            and handle == abort_handle
            and milliseconds == 0
            and not injected
        ):
            injected = True
            ctypes.set_last_error(6)
            return child_process._WAIT_FAILED
        return int(real_wait(handle, milliseconds))

    monkeypatch.setattr(child_process, "_create_event", observe_event)
    monkeypatch.setattr(child_process, "_WAIT_FOR_SINGLE_OBJECT", fail_abort_wait)

    evidence = run_codex_child_v1(plan, NeverCancelledV1())

    assert injected
    assert evidence.stop_calls == 1
    assert evidence.mechanical_outcome == "process_error"
    assert evidence.resource_ledger_count == 0
    assert any(
        "stdin_worker_failure:CodexChildWin32ErrorV1" in fact
        for fact in evidence.lifecycle_facts
    )


def test_precommit_setup_fault_returns_no_attempt_after_zero_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path, "success")

    def fail_job(_ledger: object) -> None:
        raise CodexChildWin32ErrorV1("injected job setup fault")

    monkeypatch.setattr(child_process, "_create_job", fail_job)

    result = run_codex_child_v1(plan, NeverCancelledV1())

    assert isinstance(result, PreAttemptRejectedV1)
    assert result.create_process_calls == 0
    assert result.resource_ledger_count == 0
    assert not Path(plan.staging_directory).exists()


def test_precommit_environment_allocation_fault_returns_no_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path, "success")

    def fail_environment(_block: str) -> None:
        raise MemoryError("injected environment allocation fault")

    monkeypatch.setattr(child_process, "_environment_array", fail_environment)

    result = run_codex_child_v1(plan, NeverCancelledV1())

    assert isinstance(result, PreAttemptRejectedV1)
    assert result.reason == "preparation_failed:MemoryError"
    assert result.create_process_calls == 0
    assert result.resource_ledger_count == 0
    assert not Path(plan.staging_directory).exists()


def test_precommit_second_pipe_fault_rolls_back_every_owned_resource(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path, "success")
    real_create_pipe_pair = child_process._create_pipe_pair

    def create_pipe_pair(*, prefix: str, ledger):  # type: ignore[no-untyped-def]
        if prefix == "stdout":
            raise CodexChildWin32ErrorV1("injected stdout pipe fault")
        return real_create_pipe_pair(prefix=prefix, ledger=ledger)

    monkeypatch.setattr(child_process, "_create_pipe_pair", create_pipe_pair)
    result = run_codex_child_v1(plan, NeverCancelledV1())

    assert isinstance(result, PreAttemptRejectedV1)
    assert result.reason == "preparation_failed:CodexChildWin32ErrorV1"
    assert result.create_process_calls == 0
    assert result.resource_ledger_count == 0
    assert not Path(plan.capture_directory).exists()
    assert not Path(plan.staging_directory).exists()


def test_precommit_ready_workers_fault_rolls_back_without_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path, "success")

    def fail_ready_snapshot(_prepared: object) -> None:
        raise RuntimeError("injected READY-to-commit fault")

    monkeypatch.setattr(
        child_process,
        "_snapshot_worker_facts",
        fail_ready_snapshot,
    )
    result = run_codex_child_v1(plan, NeverCancelledV1())

    assert isinstance(result, PreAttemptRejectedV1)
    assert result.reason == "preparation_failed:RuntimeError"
    assert result.create_process_calls == 0
    assert result.resource_ledger_count == 0
    assert not Path(plan.capture_directory).exists()
    assert not Path(plan.staging_directory).exists()


def test_stale_plan_cannot_launch_after_working_directory_content_changes(
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path, "success")
    (Path(plan.working_directory) / "AGENTS.md").write_text(
        "untrusted instruction",
        encoding="utf-8",
    )

    result = run_codex_child_v1(plan, NeverCancelledV1())

    assert isinstance(result, PreAttemptRejectedV1)
    assert result.reason == "preparation_failed:CodexChildWin32ErrorV1"
    assert result.create_process_calls == 0
    assert result.resource_ledger_count == 0
    assert not Path(plan.staging_directory).exists()


def test_mismatched_path_capability_close_failure_is_never_downgraded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path, "success")
    target = Path(plan.working_directory)
    (target / "unexpected.txt").write_text("drift", encoding="utf-8")
    real_close = windows_root.ValidatedDataRootV1.close
    injected = False

    def fail_target_close(capability):  # type: ignore[no-untyped-def]
        nonlocal injected
        canonical = capability.inspection.canonical_path
        real_close(capability)
        if (
            canonical is not None
            and os.path.normcase(canonical) == os.path.normcase(str(target))
            and not injected
        ):
            injected = True
            raise windows_root.DataRootLifecycleErrorV1(
                "injected mismatched capability close failure"
            )

    monkeypatch.setattr(
        windows_root.ValidatedDataRootV1,
        "close",
        fail_target_close,
    )

    with pytest.raises(
        CodexChildUnsafeHoldErrorV1,
        match="mismatched working capability close failed",
    ):
        run_codex_child_v1(plan, NeverCancelledV1())

    assert injected


@pytest.mark.parametrize(
    "directory_name",
    ["working", "temporary", "sqlite", "capture-parent", "codex-home"],
)
def test_stale_plan_cannot_launch_after_directory_generation_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    directory_name: str,
) -> None:
    plan, paths = _production_plan(tmp_path)
    target = paths[directory_name]
    with windows_root.open_validated_data_root_v1(str(target)) as opened:
        old_identity = opened.inspection.identity
    backup = target.with_name(f"{target.name}.old-generation")
    target.rename(backup)
    target.mkdir()
    with windows_root.open_validated_data_root_v1(str(target)) as opened:
        new_identity = opened.inspection.identity
    assert old_identity is not None
    assert new_identity is not None
    assert new_identity != old_identity

    def forbidden_create(*_args: object) -> int:
        raise AssertionError("CreateProcessW must not be reached")

    monkeypatch.setattr(child_process, "_CREATE_PROCESS", forbidden_create)
    try:
        result = run_production_codex_child_v1(plan, NeverCancelledV1())
    finally:
        backup.rmdir()

    assert isinstance(result, PreAttemptRejectedV1)
    assert result.reason == "preparation_failed:CodexChildWin32ErrorV1"
    assert result.create_process_calls == 0
    assert result.resource_ledger_count == 0
    assert not Path(plan.staging_directory).exists()


def test_stale_plan_cannot_launch_after_attempt_root_generation_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, paths = _production_plan(tmp_path)
    target = paths["attempt-root"]
    with windows_root.open_validated_data_root_v1(str(target)) as opened:
        old_identity = opened.inspection.identity
    backup = target.with_name(f"{target.name}.old-generation")
    target.rename(backup)
    target.mkdir()
    child_names = ("captures", "sqlite", "temporary", "working")
    for name in child_names:
        (backup / name).rename(target / name)
    with windows_root.open_validated_data_root_v1(str(target)) as opened:
        new_identity = opened.inspection.identity
    assert old_identity is not None
    assert new_identity is not None
    assert new_identity != old_identity

    def forbidden_create(*_args: object) -> int:
        raise AssertionError("CreateProcessW must not be reached")

    monkeypatch.setattr(child_process, "_CREATE_PROCESS", forbidden_create)
    try:
        result = run_production_codex_child_v1(plan, NeverCancelledV1())
    finally:
        for name in child_names:
            (target / name).rename(backup / name)
        target.rmdir()
        backup.rename(target)

    assert isinstance(result, PreAttemptRejectedV1)
    assert result.reason == "preparation_failed:CodexChildWin32ErrorV1"
    assert result.create_process_calls == 0
    assert result.resource_ledger_count == 0


@pytest.mark.parametrize(
    ("role", "directory_name"),
    [
        ("literature_reader_v1", "literature-authoritative"),
        ("knowledge_answerer_v1", "knowledge-authoritative"),
    ],
)
def test_stale_plan_cannot_launch_after_authoritative_root_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    role: str,
    directory_name: str,
) -> None:
    plan, paths = _production_plan(tmp_path, role=role)
    target = paths[directory_name]
    with windows_root.open_validated_data_root_v1(str(target)) as opened:
        old_identity = opened.inspection.identity
    backup = target.with_name(f"{target.name}.old-generation")
    target.rename(backup)
    target.mkdir()
    with windows_root.open_validated_data_root_v1(str(target)) as opened:
        new_identity = opened.inspection.identity
    assert old_identity is not None
    assert new_identity is not None
    assert new_identity != old_identity

    def forbidden_create(*_args: object) -> int:
        raise AssertionError("CreateProcessW must not be reached")

    monkeypatch.setattr(child_process, "_CREATE_PROCESS", forbidden_create)
    try:
        result = run_production_codex_child_v1(plan, NeverCancelledV1())
    finally:
        target.rmdir()
        backup.rename(target)

    assert isinstance(result, PreAttemptRejectedV1)
    assert result.reason == "preparation_failed:CodexChildWin32ErrorV1"
    assert result.create_process_calls == 0
    assert result.resource_ledger_count == 0


@pytest.mark.parametrize("target_name", ["schema", "executable"])
@pytest.mark.parametrize("mutation", ["in-place", "replacement"])
def test_stale_plan_cannot_launch_after_frozen_file_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target_name: str,
    mutation: str,
) -> None:
    plan, paths = _production_plan(tmp_path)
    target = paths[target_name]
    original = target.read_bytes()
    if mutation == "in-place":
        changed = bytearray(original)
        changed[0] ^= 1
        target.write_bytes(changed)
    else:
        replacement = target.with_name(f"{target.name}.replacement")
        replacement.write_bytes(original)
        os.replace(replacement, target)

    def forbidden_create(*_args: object) -> int:
        raise AssertionError("CreateProcessW must not be reached")

    monkeypatch.setattr(child_process, "_CREATE_PROCESS", forbidden_create)
    result = run_production_codex_child_v1(plan, NeverCancelledV1())

    assert isinstance(result, PreAttemptRejectedV1)
    assert result.reason == "preparation_failed:CodexChildWin32ErrorV1"
    assert result.create_process_calls == 0
    assert result.resource_ledger_count == 0
    assert not Path(plan.staging_directory).exists()


def test_committed_child_duplicate_close_failure_stops_before_unsafe_hold(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path, "hang", timeout_seconds=60)
    real_create_pipe_pair = child_process._create_pipe_pair
    real_close = child_process._CLOSE_HANDLE
    real_terminate = child_process._TERMINATE_JOB_OBJECT
    target_handle: int | None = None
    injected = False
    terminate_calls = 0

    def observe_pipe_pair(*, prefix: str, ledger):  # type: ignore[no-untyped-def]
        nonlocal target_handle
        pair = real_create_pipe_pair(prefix=prefix, ledger=ledger)
        if prefix == "stdin":
            target_handle = pair[0].value
        return pair

    def fail_close_after_kernel_close(handle: int) -> int:
        nonlocal injected
        if target_handle is not None and handle == target_handle and not injected:
            injected = True
            assert real_close(handle)
            ctypes.set_last_error(6)
            return 0
        return int(real_close(handle))

    def observe_terminate(job: int, code: int) -> int:
        nonlocal terminate_calls
        terminate_calls += 1
        return int(real_terminate(job, code))

    monkeypatch.setattr(child_process, "_create_pipe_pair", observe_pipe_pair)
    monkeypatch.setattr(child_process, "_CLOSE_HANDLE", fail_close_after_kernel_close)
    monkeypatch.setattr(child_process, "_TERMINATE_JOB_OBJECT", observe_terminate)

    with pytest.raises(
        CodexChildUnsafeHoldErrorV1,
        match="resource ownership is uncertain",
    ):
        run_codex_child_v1(plan, NeverCancelledV1())

    assert injected
    assert terminate_calls == 1


def test_committed_primary_thread_close_failure_stops_before_unsafe_hold(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path, "hang", timeout_seconds=60)
    real_create = child_process._CREATE_PROCESS
    real_close = child_process._CLOSE_HANDLE
    real_terminate = child_process._TERMINATE_JOB_OBJECT
    target_handle: int | None = None
    injected = False
    terminate_calls = 0

    def observe_create(*args):  # type: ignore[no-untyped-def]
        nonlocal target_handle
        result = int(real_create(*args))
        if result:
            target_handle = int(args[-1].contents.hThread)
        return result

    def fail_close_after_kernel_close(handle: int) -> int:
        nonlocal injected
        if target_handle is not None and handle == target_handle and not injected:
            injected = True
            assert real_close(handle)
            ctypes.set_last_error(6)
            return 0
        return int(real_close(handle))

    def observe_terminate(job: int, code: int) -> int:
        nonlocal terminate_calls
        terminate_calls += 1
        return int(real_terminate(job, code))

    monkeypatch.setattr(child_process, "_CREATE_PROCESS", observe_create)
    monkeypatch.setattr(child_process, "_CLOSE_HANDLE", fail_close_after_kernel_close)
    monkeypatch.setattr(child_process, "_TERMINATE_JOB_OBJECT", observe_terminate)

    with pytest.raises(
        CodexChildUnsafeHoldErrorV1,
        match="resource ownership is uncertain",
    ):
        run_codex_child_v1(plan, NeverCancelledV1())

    assert injected
    assert terminate_calls == 1


def test_path_guard_close_failure_never_resumes_the_suspended_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path, "hang", timeout_seconds=60)
    real_guard_close = child_process._OwnedPathGuard.close
    real_terminate = child_process._TERMINATE_JOB_OBJECT
    injected = False
    resume_calls = 0
    terminate_calls = 0

    def fail_schema_guard_close(guard):  # type: ignore[no-untyped-def]
        nonlocal injected
        real_guard_close(guard)
        if guard.label == "path-executable" and not injected:
            injected = True
            raise CodexChildUnsafeHoldErrorV1("injected path guard close failure")

    def forbidden_resume(_thread: int) -> int:
        nonlocal resume_calls
        resume_calls += 1
        return 1

    def observe_terminate(job: int, code: int) -> int:
        nonlocal terminate_calls
        terminate_calls += 1
        return int(real_terminate(job, code))

    monkeypatch.setattr(
        child_process._OwnedPathGuard,
        "close",
        fail_schema_guard_close,
    )
    monkeypatch.setattr(child_process, "_RESUME_THREAD", forbidden_resume)
    monkeypatch.setattr(child_process, "_TERMINATE_JOB_OBJECT", observe_terminate)

    with pytest.raises(
        CodexChildUnsafeHoldErrorV1,
        match="resource ownership is uncertain",
    ):
        run_codex_child_v1(plan, NeverCancelledV1())

    assert injected
    assert resume_calls == 0
    assert terminate_calls == 1


def test_events_fd_is_owned_before_inheritability_can_fail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path, "success")
    real_open = child_process.os.open
    real_set_inheritable = child_process.os.set_inheritable
    captured_fd: int | None = None

    def observe_open(path, flags, mode=0o777):  # type: ignore[no-untyped-def]
        nonlocal captured_fd
        fd = int(real_open(path, flags, mode))
        if str(path) == plan.events_staging_path:
            captured_fd = fd
        return fd

    def fail_events_inheritability(fd: int, inheritable: bool) -> None:
        if captured_fd is not None and fd == captured_fd:
            raise OSError("injected set_inheritable fault")
        real_set_inheritable(fd, inheritable)

    monkeypatch.setattr(child_process.os, "open", observe_open)
    monkeypatch.setattr(
        child_process.os,
        "set_inheritable",
        fail_events_inheritability,
    )

    result = run_codex_child_v1(plan, NeverCancelledV1())

    assert isinstance(result, PreAttemptRejectedV1)
    assert captured_fd is not None
    with pytest.raises(OSError):
        os.fstat(captured_fd)
    assert not Path(plan.staging_directory).exists()


def test_same_final_generation_cannot_clear_an_early_overflow_witness(
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path, "success")
    staging = Path(plan.staging_directory)
    staging.mkdir()
    assert plan.final_spool_path is not None
    final_path = Path(plan.final_spool_path)
    final_path.write_bytes(b"f" * (KNOWLEDGE_FINAL_CAPTURE_CAP_V1 + 1))
    ledger = child_process._ResourceLedger()
    witness = child_process._active_final_probe(
        str(final_path),
        cap=KNOWLEDGE_FINAL_CAPTURE_CAP_V1,
        ledger=ledger,
    )
    assert witness is not None
    assert ledger.count() == 0
    with final_path.open("r+b", buffering=0) as target:
        target.truncate(KNOWLEDGE_FINAL_CAPTURE_CAP_V1)

    with pytest.raises(
        CodexChildUnsafeHoldErrorV1,
        match="not independently confirmed",
    ):
        child_process._read_final_source(
            plan,
            ledger,
            early_overflow_identity=witness,
        )

    assert ledger.count() == 0


def test_active_final_probe_close_failure_stops_before_unsafe_hold(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(
        tmp_path,
        "final-overflow-hang",
        value=KNOWLEDGE_FINAL_CAPTURE_CAP_V1 + 1,
        timeout_seconds=60,
    )
    real_acquire = child_process._OwnedHandle.acquire
    real_close = child_process._CLOSE_HANDLE
    real_terminate = child_process._TERMINATE_JOB_OBJECT
    target_handle: int | None = None
    injected = False
    terminate_calls = 0

    def observe_acquire(value, label, ledger):  # type: ignore[no-untyped-def]
        nonlocal target_handle
        owned = real_acquire(value, label, ledger)
        if label == "active-final-probe":
            target_handle = owned.value
        return owned

    def fail_close_after_kernel_close(handle: int) -> int:
        nonlocal injected
        if target_handle is not None and handle == target_handle and not injected:
            injected = True
            assert real_close(handle)
            ctypes.set_last_error(6)
            return 0
        return int(real_close(handle))

    def observe_terminate(job: int, code: int) -> int:
        nonlocal terminate_calls
        terminate_calls += 1
        return int(real_terminate(job, code))

    monkeypatch.setattr(
        child_process._OwnedHandle,
        "acquire",
        observe_acquire,
    )
    monkeypatch.setattr(child_process, "_CLOSE_HANDLE", fail_close_after_kernel_close)
    monkeypatch.setattr(child_process, "_TERMINATE_JOB_OBJECT", observe_terminate)

    with pytest.raises(
        CodexChildUnsafeHoldErrorV1,
        match="resource ownership is uncertain",
    ):
        run_codex_child_v1(plan, NeverCancelledV1())

    assert injected
    assert terminate_calls == 1


def test_preexisting_staging_directory_is_never_claimed_or_cleaned(
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path, "success")
    staging = Path(plan.staging_directory)
    staging.mkdir()
    sentinel = staging / "user-owned.txt"
    sentinel.write_text("preserve me", encoding="utf-8")

    result = run_codex_child_v1(plan, NeverCancelledV1())

    assert isinstance(result, PreAttemptRejectedV1)
    assert result.reason == "preparation_failed:CodexChildWin32ErrorV1"
    assert result.create_process_calls == 0
    assert result.resource_ledger_count == 0
    assert sentinel.read_text(encoding="utf-8") == "preserve me"


def test_precommit_cleanup_refuses_an_unknown_staging_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path, "success")
    staging = Path(plan.staging_directory)
    sentinel = staging / "unknown-entry.txt"

    def add_unknown_entry_then_fail(_ledger: object) -> None:
        sentinel.write_text("do not delete", encoding="utf-8")
        raise CodexChildWin32ErrorV1("injected job setup fault")

    monkeypatch.setattr(child_process, "_create_job", add_unknown_entry_then_fail)

    with pytest.raises(
        CodexChildUnsafeHoldErrorV1,
        match="precommit preparation cleanup did not settle",
    ):
        run_codex_child_v1(plan, NeverCancelledV1())

    assert sentinel.read_text(encoding="utf-8") == "do not delete"
    assert staging.exists()


@pytest.mark.parametrize("capture_profile", ["knowledge", "literature"])
@pytest.mark.parametrize(
    "replacement_length",
    [5, KNOWLEDGE_FINAL_CAPTURE_CAP_V1 + 1],
)
def test_final_generation_replacement_after_witness_is_unsafe_hold(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capture_profile: str,
    replacement_length: int,
) -> None:
    plan = _plan(
        tmp_path,
        "final-overflow-hang",
        value=KNOWLEDGE_FINAL_CAPTURE_CAP_V1 + 1,
        timeout_seconds=60,
        capture_profile=capture_profile,
    )
    real_probe = child_process._active_final_probe
    replaced = False

    def replace_after_witness(  # type: ignore[no-untyped-def]
        path: str,
        *,
        cap: int,
        ledger,
    ):
        nonlocal replaced
        identity = real_probe(path, cap=cap, ledger=ledger)
        if identity is not None and not replaced:
            replacement = Path(path).with_name("replacement.tmp")
            replacement.write_bytes(b"r" * replacement_length)
            deadline = time.monotonic() + 1
            while True:
                try:
                    os.replace(replacement, path)
                    break
                except PermissionError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.005)
            replaced = True
        return identity

    monkeypatch.setattr(child_process, "_active_final_probe", replace_after_witness)

    with pytest.raises(
        CodexChildUnsafeHoldErrorV1,
        match="generation changed",
    ):
        run_codex_child_v1(plan, NeverCancelledV1())

    assert replaced
    assert Path(plan.staging_directory).exists()
    assert not Path(plan.capture_directory).exists()


def test_post_close_final_overflow_does_not_terminate_an_empty_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(
        tmp_path,
        "final-bytes",
        value=KNOWLEDGE_FINAL_CAPTURE_CAP_V1 + 1,
    )
    monkeypatch.setattr(
        child_process,
        "_active_final_probe",
        lambda _path, *, cap, ledger: None,
    )

    evidence = run_codex_child_v1(plan, NeverCancelledV1())

    assert evidence.final_message is not None
    assert evidence.final_message.overflow
    assert evidence.stop_calls == 0
    assert evidence.mechanical_outcome == "process_error"


def test_events_sink_fault_switches_to_drain_only_and_settles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path, "events-bytes", value=1_000_000)
    real_write = child_process._write_events_sink_all
    injected = False

    def fail_after_prefix(fd: int, payload: bytes) -> None:
        nonlocal injected
        if not injected:
            injected = True
            real_write(fd, payload[:17])
            raise OSError("injected sink failure")
        real_write(fd, payload)

    monkeypatch.setattr(
        child_process,
        "_write_events_sink_all",
        fail_after_prefix,
    )

    evidence = run_codex_child_v1(plan, NeverCancelledV1())

    assert injected
    assert evidence.events.byte_length == 17
    assert evidence.mechanical_outcome == "process_error"
    assert evidence.resource_ledger_count == 0


def test_events_sink_failure_is_published_before_eof_and_stops_a_hung_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path, "events-then-hang", timeout_seconds=60)
    failed = False

    def fail_first_sink_write(_fd: int, _payload: bytes) -> None:
        nonlocal failed
        failed = True
        raise OSError("injected sink failure")

    monkeypatch.setattr(
        child_process,
        "_write_events_sink_all",
        fail_first_sink_write,
    )

    evidence = run_codex_child_v1(plan, NeverCancelledV1())

    assert failed
    assert evidence.mechanical_outcome == "process_error"
    assert evidence.stop_calls == 1
    assert evidence.resource_ledger_count == 0
    assert any("events_sink_failure" in fact for fact in evidence.lifecycle_facts)


def test_overflow_never_installs_a_shorter_than_cap_events_prefix(
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path, "success")
    staging = Path(plan.staging_directory)
    staging.mkdir()
    persisted = KNOWLEDGE_EVENTS_CAPTURE_CAP_V1 - 1
    Path(plan.events_staging_path).write_bytes(b"e" * persisted)
    ledger = child_process._ResourceLedger()

    with pytest.raises(
        CodexChildUnsafeHoldErrorV1,
        match="exact cap prefix",
    ):
        child_process._install_captures(
            plan,
            ledger,
            events_overflow=True,
            final_capture=child_process._FinalCapture(False, False, None, None),
        )

    assert persisted == KNOWLEDGE_EVENTS_CAPTURE_CAP_V1 - 1
    assert Path(plan.events_staging_path).stat().st_size == persisted
    assert not Path(plan.capture_directory).exists()
    assert ledger.count() == 0


def test_failed_terminate_request_waits_for_natural_job_settlement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(
        tmp_path,
        "delayed-exit",
        value=250,
        timeout_seconds=0.05,
    )

    def reject_termination(_job: int, _code: int) -> int:
        ctypes.set_last_error(5)
        return 0

    monkeypatch.setattr(
        child_process,
        "_TERMINATE_JOB_OBJECT",
        reject_termination,
    )
    started = time.monotonic()

    evidence = run_codex_child_v1(plan, NeverCancelledV1())

    assert time.monotonic() - started >= 0.20
    assert evidence.stop_calls == 1
    assert evidence.mechanical_outcome == "process_error"
    assert any("terminate_job" in fact for fact in evidence.lifecycle_facts)


def test_successful_terminate_request_does_not_imply_job_is_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path, "hang", timeout_seconds=0.05)
    real_terminate = child_process._TERMINATE_JOB_OBJECT
    real_active = child_process._job_active_processes
    termination_accepted = False
    forced_nonempty_observations = 0

    def terminate(job: int, code: int) -> int:
        nonlocal termination_accepted
        result = int(real_terminate(job, code))
        termination_accepted = bool(result)
        return result

    def active(job):  # type: ignore[no-untyped-def]
        nonlocal forced_nonempty_observations
        actual = real_active(job)
        if termination_accepted and actual == 0 and forced_nonempty_observations < 3:
            forced_nonempty_observations += 1
            return 1
        return actual

    monkeypatch.setattr(child_process, "_TERMINATE_JOB_OBJECT", terminate)
    monkeypatch.setattr(child_process, "_job_active_processes", active)

    evidence = run_codex_child_v1(plan, NeverCancelledV1())

    assert termination_accepted
    assert forced_nonempty_observations == 3
    assert evidence.mechanical_outcome == "timeout"
    assert evidence.stop_calls == 1
    assert evidence.resource_ledger_count == 0


def test_one_shot_job_query_failure_stops_and_then_safely_settles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path, "hang", timeout_seconds=10)
    real_query = child_process._QUERY_INFORMATION_JOB_OBJECT
    injected = False

    def query(*args):  # type: ignore[no-untyped-def]
        nonlocal injected
        if not injected:
            injected = True
            ctypes.set_last_error(31)
            return 0
        return int(real_query(*args))

    monkeypatch.setattr(child_process, "_QUERY_INFORMATION_JOB_OBJECT", query)

    evidence = run_codex_child_v1(plan, NeverCancelledV1())

    assert injected
    assert evidence.mechanical_outcome == "process_error"
    assert evidence.stop_calls == 1
    assert evidence.resource_ledger_count == 0
    assert any("job_query" in fact for fact in evidence.lifecycle_facts)


def test_one_shot_wait_failure_stops_and_then_safely_settles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path, "hang", timeout_seconds=10)
    real_wait = child_process._WAIT_FOR_MULTIPLE_OBJECTS
    injected = False

    def wait_many(*args):  # type: ignore[no-untyped-def]
        nonlocal injected
        if not injected and not threading.current_thread().name.startswith(
            "gezhi-codex"
        ):
            injected = True
            ctypes.set_last_error(31)
            return 0xFFFFFFFF
        return int(real_wait(*args))

    monkeypatch.setattr(child_process, "_WAIT_FOR_MULTIPLE_OBJECTS", wait_many)

    evidence = run_codex_child_v1(plan, NeverCancelledV1())

    assert injected
    assert evidence.mechanical_outcome == "process_error"
    assert evidence.stop_calls == 1
    assert evidence.resource_ledger_count == 0
    assert any("wait:" in fact for fact in evidence.lifecycle_facts)


def test_uncertain_final_job_close_never_returns_terminal_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path, "success")
    real_create_job = child_process._create_job
    real_close = child_process._CLOSE_HANDLE
    job_value: int | None = None

    def create_job(ledger):  # type: ignore[no-untyped-def]
        nonlocal job_value
        job = real_create_job(ledger)
        job_value = job.value
        return job

    def close(handle: int) -> int:
        if job_value is not None and handle == job_value:
            assert real_close(handle)
            ctypes.set_last_error(6)
            return 0
        return int(real_close(handle))

    monkeypatch.setattr(child_process, "_create_job", create_job)
    monkeypatch.setattr(child_process, "_CLOSE_HANDLE", close)

    with pytest.raises(
        CodexChildUnsafeHoldErrorV1,
        match=r"CloseHandle\(job\)",
    ):
        run_codex_child_v1(plan, NeverCancelledV1())

    assert job_value is not None


def test_wake_reset_interleavings_do_not_lose_worker_facts() -> None:
    begin = threading.Barrier(2)
    published = threading.Barrier(2)
    current: list[SimpleNamespace] = []

    def publisher() -> None:
        for index in range(10_000):
            begin.wait()
            prepared = current[0]
            facts = prepared.facts
            wake = prepared.wake_event
            with facts.lock:
                facts.writer_failure = f"fact-{index}"
            assert child_process._SET_EVENT(wake.value)
            published.wait()

    worker = threading.Thread(target=publisher, daemon=False)
    worker.start()
    try:
        for index in range(10_000):
            ledger = child_process._ResourceLedger()
            wake = child_process._create_event(f"wake-race-{index}", ledger)
            facts = child_process._WorkerFacts(lock=threading.Lock())
            prepared = SimpleNamespace(facts=facts, wake_event=wake)
            current[:] = [prepared]
            with facts.lock:
                facts.writer_failure = None
                assert child_process._RESET_EVENT(wake.value)
            begin.wait()
            first = child_process._reset_wake(prepared)
            published.wait()
            if first.writer_failure != f"fact-{index}":
                assert child_process._WAIT_FOR_SINGLE_OBJECT(wake.value, 0) == 0
                second = child_process._reset_wake(prepared)
                assert second.writer_failure == f"fact-{index}"
            wake.close()
            assert ledger.count() == 0
    finally:
        worker.join()

    assert not worker.is_alive()


def test_public_attempt_observes_completed_workers_through_wake_reset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path, "success")
    real_reset = child_process._reset_wake
    completed_snapshots = 0

    def observe_reset(prepared):  # type: ignore[no-untyped-def]
        nonlocal completed_snapshots
        snapshot = real_reset(prepared)
        if snapshot.writer_done or snapshot.collector_done:
            completed_snapshots += 1
        return snapshot

    monkeypatch.setattr(child_process, "_reset_wake", observe_reset)
    evidence = run_codex_child_v1(plan, NeverCancelledV1())

    assert completed_snapshots >= 1
    assert evidence.mechanical_outcome == "clean"
    assert evidence.create_process_calls == 1
    assert evidence.stop_calls == 0
    assert evidence.resource_ledger_count == 0


def test_two_parallel_attempts_do_not_cross_inherit_or_cross_capture(
    tmp_path: Path,
) -> None:
    class SecurityAttributes(ctypes.Structure):
        _fields_ = (
            ("length", ctypes.c_ulong),
            ("descriptor", ctypes.c_void_p),
            ("inherit", ctypes.c_int),
        )

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_event = kernel32.CreateEventW
    create_event.argtypes = [
        ctypes.POINTER(SecurityAttributes),
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_wchar_p,
    ]
    create_event.restype = ctypes.c_void_p
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [ctypes.c_void_p]
    close_handle.restype = ctypes.c_int
    wait_for_single_object = kernel32.WaitForSingleObject
    wait_for_single_object.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    wait_for_single_object.restype = ctypes.c_ulong
    security = SecurityAttributes(ctypes.sizeof(SecurityAttributes), None, True)
    sentinels = tuple(
        int(create_event(ctypes.byref(security), True, False, None)) for _ in range(12)
    )
    assert all(sentinels)
    sentinel_arguments = tuple(
        item for handle in sentinels for item in ("--sentinel", str(handle))
    )
    plan_a = _plan(
        tmp_path / "a",
        "inspect-handles",
        prompt=b"alpha",
        extra_arguments=sentinel_arguments,
    )
    plan_b = _plan(
        tmp_path / "b",
        "inspect-handles",
        prompt=b"beta",
        extra_arguments=sentinel_arguments,
    )

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_a = executor.submit(
                run_codex_child_v1,
                plan_a,
                NeverCancelledV1(),
            )
            future_b = executor.submit(
                run_codex_child_v1,
                plan_b,
                NeverCancelledV1(),
            )
            evidence_a = future_a.result(timeout=10)
            evidence_b = future_b.result(timeout=10)
        assert all(wait_for_single_object(handle, 0) == 0x102 for handle in sentinels)
    finally:
        assert all(close_handle(handle) for handle in sentinels)

    receipt_a = json.loads(evidence_a.events.path.read_bytes())
    receipt_b = json.loads(evidence_b.events.path.read_bytes())
    assert receipt_a["prompt_sha256"] == hashlib.sha256(b"alpha").hexdigest()
    assert receipt_b["prompt_sha256"] == hashlib.sha256(b"beta").hexdigest()
    for receipt in (receipt_a, receipt_b):
        assert len(receipt["sentinels"]) == len(sentinels)
        assert all(
            set(result) == {"accessible", "set_succeeded", "set_error"}
            for result in receipt["sentinels"]
        )
    assert evidence_a.events.path != evidence_b.events.path
    for evidence in (evidence_a, evidence_b):
        assert evidence.create_process_calls == 1
        assert evidence.stop_calls == 0
        assert evidence.resource_ledger_count == 0


def test_create_process_receives_a_mutable_copy_without_changing_audit_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path, "success")
    original_argv = plan.argv
    original_quoted = plan.quoted_command_line
    original_hash = plan.command_line_sha256
    real_create = child_process._CREATE_PROCESS
    mutated = False

    def mutate_then_create(
        application,
        command_line,
        *arguments,  # type: ignore[no-untyped-def]
    ) -> int:
        nonlocal mutated
        final_index = len(command_line.value) - 1
        original = command_line[final_index]
        command_line[final_index] = "X"
        mutated = command_line[final_index] == "X"
        command_line[final_index] = original
        return int(real_create(application, command_line, *arguments))

    monkeypatch.setattr(child_process, "_CREATE_PROCESS", mutate_then_create)

    evidence = run_codex_child_v1(plan, NeverCancelledV1())

    assert mutated
    assert evidence.mechanical_outcome == "clean"
    assert plan.argv == original_argv
    assert plan.quoted_command_line == original_quoted
    assert plan.command_line_sha256 == original_hash


def test_writefile_progress_sequence_preserves_the_exact_remaining_suffix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompt = b"p" * 200_000
    plan = _plan(tmp_path, "success", prompt=prompt)
    real_write = child_process._WRITE_FILE
    writer_calls = 0
    observations: list[tuple[int, int]] = []

    def write(handle, buffer, requested, written, overlapped):  # type: ignore[no-untyped-def]
        nonlocal writer_calls
        if threading.current_thread().name.startswith("gezhi-codex-stdin"):
            writer_calls += 1
            if writer_calls == 1:
                result = int(real_write(handle, buffer, requested, written, overlapped))
                count = ctypes.cast(
                    written,
                    ctypes.POINTER(ctypes.c_ulong),
                ).contents.value
                observations.append((requested, int(count)))
                return result
            if writer_calls == 2:
                result = int(real_write(handle, buffer, 7, written, overlapped))
                count = ctypes.cast(
                    written,
                    ctypes.POINTER(ctypes.c_ulong),
                ).contents.value
                observations.append((requested, int(count)))
                return result
        return int(real_write(handle, buffer, requested, written, overlapped))

    monkeypatch.setattr(child_process, "_WRITE_FILE", write)

    evidence = run_codex_child_v1(plan, NeverCancelledV1())

    receipt = json.loads(evidence.events.path.read_bytes())
    assert observations[0][1] == observations[0][0]
    assert 0 < observations[1][1] < observations[1][0]
    assert writer_calls >= 3
    assert receipt["sha256"] == hashlib.sha256(prompt).hexdigest()
    assert receipt["length"] == len(prompt)
    assert evidence.mechanical_outcome == "clean"
    assert evidence.create_process_calls == 1
    assert evidence.stop_calls == 0
    assert evidence.resource_ledger_count == 0


@pytest.mark.parametrize("observation", ["zero", "over", "broken", "no-data", "other"])
def test_terminal_writefile_observation_fails_once_without_another_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    observation: str,
) -> None:
    plan = _plan(tmp_path, "success", prompt=b"p" * 200_000)
    real_write = child_process._WRITE_FILE
    injected = False
    later_writer_calls = 0

    def write(handle, buffer, requested, written, overlapped):  # type: ignore[no-untyped-def]
        nonlocal injected, later_writer_calls
        if threading.current_thread().name.startswith("gezhi-codex-stdin"):
            if injected:
                later_writer_calls += 1
                return int(real_write(handle, buffer, requested, written, overlapped))
            injected = True
            target = ctypes.cast(written, ctypes.POINTER(ctypes.c_ulong))
            if observation == "zero":
                target.contents.value = 0
                return 1
            if observation == "over":
                target.contents.value = requested + 1
                return 1
            ctypes.set_last_error(
                109
                if observation == "broken"
                else 232
                if observation == "no-data"
                else 31
            )
            target.contents.value = 0
            return 0
        return int(real_write(handle, buffer, requested, written, overlapped))

    monkeypatch.setattr(child_process, "_WRITE_FILE", write)

    evidence = run_codex_child_v1(plan, NeverCancelledV1())

    assert injected
    assert later_writer_calls == 0
    assert evidence.mechanical_outcome == "process_error"
    assert evidence.create_process_calls == 1
    assert evidence.stop_calls == 1
    assert evidence.resource_ledger_count == 0
    assert any("stdin_delivery_failure" in fact for fact in evidence.lifecycle_facts)


def test_readfile_progress_sequence_reaches_real_broken_pipe_eof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(tmp_path, "events-bytes", value=200_000)
    real_read = child_process._READ_FILE
    collector_calls = 0
    observed_short = 0
    observed_positive = False
    observed_broken_pipe = False

    def read(handle, buffer, requested, count, overlapped):  # type: ignore[no-untyped-def]
        nonlocal collector_calls, observed_short, observed_positive
        nonlocal observed_broken_pipe
        if threading.current_thread().name.startswith("gezhi-codex-stdout"):
            collector_calls += 1
            target = ctypes.cast(count, ctypes.POINTER(ctypes.c_ulong))
            if collector_calls == 1:
                target.contents.value = 0
                return 1
            if collector_calls == 2:
                result = int(real_read(handle, buffer, 7, count, overlapped))
                observed_short = int(target.contents.value)
                return result
            result = int(real_read(handle, buffer, requested, count, overlapped))
            observed = int(target.contents.value)
            if result and observed > 0:
                observed_positive = True
            if not result and ctypes.get_last_error() == 109:
                observed_broken_pipe = True
            return result
        return int(real_read(handle, buffer, requested, count, overlapped))

    monkeypatch.setattr(child_process, "_READ_FILE", read)

    evidence = run_codex_child_v1(plan, NeverCancelledV1())

    assert collector_calls >= 4
    assert observed_short == 7
    assert observed_positive
    assert observed_broken_pipe
    assert evidence.events.byte_length == 200_000
    assert evidence.mechanical_outcome == "clean"
    assert evidence.create_process_calls == 1
    assert evidence.stop_calls == 0
    assert evidence.resource_ledger_count == 0


@pytest.mark.parametrize("observation", ["over", "other"])
def test_terminal_readfile_observation_latches_once_then_drains_to_real_eof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    observation: str,
) -> None:
    plan = _plan(tmp_path, "events-bytes", value=200_000)
    real_read = child_process._READ_FILE
    injected = 0
    observed_broken_pipe = False
    real_progress_after_fault = False

    def read(handle, buffer, requested, count, overlapped):  # type: ignore[no-untyped-def]
        nonlocal injected, observed_broken_pipe, real_progress_after_fault
        if threading.current_thread().name.startswith("gezhi-codex-stdout"):
            target = ctypes.cast(count, ctypes.POINTER(ctypes.c_ulong))
            if injected == 0:
                injected = 1
                if observation == "over":
                    target.contents.value = requested + 1
                    return 1
                ctypes.set_last_error(31)
                target.contents.value = 0
                return 0
            result = int(real_read(handle, buffer, requested, count, overlapped))
            observed = int(target.contents.value)
            if result and observed > 0:
                real_progress_after_fault = True
            if not result and ctypes.get_last_error() == 109:
                observed_broken_pipe = True
            return result
        return int(real_read(handle, buffer, requested, count, overlapped))

    monkeypatch.setattr(child_process, "_READ_FILE", read)
    evidence = run_codex_child_v1(plan, NeverCancelledV1())

    assert injected == 1
    assert real_progress_after_fault or observed_broken_pipe
    assert observed_broken_pipe
    assert evidence.mechanical_outcome == "process_error"
    assert evidence.create_process_calls == 1
    assert evidence.stop_calls == 1
    assert evidence.resource_ledger_count == 0
    assert (
        sum("stdout_collector_failure" in fact for fact in evidence.lifecycle_facts)
        == 1
    )
