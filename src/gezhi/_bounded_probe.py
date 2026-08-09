from __future__ import annotations

import ctypes
import math
import subprocess
import sys
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import BinaryIO, cast

_CREATE_SUSPENDED = 0x00000004
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
_JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION_CLASS = 1
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_SETTLEMENT_SECONDS = 5.0
_READER_SETTLEMENT_SECONDS = 2.0
_WAIT_SLICE_SECONDS = 0.01


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = (
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", ctypes.c_ulong),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_ulong),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_ulong),
        ("SchedulingClass", ctypes.c_ulong),
    )


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = (
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    )


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = (
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    )


class _JOBOBJECT_BASIC_ACCOUNTING_INFORMATION(ctypes.Structure):
    _fields_ = (
        ("TotalUserTime", ctypes.c_longlong),
        ("TotalKernelTime", ctypes.c_longlong),
        ("ThisPeriodTotalUserTime", ctypes.c_longlong),
        ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
        ("TotalPageFaultCount", ctypes.c_ulong),
        ("TotalProcesses", ctypes.c_ulong),
        ("ActiveProcesses", ctypes.c_ulong),
        ("TotalTerminatedProcesses", ctypes.c_ulong),
    )


_KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
_NTDLL = ctypes.WinDLL("ntdll", use_last_error=True)
_CREATE_JOB_OBJECT = _KERNEL32.CreateJobObjectW
_CREATE_JOB_OBJECT.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
_CREATE_JOB_OBJECT.restype = ctypes.c_void_p
_SET_INFORMATION_JOB_OBJECT = _KERNEL32.SetInformationJobObject
_SET_INFORMATION_JOB_OBJECT.argtypes = [
    ctypes.c_void_p,
    ctypes.c_int,
    ctypes.c_void_p,
    ctypes.c_ulong,
]
_SET_INFORMATION_JOB_OBJECT.restype = ctypes.c_int
_ASSIGN_PROCESS_TO_JOB_OBJECT = _KERNEL32.AssignProcessToJobObject
_ASSIGN_PROCESS_TO_JOB_OBJECT.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_ASSIGN_PROCESS_TO_JOB_OBJECT.restype = ctypes.c_int
_TERMINATE_JOB_OBJECT = _KERNEL32.TerminateJobObject
_TERMINATE_JOB_OBJECT.argtypes = [ctypes.c_void_p, ctypes.c_uint]
_TERMINATE_JOB_OBJECT.restype = ctypes.c_int
_QUERY_INFORMATION_JOB_OBJECT = _KERNEL32.QueryInformationJobObject
_QUERY_INFORMATION_JOB_OBJECT.argtypes = [
    ctypes.c_void_p,
    ctypes.c_int,
    ctypes.c_void_p,
    ctypes.c_ulong,
    ctypes.c_void_p,
]
_QUERY_INFORMATION_JOB_OBJECT.restype = ctypes.c_int
_CLOSE_HANDLE = _KERNEL32.CloseHandle
_CLOSE_HANDLE.argtypes = [ctypes.c_void_p]
_CLOSE_HANDLE.restype = ctypes.c_int
_NT_RESUME_PROCESS = _NTDLL.NtResumeProcess
_NT_RESUME_PROCESS.argtypes = [ctypes.c_void_p]
_NT_RESUME_PROCESS.restype = ctypes.c_long


class ProbeOutputLimitExceeded(RuntimeError):
    """A read-only capability probe exceeded its capture budget."""


class ProbeLifecycleError(RuntimeError):
    """The probe could not prove that its Windows resources were settled."""


class ProbeUnavailableError(RuntimeError):
    """The requested probe executable could not be launched."""


@dataclass(frozen=True, slots=True)
class BoundedProbeResultV1:
    returncode: int
    stdout: bytes
    stderr: bytes


def _win32_error(message: str) -> ProbeLifecycleError:
    code = ctypes.get_last_error()
    return ProbeLifecycleError(f"{message} (Win32 {code})")


def _create_kill_on_close_job() -> int:
    handle = _CREATE_JOB_OBJECT(None, None)
    if handle in {None, 0}:
        raise _win32_error("CreateJobObjectW failed")
    job = int(handle)
    limits = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not _SET_INFORMATION_JOB_OBJECT(
        job,
        _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
        ctypes.byref(limits),
        ctypes.sizeof(limits),
    ):
        error = _win32_error("SetInformationJobObject failed")
        if not _CLOSE_HANDLE(job):
            raise _win32_error(
                "SetInformationJobObject and CloseHandle(Job) failed"
            ) from error
        raise error
    return job


def _process_handle(process: subprocess.Popen[bytes]) -> int:
    handle = getattr(process, "_handle", None)
    if handle is None:
        raise RuntimeError("probe process handle is unavailable")
    return int(handle)


def _job_active_processes(job: int) -> int:
    accounting = _JOBOBJECT_BASIC_ACCOUNTING_INFORMATION()
    if not _QUERY_INFORMATION_JOB_OBJECT(
        job,
        _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION_CLASS,
        ctypes.byref(accounting),
        ctypes.sizeof(accounting),
        None,
    ):
        raise _win32_error("QueryInformationJobObject failed")
    return int(accounting.ActiveProcesses)


def _remaining_seconds(deadline: float) -> float:
    return max(0.0, deadline - time.monotonic())


def _wait_for_job_empty(job: int, deadline: float) -> bool:
    while _job_active_processes(job) != 0:
        remaining = _remaining_seconds(deadline)
        if remaining <= 0:
            return False
        time.sleep(min(0.01, remaining))
    return True


def _terminate_job_best_effort(job: int) -> None:
    try:
        if _job_active_processes(job) != 0:
            _TERMINATE_JOB_OBJECT(job, 1)
    except ProbeLifecycleError:
        pass


def _close_stream_best_effort(stream: BinaryIO) -> None:
    try:
        stream.close()
    except Exception:  # noqa: BLE001, S110 - final rollback is best effort.
        pass


def _close_stream(stream: BinaryIO) -> None:
    try:
        stream.close()
    except Exception as error:
        raise ProbeLifecycleError("probe pipe close failed") from error


def _join_readers(
    threads: tuple[threading.Thread, threading.Thread],
    streams: tuple[BinaryIO, BinaryIO],
) -> None:
    deadline = time.monotonic() + _READER_SETTLEMENT_SECONDS
    for thread in threads:
        thread.join(_remaining_seconds(deadline))
    if any(thread.is_alive() for thread in threads):
        for stream in streams:
            _close_stream_best_effort(stream)
        second_deadline = time.monotonic() + 1.0
        for thread in threads:
            thread.join(_remaining_seconds(second_deadline))
    if any(thread.is_alive() for thread in threads):
        raise ProbeLifecycleError("probe pipe readers did not settle")


def _wait_for_probe_completion(
    process: subprocess.Popen[bytes],
    job: int,
    deadline: float,
    stop_signals: tuple[threading.Event, ...],
) -> bool:
    root_exited = False
    while True:
        if any(signal.is_set() for signal in stop_signals):
            return False
        remaining = _remaining_seconds(deadline)
        if remaining <= 0:
            return False
        if not root_exited:
            try:
                process.wait(timeout=min(_WAIT_SLICE_SECONDS, remaining))
            except subprocess.TimeoutExpired:
                continue
            root_exited = True
        if _job_active_processes(job) == 0:
            return True
        time.sleep(min(_WAIT_SLICE_SECONDS, _remaining_seconds(deadline)))


def _settle_process_tree(
    process: subprocess.Popen[bytes],
    job: int,
) -> None:
    deadline = time.monotonic() + _SETTLEMENT_SECONDS
    try:
        process.wait(timeout=_remaining_seconds(deadline))
    except subprocess.TimeoutExpired as error:
        raise ProbeLifecycleError("probe root process did not settle") from error
    if not _wait_for_job_empty(job, deadline):
        raise ProbeLifecycleError("probe process Job did not settle")


def _settle_unassigned_process(process: subprocess.Popen[bytes]) -> None:
    try:
        if process.poll() is None:
            process.kill()
    except OSError:
        pass
    try:
        process.wait(timeout=_SETTLEMENT_SECONDS)
    except subprocess.TimeoutExpired as error:
        raise ProbeLifecycleError("unassigned probe root did not settle") from error


def run_bounded_probe_v1(
    command: Sequence[str],
    *,
    environment: Mapping[str, str] | None = None,
    timeout_seconds: float,
    output_limit: int,
    creation_flags: int = 0,
) -> BoundedProbeResultV1:
    frozen_command = tuple(command)
    if not frozen_command or any(type(item) is not str for item in frozen_command):
        raise TypeError("probe command is invalid")
    if (
        type(timeout_seconds) not in {int, float}
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
    ):
        raise ValueError("probe timeout is invalid")
    if type(output_limit) is not int or output_limit < 0:
        raise ValueError("probe output limit is invalid")

    deadline = time.monotonic() + timeout_seconds
    job = _create_kill_on_close_job()
    process: subprocess.Popen[bytes] | None = None
    stdout_stream: BinaryIO | None = None
    stderr_stream: BinaryIO | None = None
    readers: tuple[threading.Thread, threading.Thread] | None = None
    assigned_to_job = False
    tree_settled = False
    try:
        try:
            process = subprocess.Popen(
                frozen_command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=None if environment is None else dict(environment),
                creationflags=creation_flags | _CREATE_SUSPENDED,
            )
        except OSError as error:
            raise ProbeUnavailableError("probe executable is unavailable") from error
        stdout_stream = cast(BinaryIO | None, process.stdout)
        stderr_stream = cast(BinaryIO | None, process.stderr)
        if stdout_stream is None or stderr_stream is None:
            raise RuntimeError("probe pipes are unavailable")
        process_handle = _process_handle(process)
        if not _ASSIGN_PROCESS_TO_JOB_OBJECT(job, process_handle):
            raise _win32_error("AssignProcessToJobObject failed")
        assigned_to_job = True

        lock = threading.Lock()
        overflow = threading.Event()
        captured = 0
        reader_failed = threading.Event()
        reader_failures: list[BaseException | None] = [None, None]
        stdout_buffer = bytearray()
        stderr_buffer = bytearray()

        def drain(index: int, stream: BinaryIO, destination: bytearray) -> None:
            nonlocal captured
            try:
                while True:
                    chunk = stream.read(1_024)
                    if type(chunk) is not bytes:
                        raise TypeError("probe pipe returned a non-bytes value")
                    if not chunk:
                        return
                    with lock:
                        remaining = max(0, output_limit + 1 - captured)
                        retained = chunk[:remaining]
                        destination.extend(retained)
                        captured += len(retained)
                        exceeded = len(chunk) > remaining or captured > output_limit
                        if exceeded:
                            overflow.set()
                    if overflow.is_set():
                        return
            except BaseException as error:  # noqa: BLE001 - cross thread boundary.
                with lock:
                    reader_failures[index] = error
                reader_failed.set()

        readers = (
            threading.Thread(
                target=drain,
                args=(0, stdout_stream, stdout_buffer),
                daemon=True,
            ),
            threading.Thread(
                target=drain,
                args=(1, stderr_stream, stderr_buffer),
                daemon=True,
            ),
        )
        for reader in readers:
            reader.start()
        if _NT_RESUME_PROCESS(process_handle) < 0:
            raise _win32_error("NtResumeProcess failed")

        completed = _wait_for_probe_completion(
            process,
            job,
            deadline,
            (overflow, reader_failed),
        )
        timed_out = not completed and not overflow.is_set() and not reader_failed.is_set()
        if not completed:
            _terminate_job_best_effort(job)
        _settle_process_tree(process, job)
        tree_settled = True
        _join_readers(readers, (stdout_stream, stderr_stream))
        readers = None
        _close_stream(stdout_stream)
        _close_stream(stderr_stream)
        stdout_stream = None
        stderr_stream = None

        if timed_out:
            raise subprocess.TimeoutExpired(frozen_command, timeout_seconds)
        reader_failure = next(
            (failure for failure in reader_failures if failure is not None),
            None,
        )
        if reader_failure is not None:
            raise ProbeLifecycleError("probe pipe read failed") from reader_failure
        if overflow.is_set():
            raise ProbeOutputLimitExceeded("probe output exceeded its byte limit")
        returncode = process.returncode
        if type(returncode) is not int:
            raise RuntimeError("probe return code is unavailable")
        return BoundedProbeResultV1(
            returncode=returncode,
            stdout=bytes(stdout_buffer),
            stderr=bytes(stderr_buffer),
        )
    except BaseException as primary_error:
        cleanup_failures: list[Exception] = []
        if process is not None and not tree_settled:
            try:
                if assigned_to_job:
                    _terminate_job_best_effort(job)
                    _settle_process_tree(process, job)
                else:
                    _settle_unassigned_process(process)
            except Exception as cleanup_error:  # noqa: BLE001 - classify cleanup.
                cleanup_failures.append(cleanup_error)
        if readers is not None and stdout_stream is not None and stderr_stream is not None:
            try:
                _join_readers(readers, (stdout_stream, stderr_stream))
            except Exception as cleanup_error:  # noqa: BLE001 - classify cleanup.
                cleanup_failures.append(cleanup_error)
        if isinstance(primary_error, (KeyboardInterrupt, SystemExit, GeneratorExit)):
            for _cleanup_failure in cleanup_failures:
                primary_error.add_note(
                    "probe cleanup could not prove complete resource settlement"
                )
            raise
        if cleanup_failures:
            cleanup_failure = cleanup_failures[0]
            if isinstance(cleanup_failure, ProbeLifecycleError):
                raise cleanup_failure from primary_error
            raise ProbeLifecycleError("probe cleanup failed") from cleanup_failure
        raise
    finally:
        if stdout_stream is not None:
            _close_stream_best_effort(stdout_stream)
        if stderr_stream is not None:
            _close_stream_best_effort(stderr_stream)
        if not _CLOSE_HANDLE(job):
            current_error = sys.exception()
            if not isinstance(
                current_error,
                (KeyboardInterrupt, SystemExit, GeneratorExit),
            ):
                raise _win32_error("CloseHandle(Job) failed")
