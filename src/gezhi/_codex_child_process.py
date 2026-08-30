from __future__ import annotations

import ctypes
import hashlib
import ntpath
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol, TypeAlias

from gezhi._codex_role_plan import (
    CaptureProfileV1,
    FrozenCodexLaunchPlanV1,
    _require_codex_launch_plan_v1,
)
from gezhi._windows_data_root import (
    DataRootLifecycleErrorV1,
    DataRootOpenErrorV1,
    ValidatedDataRootV1,
    ValidatedFileV1,
    open_validated_data_root_v1,
    open_validated_local_file_v1,
)

CODEX_PIPE_BUFFER_HINT_BYTES_V1 = 65_536
CODEX_PIPE_IO_CHUNK_BYTES_V1 = 65_536
CODEX_CHILD_POLL_QUANTUM_MS_V1 = 50
CODEX_JOB_STOP_EXIT_DWORD_V1 = 0x475A0001
KNOWLEDGE_EVENTS_CAPTURE_CAP_V1 = 16_777_216
KNOWLEDGE_FINAL_CAPTURE_CAP_V1 = 1_048_576
LITERATURE_EVENTS_CAPTURE_CAP_V1 = 16_777_216
LITERATURE_FINAL_CAPTURE_CAP_V1 = 1_048_576


def _events_capture_cap_v1(capture_profile: CaptureProfileV1) -> int:
    if capture_profile == "knowledge":
        return KNOWLEDGE_EVENTS_CAPTURE_CAP_V1
    return LITERATURE_EVENTS_CAPTURE_CAP_V1


def _final_capture_cap_v1(capture_profile: CaptureProfileV1) -> int:
    if capture_profile == "knowledge":
        return KNOWLEDGE_FINAL_CAPTURE_CAP_V1
    return LITERATURE_FINAL_CAPTURE_CAP_V1


MechanicalOutcomeV1: TypeAlias = Literal[
    "clean",
    "provider_or_process_exit",
    "process_error",
    "timeout",
    "interrupted",
]

_CREATE_SUSPENDED = 0x00000004
_CREATE_UNICODE_ENVIRONMENT = 0x00000400
_EXTENDED_STARTUPINFO_PRESENT = 0x00080000
_CREATE_NO_WINDOW = 0x08000000
_CREATION_FLAGS = (
    _CREATE_SUSPENDED
    | _CREATE_UNICODE_ENVIRONMENT
    | _EXTENDED_STARTUPINFO_PRESENT
    | _CREATE_NO_WINDOW
)
_STARTF_USESTDHANDLES = 0x00000100
_HANDLE_FLAG_INHERIT = 0x00000001
_PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x00020002
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
_JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION_CLASS = 1
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_WAIT_OBJECT_0 = 0x00000000
_WAIT_TIMEOUT = 0x00000102
_WAIT_FAILED = 0xFFFFFFFF
_INFINITE = 0xFFFFFFFF
_ERROR_FILE_NOT_FOUND = 2
_ERROR_PATH_NOT_FOUND = 3
_ERROR_ACCESS_DENIED = 5
_ERROR_BROKEN_PIPE = 109
_ERROR_INSUFFICIENT_BUFFER = 122
_ERROR_SHARING_VIOLATION = 32
_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_DELETE = 0x00010000
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_FILE_SHARE_DELETE = 0x00000004
_OPEN_EXISTING = 3
_FILE_ATTRIBUTE_NORMAL = 0x00000080
_FILE_ATTRIBUTE_DIRECTORY = 0x00000010
_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_FLAG_DELETE_ON_CLOSE = 0x04000000
_FILE_ATTRIBUTE_TAG_INFO_CLASS = 9
_FILE_ID_INFO_CLASS = 18
_FILE_BEGIN = 0
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF
_PRECOMMIT_THREAD_READY_SECONDS = 10.0


class _SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = (
        ("nLength", ctypes.c_ulong),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", ctypes.c_int),
    )


class _STARTUPINFOW(ctypes.Structure):
    _fields_ = (
        ("cb", ctypes.c_ulong),
        ("lpReserved", ctypes.c_wchar_p),
        ("lpDesktop", ctypes.c_wchar_p),
        ("lpTitle", ctypes.c_wchar_p),
        ("dwX", ctypes.c_ulong),
        ("dwY", ctypes.c_ulong),
        ("dwXSize", ctypes.c_ulong),
        ("dwYSize", ctypes.c_ulong),
        ("dwXCountChars", ctypes.c_ulong),
        ("dwYCountChars", ctypes.c_ulong),
        ("dwFillAttribute", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("wShowWindow", ctypes.c_ushort),
        ("cbReserved2", ctypes.c_ushort),
        ("lpReserved2", ctypes.POINTER(ctypes.c_ubyte)),
        ("hStdInput", ctypes.c_void_p),
        ("hStdOutput", ctypes.c_void_p),
        ("hStdError", ctypes.c_void_p),
    )


class _STARTUPINFOEXW(ctypes.Structure):
    _fields_ = (
        ("StartupInfo", _STARTUPINFOW),
        ("lpAttributeList", ctypes.c_void_p),
    )


class _PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = (
        ("hProcess", ctypes.c_void_p),
        ("hThread", ctypes.c_void_p),
        ("dwProcessId", ctypes.c_ulong),
        ("dwThreadId", ctypes.c_ulong),
    )


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


class _FILE_ATTRIBUTE_TAG_INFO(ctypes.Structure):
    _fields_ = (
        ("FileAttributes", ctypes.c_ulong),
        ("ReparseTag", ctypes.c_ulong),
    )


class _FILE_ID_128(ctypes.Structure):
    _fields_ = (("Identifier", ctypes.c_ubyte * 16),)


class _FILE_ID_INFO(ctypes.Structure):
    _fields_ = (
        ("VolumeSerialNumber", ctypes.c_ulonglong),
        ("FileId", _FILE_ID_128),
    )


_KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
_CREATE_PIPE = _KERNEL32.CreatePipe
_CREATE_PIPE.argtypes = [
    ctypes.POINTER(ctypes.c_void_p),
    ctypes.POINTER(ctypes.c_void_p),
    ctypes.POINTER(_SECURITY_ATTRIBUTES),
    ctypes.c_ulong,
]
_CREATE_PIPE.restype = ctypes.c_int
_SET_HANDLE_INFORMATION = _KERNEL32.SetHandleInformation
_SET_HANDLE_INFORMATION.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong]
_SET_HANDLE_INFORMATION.restype = ctypes.c_int
_CREATE_FILE = _KERNEL32.CreateFileW
_CREATE_FILE.argtypes = [
    ctypes.c_wchar_p,
    ctypes.c_ulong,
    ctypes.c_ulong,
    ctypes.POINTER(_SECURITY_ATTRIBUTES),
    ctypes.c_ulong,
    ctypes.c_ulong,
    ctypes.c_void_p,
]
_CREATE_FILE.restype = ctypes.c_void_p
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
_QUERY_INFORMATION_JOB_OBJECT = _KERNEL32.QueryInformationJobObject
_QUERY_INFORMATION_JOB_OBJECT.argtypes = [
    ctypes.c_void_p,
    ctypes.c_int,
    ctypes.c_void_p,
    ctypes.c_ulong,
    ctypes.c_void_p,
]
_QUERY_INFORMATION_JOB_OBJECT.restype = ctypes.c_int
_TERMINATE_JOB_OBJECT = _KERNEL32.TerminateJobObject
_TERMINATE_JOB_OBJECT.argtypes = [ctypes.c_void_p, ctypes.c_uint]
_TERMINATE_JOB_OBJECT.restype = ctypes.c_int
_TERMINATE_PROCESS = _KERNEL32.TerminateProcess
_TERMINATE_PROCESS.argtypes = [ctypes.c_void_p, ctypes.c_uint]
_TERMINATE_PROCESS.restype = ctypes.c_int
_INITIALIZE_ATTRIBUTE_LIST = _KERNEL32.InitializeProcThreadAttributeList
_INITIALIZE_ATTRIBUTE_LIST.argtypes = [
    ctypes.c_void_p,
    ctypes.c_ulong,
    ctypes.c_ulong,
    ctypes.POINTER(ctypes.c_size_t),
]
_INITIALIZE_ATTRIBUTE_LIST.restype = ctypes.c_int
_UPDATE_ATTRIBUTE = _KERNEL32.UpdateProcThreadAttribute
_UPDATE_ATTRIBUTE.argtypes = [
    ctypes.c_void_p,
    ctypes.c_ulong,
    ctypes.c_size_t,
    ctypes.c_void_p,
    ctypes.c_size_t,
    ctypes.c_void_p,
    ctypes.c_void_p,
]
_UPDATE_ATTRIBUTE.restype = ctypes.c_int
_DELETE_ATTRIBUTE_LIST = _KERNEL32.DeleteProcThreadAttributeList
_DELETE_ATTRIBUTE_LIST.argtypes = [ctypes.c_void_p]
_DELETE_ATTRIBUTE_LIST.restype = None
_CREATE_PROCESS = _KERNEL32.CreateProcessW
_CREATE_PROCESS.argtypes = [
    ctypes.c_wchar_p,
    ctypes.c_wchar_p,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_int,
    ctypes.c_ulong,
    ctypes.c_void_p,
    ctypes.c_wchar_p,
    ctypes.POINTER(_STARTUPINFOW),
    ctypes.POINTER(_PROCESS_INFORMATION),
]
_CREATE_PROCESS.restype = ctypes.c_int
_RESUME_THREAD = _KERNEL32.ResumeThread
_RESUME_THREAD.argtypes = [ctypes.c_void_p]
_RESUME_THREAD.restype = ctypes.c_ulong
_CREATE_EVENT = _KERNEL32.CreateEventW
_CREATE_EVENT.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_wchar_p]
_CREATE_EVENT.restype = ctypes.c_void_p
_SET_EVENT = _KERNEL32.SetEvent
_SET_EVENT.argtypes = [ctypes.c_void_p]
_SET_EVENT.restype = ctypes.c_int
_RESET_EVENT = _KERNEL32.ResetEvent
_RESET_EVENT.argtypes = [ctypes.c_void_p]
_RESET_EVENT.restype = ctypes.c_int
_WAIT_FOR_SINGLE_OBJECT = _KERNEL32.WaitForSingleObject
_WAIT_FOR_SINGLE_OBJECT.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
_WAIT_FOR_SINGLE_OBJECT.restype = ctypes.c_ulong
_WAIT_FOR_MULTIPLE_OBJECTS = _KERNEL32.WaitForMultipleObjects
_WAIT_FOR_MULTIPLE_OBJECTS.argtypes = [
    ctypes.c_ulong,
    ctypes.POINTER(ctypes.c_void_p),
    ctypes.c_int,
    ctypes.c_ulong,
]
_WAIT_FOR_MULTIPLE_OBJECTS.restype = ctypes.c_ulong
_GET_EXIT_CODE_PROCESS = _KERNEL32.GetExitCodeProcess
_GET_EXIT_CODE_PROCESS.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
_GET_EXIT_CODE_PROCESS.restype = ctypes.c_int
_READ_FILE = _KERNEL32.ReadFile
_READ_FILE.argtypes = [
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_ulong,
    ctypes.POINTER(ctypes.c_ulong),
    ctypes.c_void_p,
]
_READ_FILE.restype = ctypes.c_int
_WRITE_FILE = _KERNEL32.WriteFile
_WRITE_FILE.argtypes = [
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_ulong,
    ctypes.POINTER(ctypes.c_ulong),
    ctypes.c_void_p,
]
_WRITE_FILE.restype = ctypes.c_int
_CLOSE_HANDLE = _KERNEL32.CloseHandle
_CLOSE_HANDLE.argtypes = [ctypes.c_void_p]
_CLOSE_HANDLE.restype = ctypes.c_int
_GET_FILE_INFORMATION_BY_HANDLE_EX = _KERNEL32.GetFileInformationByHandleEx
_GET_FILE_INFORMATION_BY_HANDLE_EX.argtypes = [
    ctypes.c_void_p,
    ctypes.c_int,
    ctypes.c_void_p,
    ctypes.c_ulong,
]
_GET_FILE_INFORMATION_BY_HANDLE_EX.restype = ctypes.c_int
_GET_FILE_SIZE_EX = _KERNEL32.GetFileSizeEx
_GET_FILE_SIZE_EX.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_longlong)]
_GET_FILE_SIZE_EX.restype = ctypes.c_int
_SET_FILE_POINTER_EX = _KERNEL32.SetFilePointerEx
_SET_FILE_POINTER_EX.argtypes = [
    ctypes.c_void_p,
    ctypes.c_longlong,
    ctypes.POINTER(ctypes.c_longlong),
    ctypes.c_ulong,
]
_SET_FILE_POINTER_EX.restype = ctypes.c_int
_GET_FILE_ATTRIBUTES = _KERNEL32.GetFileAttributesW
_GET_FILE_ATTRIBUTES.argtypes = [ctypes.c_wchar_p]
_GET_FILE_ATTRIBUTES.restype = ctypes.c_ulong
class CancellationObservationV1(Protocol):
    def observed_at_monotonic_ns(self) -> int | None: ...


class NeverCancelledV1:
    def observed_at_monotonic_ns(self) -> None:
        return None


@dataclass(slots=True)
class CodexChildTestHooksV1:
    """Private deterministic barriers; production composition never supplies it."""

    collector_read_gate: threading.Event | None = None
    collector_waiting_at_gate: threading.Event | None = None
    collector_read_observed: threading.Event | None = None
    collector_read_seen_before_writer_join: bool | None = None
    stdin_write_call_active: threading.Event | None = None
    pipe_capacity_observer: Callable[[int, int], tuple[int, int]] | None = None
    prompt_factory: Callable[[int, int], bytes] | None = None
    command_line_factory: Callable[[int, int], str] | None = None
    measured_stdin_pipe_capacity_bytes: int | None = None
    measured_stdout_pipe_capacity_bytes: int | None = None
    selected_prompt: bytes | None = None
    selected_command_line: str | None = None


class CodexChildUnsafeHoldErrorV1(RuntimeError):
    """A committed attempt could not prove a safe terminal boundary."""


class CodexChildWin32ErrorV1(RuntimeError):
    """A Win32 observation failed but handle ownership remains known."""


class _StructuralFailures(list[str]):
    """An insertion-ordered first-fact latch with list compatibility."""

    __slots__ = ("_seen",)

    def __init__(self) -> None:
        super().__init__()
        self._seen: set[str] = set()

    def append(self, value: str) -> None:
        if value in self._seen:
            return
        self._seen.add(value)
        super().append(value)


@dataclass(frozen=True, slots=True)
class PreAttemptRejectedV1:
    reason: str
    resource_ledger_count: int
    create_process_calls: int = 0


@dataclass(frozen=True, slots=True)
class CaptureEvidenceV1:
    path: Path
    byte_length: int
    sha256: str
    overflow: bool


@dataclass(frozen=True, slots=True)
class AttemptTerminalEvidenceV1:
    role: str
    attempt_ordinal: int
    commit_wall_time: str
    commit_monotonic_ns: int
    provider_started_monotonic_ns: int | None
    attempt_deadline_monotonic_ns: int | None
    shared_deadline_monotonic_ns: int | None
    capture_ready_monotonic_ns: int | None
    exit_code: int | None
    mechanical_outcome: MechanicalOutcomeV1
    events: CaptureEvidenceV1
    final_message: CaptureEvidenceV1 | None
    create_process_calls: int
    stop_calls: int
    resource_ledger_count: int
    lifecycle_facts: tuple[str, ...]


@dataclass(slots=True)
class _WorkerFacts:
    lock: threading.Lock
    abort_requested: bool = False
    writer_done: bool = False
    writer_failure: str | None = None
    collector_done: bool = False
    collector_eof: bool = False
    collector_failure: str | None = None
    events_overflow: bool = False


class _ResourceLedger:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._owned: set[str] = set()

    def acquire(self, label: str) -> None:
        with self._lock:
            if label in self._owned:
                raise CodexChildUnsafeHoldErrorV1(f"duplicate ledger entry: {label}")
            self._owned.add(label)

    def settle(self, label: str) -> None:
        with self._lock:
            if label not in self._owned:
                raise CodexChildUnsafeHoldErrorV1(f"unknown ledger entry: {label}")
            self._owned.remove(label)

    def count(self) -> int:
        with self._lock:
            return len(self._owned)

    def contains(self, label: str) -> bool:
        with self._lock:
            return label in self._owned


@dataclass(slots=True)
class _OwnedHandle:
    value: int
    label: str
    ledger: _ResourceLedger
    closed: bool = False
    reserved: bool = False

    @classmethod
    def acquire(
        cls,
        value: int | None,
        label: str,
        ledger: _ResourceLedger,
    ) -> _OwnedHandle:
        if value in {None, 0, _INVALID_HANDLE_VALUE}:
            raise _win32_error(f"{label} acquisition failed")
        try:
            ledger.acquire(label)
        except BaseException as acquisition_error:
            if not _CLOSE_HANDLE(value):
                raise CodexChildUnsafeHoldErrorV1(
                    f"untracked CloseHandle({label}) failed"
                ) from acquisition_error
            raise
        return cls(int(value), label, ledger)

    @classmethod
    def reserve(cls, label: str, ledger: _ResourceLedger) -> _OwnedHandle:
        ledger.acquire(label)
        return cls(0, label, ledger, closed=True, reserved=True)

    def activate(self, value: int | None) -> _OwnedHandle:
        if not self.reserved or not self.closed or self.value != 0:
            raise CodexChildUnsafeHoldErrorV1(
                f"reserved handle activation is invalid: {self.label}"
            )
        if value in {None, 0, _INVALID_HANDLE_VALUE}:
            raise _win32_error(f"{self.label} activation failed")
        self.value = int(value)
        self.closed = False
        self.reserved = False
        return self

    def close(self) -> None:
        if self.reserved:
            self.reserved = False
            self.ledger.settle(self.label)
            return
        if self.closed:
            return
        self.closed = True
        if not _CLOSE_HANDLE(self.value):
            raise CodexChildUnsafeHoldErrorV1(
                f"CloseHandle({self.label}) failed (Win32 {ctypes.get_last_error()})"
            )
        self.ledger.settle(self.label)
        self.value = 0


@dataclass(slots=True)
class _OwnedFd:
    value: int
    label: str
    ledger: _ResourceLedger
    closed: bool = False

    @classmethod
    def acquire(cls, value: int, label: str, ledger: _ResourceLedger) -> _OwnedFd:
        try:
            ledger.acquire(label)
        except BaseException:
            try:
                os.close(value)
            except OSError as close_error:
                raise CodexChildUnsafeHoldErrorV1(
                    f"untracked close({label}) failed"
                ) from close_error
            raise
        return cls(value, label, ledger)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            os.close(self.value)
        except OSError as error:
            raise CodexChildUnsafeHoldErrorV1(f"close({self.label}) failed") from error
        self.ledger.settle(self.label)
        self.value = -1


@dataclass(slots=True)
class _OwnedPathGuard:
    capability: ValidatedDataRootV1 | ValidatedFileV1
    label: str
    ledger: _ResourceLedger
    closed: bool = False

    @classmethod
    def acquire(
        cls,
        capability: ValidatedDataRootV1 | ValidatedFileV1,
        label: str,
        ledger: _ResourceLedger,
    ) -> _OwnedPathGuard:
        try:
            ledger.acquire(label)
        except BaseException:
            try:
                capability.close()
            except (DataRootLifecycleErrorV1, OSError) as close_error:
                raise CodexChildUnsafeHoldErrorV1(
                    f"untracked path guard close({label}) failed"
                ) from close_error
            raise
        return cls(capability, label, ledger)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            self.capability.close()
        except (DataRootLifecycleErrorV1, OSError) as error:
            raise CodexChildUnsafeHoldErrorV1(
                f"path guard close({self.label}) failed"
            ) from error
        self.ledger.settle(self.label)


@dataclass(slots=True)
class _AttributeList:
    pointer: ctypes.c_void_p
    backing: ctypes.Array
    handles: ctypes.Array
    ledger: _ResourceLedger
    deleted: bool = False

    def delete(self) -> None:
        if self.deleted:
            return
        self.deleted = True
        _DELETE_ATTRIBUTE_LIST(self.pointer)
        self.ledger.settle("attribute-list")


@dataclass(slots=True)
class _PreparedAttempt:
    ledger: _ResourceLedger
    root_process_slot: _OwnedHandle
    primary_thread_slot: _OwnedHandle
    job: _OwnedHandle
    stdin_read: _OwnedHandle
    stdin_write: _OwnedHandle
    stdout_read: _OwnedHandle
    stdout_write: _OwnedHandle
    stderr_nul: _OwnedHandle
    go_event: _OwnedHandle
    abort_event: _OwnedHandle
    wake_event: _OwnedHandle
    events_fd: _OwnedFd
    facts: _WorkerFacts
    writer_ready: threading.Event
    collector_ready: threading.Event
    worker_activation: threading.Event
    precommit_rejected: threading.Event
    writer: threading.Thread | None
    collector: threading.Thread | None
    attribute_list: _AttributeList
    startup: _STARTUPINFOEXW
    command_buffer: ctypes.Array | None
    environment: ctypes.Array | None
    process_info: _PROCESS_INFORMATION | None
    environment_pointer: ctypes.c_void_p | None
    startup_pointer: object | None
    process_info_pointer: object | None
    path_guards: tuple[_OwnedPathGuard, ...]
    test_hooks: CodexChildTestHooksV1 | None


@dataclass(frozen=True, slots=True)
class _FinalCapture:
    existed: bool
    overflow: bool
    identity: tuple[int, bytes] | None
    private_capture_path: Path | None


@dataclass(slots=True)
class _ExternalBaseExceptionLatch:
    error: BaseException | None = None

    def observe(self, error: BaseException) -> bool:
        if isinstance(error, Exception):
            return False
        if self.error is None:
            self.error = error
        return True


def _win32_error(message: str) -> CodexChildWin32ErrorV1:
    return CodexChildWin32ErrorV1(
        f"{message} (Win32 {ctypes.get_last_error()})"
    )


def _utc_now() -> str:
    return (
        datetime.now(UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _monotonic_now_ns_v1() -> int:
    observed = time.monotonic_ns()
    if type(observed) is not int or observed < 0:
        raise ValueError("monotonic clock returned an invalid value")
    return observed


def _observe_cancellation_v1(
    cancellation: CancellationObservationV1,
) -> int | None:
    observed = cancellation.observed_at_monotonic_ns()
    if observed is not None and (type(observed) is not int or observed < 0):
        raise ValueError("cancellation observation returned an invalid value")
    return observed


def _observe_cancellation_after_commit(
    cancellation: CancellationObservationV1,
    structural_failures: list[str],
    external_exceptions: _ExternalBaseExceptionLatch,
) -> tuple[int | None, bool]:
    try:
        return _observe_cancellation_v1(cancellation), False
    except BaseException as error:  # noqa: BLE001 - committed boundary must settle.
        external_exceptions.observe(error)
        structural_failures.append(f"cancellation_observation:{type(error).__name__}")
        return None, True


def _monotonic_after_commit(
    structural_failures: list[str],
    external_exceptions: _ExternalBaseExceptionLatch,
    *,
    fallback_ns: int,
) -> tuple[int, bool]:
    try:
        return _monotonic_now_ns_v1(), False
    except BaseException as error:  # noqa: BLE001 - committed boundary must settle.
        external_exceptions.observe(error)
        structural_failures.append(f"monotonic_clock:{type(error).__name__}")
        return fallback_ns, True


def _rollback_precommit_staging(plan: FrozenCodexLaunchPlanV1) -> None:
    target = Path(plan.staging_directory)
    events = Path(plan.events_staging_path)
    if events.parent != target or events.name != ".events.capture":
        raise CodexChildUnsafeHoldErrorV1(
            "precommit staging ownership is invalid"
        )
    try:
        if os.path.lexists(events):
            if not events.is_file() or events.is_symlink():
                raise CodexChildUnsafeHoldErrorV1(
                    "precommit events entry changed identity"
                )
            events.unlink()
        target.rmdir()
    except FileNotFoundError:
        pass
    except OSError as error:
        raise CodexChildUnsafeHoldErrorV1(
            "precommit staging removal failed"
        ) from error
    if os.path.lexists(target):
        raise CodexChildUnsafeHoldErrorV1(
            "precommit staging still exists after removal"
        )


def _create_pipe_pair(
    *,
    prefix: str,
    ledger: _ResourceLedger,
) -> tuple[_OwnedHandle, _OwnedHandle]:
    security = _SECURITY_ATTRIBUTES(
        ctypes.sizeof(_SECURITY_ATTRIBUTES),
        None,
        True,
    )
    read = ctypes.c_void_p()
    write = ctypes.c_void_p()
    if not _CREATE_PIPE(
        ctypes.byref(read),
        ctypes.byref(write),
        ctypes.byref(security),
        CODEX_PIPE_BUFFER_HINT_BYTES_V1,
    ):
        raise _win32_error(f"CreatePipe({prefix}) failed")
    owned_read: _OwnedHandle | None = None
    owned_write: _OwnedHandle | None = None
    try:
        owned_read = _OwnedHandle.acquire(read.value, f"{prefix}-read", ledger)
        owned_write = _OwnedHandle.acquire(
            write.value,
            f"{prefix}-write",
            ledger,
        )
        return owned_read, owned_write
    except BaseException:
        if owned_write is not None:
            owned_write.close()
        elif write.value not in {None, 0}:
            _CLOSE_HANDLE(write.value)
        if owned_read is not None:
            owned_read.close()
        elif read.value not in {None, 0}:
            _CLOSE_HANDLE(read.value)
        raise


def _clear_inheritance(handle: _OwnedHandle) -> None:
    if not _SET_HANDLE_INFORMATION(handle.value, _HANDLE_FLAG_INHERIT, 0):
        raise _win32_error(f"SetHandleInformation({handle.label}) failed")


def _create_nul(ledger: _ResourceLedger) -> _OwnedHandle:
    security = _SECURITY_ATTRIBUTES(
        ctypes.sizeof(_SECURITY_ATTRIBUTES),
        None,
        True,
    )
    handle = _CREATE_FILE(
        "NUL",
        _GENERIC_WRITE,
        _FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE,
        ctypes.byref(security),
        _OPEN_EXISTING,
        _FILE_ATTRIBUTE_NORMAL,
        None,
    )
    return _OwnedHandle.acquire(handle, "stderr-nul", ledger)


def _create_job(ledger: _ResourceLedger) -> _OwnedHandle:
    job = _OwnedHandle.acquire(_CREATE_JOB_OBJECT(None, None), "job", ledger)
    limits = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not _SET_INFORMATION_JOB_OBJECT(
        job.value,
        _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
        ctypes.byref(limits),
        ctypes.sizeof(limits),
    ):
        error = _win32_error("SetInformationJobObject failed")
        job.close()
        raise error
    return job


def _create_event(label: str, ledger: _ResourceLedger) -> _OwnedHandle:
    return _OwnedHandle.acquire(
        _CREATE_EVENT(None, True, False, None),
        label,
        ledger,
    )


def _create_attribute_list(
    handles: tuple[_OwnedHandle, _OwnedHandle, _OwnedHandle],
    ledger: _ResourceLedger,
) -> _AttributeList:
    size = ctypes.c_size_t()
    ctypes.set_last_error(0)
    first = _INITIALIZE_ATTRIBUTE_LIST(None, 1, 0, ctypes.byref(size))
    first_error = ctypes.get_last_error()
    if first or size.value <= 0 or first_error != _ERROR_INSUFFICIENT_BUFFER:
        raise _win32_error("InitializeProcThreadAttributeList(size) failed")
    backing = ctypes.create_string_buffer(size.value)
    pointer = ctypes.cast(backing, ctypes.c_void_p)
    if not _INITIALIZE_ATTRIBUTE_LIST(pointer, 1, 0, ctypes.byref(size)):
        raise _win32_error("InitializeProcThreadAttributeList failed")
    handle_array_type = ctypes.c_void_p * 3
    handle_array = handle_array_type(*(item.value for item in handles))
    if not _UPDATE_ATTRIBUTE(
        pointer,
        0,
        _PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
        ctypes.cast(handle_array, ctypes.c_void_p),
        ctypes.sizeof(handle_array),
        None,
        None,
    ):
        error = _win32_error("UpdateProcThreadAttribute failed")
        _DELETE_ATTRIBUTE_LIST(pointer)
        raise error
    ledger.acquire("attribute-list")
    return _AttributeList(pointer, backing, handle_array, ledger)


def _write_all_fd(fd: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(fd, payload[offset:])
        if written <= 0:
            raise OSError("capture sink made no progress")
        offset += written


def _write_events_sink_all(fd: int, payload: bytes) -> None:
    _write_all_fd(fd, payload)


def _signal_wake(wake: _OwnedHandle) -> None:
    if not _SET_EVENT(wake.value):
        raise _win32_error("SetEvent(wake) failed")


def _publish_collector_failure(
    facts: _WorkerFacts,
    wake_event: _OwnedHandle,
    failure: str,
) -> str:
    with facts.lock:
        facts.collector_failure = facts.collector_failure or failure
    try:
        _signal_wake(wake_event)
    except CodexChildWin32ErrorV1 as error:
        wake_failure = f"stdout_wake_failure:{type(error).__name__}"
        with facts.lock:
            facts.collector_failure = (
                facts.collector_failure or wake_failure
            )
        return facts.collector_failure
    return failure


def _writer_abort_is_latched(
    facts: _WorkerFacts,
    abort_event: _OwnedHandle,
) -> bool:
    with facts.lock:
        if facts.abort_requested:
            return True
    verdict = int(_WAIT_FOR_SINGLE_OBJECT(abort_event.value, 0))
    if verdict == _WAIT_OBJECT_0:
        return True
    if verdict == _WAIT_TIMEOUT:
        return False
    raise CodexChildWin32ErrorV1(
        f"stdin abort observation failed: {verdict} "
        f"(Win32 {ctypes.get_last_error()})"
    )


def _writer_worker(
    prompt: bytes,
    stdin_write: _OwnedHandle,
    go_event: _OwnedHandle,
    abort_event: _OwnedHandle,
    wake_event: _OwnedHandle,
    facts: _WorkerFacts,
    ready: threading.Event,
    activation: threading.Event,
    precommit_rejected: threading.Event,
    test_hooks: CodexChildTestHooksV1 | None,
) -> None:
    failure: str | None = None
    try:
        ready.set()
        activation.wait()
        if precommit_rejected.is_set():
            return
        handles_type = ctypes.c_void_p * 2
        handles = handles_type(abort_event.value, go_event.value)
        while True:
            with facts.lock:
                abort_requested = facts.abort_requested
            if abort_requested:
                verdict = _WAIT_OBJECT_0
                break
            verdict = int(
                _WAIT_FOR_MULTIPLE_OBJECTS(
                    2,
                    handles,
                    False,
                    CODEX_CHILD_POLL_QUANTUM_MS_V1,
                )
            )
            if verdict == _WAIT_TIMEOUT:
                continue
            break
        if verdict == _WAIT_OBJECT_0 + 1:
            offset = 0
            while offset < len(prompt):
                if _writer_abort_is_latched(facts, abort_event):
                    break
                requested = min(CODEX_PIPE_IO_CHUNK_BYTES_V1, len(prompt) - offset)
                chunk = prompt[offset : offset + requested]
                buffer = ctypes.create_string_buffer(chunk, len(chunk))
                written = ctypes.c_ulong()
                if (
                    test_hooks is not None
                    and test_hooks.stdin_write_call_active is not None
                ):
                    test_hooks.stdin_write_call_active.set()
                try:
                    succeeded = bool(
                        _WRITE_FILE(
                            stdin_write.value,
                            buffer,
                            requested,
                            ctypes.byref(written),
                            None,
                        )
                    )
                finally:
                    if (
                        test_hooks is not None
                        and test_hooks.stdin_write_call_active is not None
                    ):
                        test_hooks.stdin_write_call_active.clear()
                count = int(written.value)
                if succeeded and 1 <= count <= requested:
                    offset += count
                    continue
                if _writer_abort_is_latched(facts, abort_event):
                    break
                failure = (
                    f"stdin_delivery_failure:{ctypes.get_last_error()}:{count}:"
                    f"{int(succeeded)}"
                )
                break
        elif verdict != _WAIT_OBJECT_0:
            failure = f"stdin_start_gate_failure:{verdict}"
    except BaseException as error:  # noqa: BLE001 - worker reports a frozen fact.
        failure = f"stdin_worker_failure:{type(error).__name__}"
    finally:
        try:
            stdin_write.close()
        except BaseException as error:  # noqa: BLE001
            failure = failure or f"stdin_close_failure:{type(error).__name__}"
        with facts.lock:
            facts.writer_failure = failure
            facts.writer_done = True
        try:
            _signal_wake(wake_event)
        except CodexChildWin32ErrorV1 as error:
            with facts.lock:
                facts.writer_failure = facts.writer_failure or (
                    f"stdin_wake_failure:{type(error).__name__}"
                )


def _collector_worker(
    stdout_read: _OwnedHandle,
    events_fd: _OwnedFd,
    wake_event: _OwnedHandle,
    facts: _WorkerFacts,
    ready: threading.Event,
    activation: threading.Event,
    precommit_rejected: threading.Event,
    *,
    events_capture_cap: int,
    test_hooks: CodexChildTestHooksV1 | None,
) -> None:
    failure: str | None = None
    eof = False
    retained = 0
    overflow = False
    drain_only = False
    try:
        ready.set()
        activation.wait()
        if precommit_rejected.is_set():
            return
        if test_hooks is not None and test_hooks.collector_read_gate is not None:
            if test_hooks.collector_waiting_at_gate is not None:
                test_hooks.collector_waiting_at_gate.set()
            test_hooks.collector_read_gate.wait()
        while True:
            buffer = ctypes.create_string_buffer(CODEX_PIPE_IO_CHUNK_BYTES_V1)
            read = ctypes.c_ulong()
            succeeded = bool(
                _READ_FILE(
                    stdout_read.value,
                    buffer,
                    CODEX_PIPE_IO_CHUNK_BYTES_V1,
                    ctypes.byref(read),
                    None,
                )
            )
            if (
                test_hooks is not None
                and test_hooks.collector_read_observed is not None
            ):
                test_hooks.collector_read_observed.set()
            count = int(read.value)
            if succeeded:
                if count > CODEX_PIPE_IO_CHUNK_BYTES_V1:
                    failure = failure or "stdout_collector_failure:overreported"
                    failure = _publish_collector_failure(
                        facts,
                        wake_event,
                        failure,
                    )
                    drain_only = True
                    continue
                if count == 0:
                    continue
                payload = buffer.raw[:count]
                keep = len(payload)
                sink_was_available = not drain_only
                keep = min(
                    len(payload),
                    max(0, events_capture_cap - retained),
                )
                if len(payload) > keep:
                    overflow = True
                    drain_only = True
                if keep and sink_was_available:
                    try:
                        _write_events_sink_all(events_fd.value, payload[:keep])
                        retained += keep
                    except OSError as error:
                        failure = failure or (
                            f"events_sink_failure:{getattr(error, 'winerror', None)}"
                        )
                        failure = _publish_collector_failure(
                            facts,
                            wake_event,
                            failure,
                        )
                        drain_only = True
                if overflow:
                    with facts.lock:
                        facts.events_overflow = True
                    _signal_wake(wake_event)
                continue
            error_code = ctypes.get_last_error()
            if error_code == _ERROR_BROKEN_PIPE:
                eof = True
                break
            failure = failure or f"stdout_collector_failure:{error_code}"
            drain_only = True
            failure = _publish_collector_failure(facts, wake_event, failure)
            time.sleep(0)
    except BaseException as error:  # noqa: BLE001
        failure = failure or f"stdout_worker_failure:{type(error).__name__}"
    finally:
        try:
            events_fd.close()
        except BaseException as error:  # noqa: BLE001
            failure = failure or f"events_close_failure:{type(error).__name__}"
        try:
            stdout_read.close()
        except BaseException as error:  # noqa: BLE001
            failure = failure or f"stdout_close_failure:{type(error).__name__}"
        with facts.lock:
            facts.collector_failure = failure
            facts.collector_eof = eof
            facts.events_overflow = overflow
            facts.collector_done = True
        try:
            _signal_wake(wake_event)
        except CodexChildWin32ErrorV1 as error:
            with facts.lock:
                facts.collector_failure = facts.collector_failure or (
                    f"stdout_wake_failure:{type(error).__name__}"
                )


def _apply_pipe_test_directives(
    stdin_read: _OwnedHandle,
    stdout_read: _OwnedHandle,
    hooks: CodexChildTestHooksV1,
    *,
    default_prompt: bytes,
    default_command_line: str,
) -> tuple[bytes, str]:
    observer = hooks.pipe_capacity_observer
    if observer is None:
        if hooks.prompt_factory is not None or hooks.command_line_factory is not None:
            raise CodexChildWin32ErrorV1(
                "test pipe factories require a same-pipe observer"
            )
        return default_prompt, default_command_line
    measured = observer(stdin_read.value, stdout_read.value)
    if (
        type(measured) is not tuple
        or len(measured) != 2
        or any(type(value) is not int or value <= 0 for value in measured)
    ):
        raise CodexChildWin32ErrorV1(
            "test pipe observer returned invalid capacities"
        )
    stdin_capacity, stdout_capacity = measured
    prompt = (
        hooks.prompt_factory(stdin_capacity, stdout_capacity)
        if hooks.prompt_factory is not None
        else default_prompt
    )
    command_line = (
        hooks.command_line_factory(stdin_capacity, stdout_capacity)
        if hooks.command_line_factory is not None
        else default_command_line
    )
    if type(prompt) is not bytes or not prompt:
        raise CodexChildWin32ErrorV1("test pipe prompt factory returned invalid bytes")
    if type(command_line) is not str or not command_line or "\0" in command_line:
        raise CodexChildWin32ErrorV1(
            "test pipe command factory returned an invalid command line"
        )
    hooks.measured_stdin_pipe_capacity_bytes = stdin_capacity
    hooks.measured_stdout_pipe_capacity_bytes = stdout_capacity
    hooks.selected_prompt = prompt
    hooks.selected_command_line = command_line
    return prompt, command_line


def _same_windows_path(left: str, right: str) -> bool:
    return ntpath.normcase(ntpath.normpath(left)) == ntpath.normcase(
        ntpath.normpath(right)
    )


def _close_path_guards(
    guards: tuple[_OwnedPathGuard, ...] | list[_OwnedPathGuard],
) -> list[CodexChildUnsafeHoldErrorV1]:
    failures: list[CodexChildUnsafeHoldErrorV1] = []
    for guard in reversed(guards):
        if guard.closed:
            continue
        try:
            guard.close()
        except CodexChildUnsafeHoldErrorV1 as error:
            failures.append(error)
    return failures


def _close_unowned_path_capability(
    capability: ValidatedDataRootV1 | ValidatedFileV1,
    *,
    label: str,
) -> None:
    try:
        capability.close()
    except (DataRootLifecycleErrorV1, OSError) as error:
        raise CodexChildUnsafeHoldErrorV1(
            f"mismatched {label} capability close failed"
        ) from error


def _open_attempt_path_guards(
    plan: FrozenCodexLaunchPlanV1,
    ledger: _ResourceLedger,
) -> tuple[_OwnedPathGuard, ...]:
    guards: list[_OwnedPathGuard] = []
    try:
        executable = open_validated_local_file_v1(plan.executable_path)
        if (
            not _same_windows_path(executable.canonical_path, plan.executable_path)
            or executable.identity != plan.runtime.executable_identity
            or executable.size != plan.runtime.executable_size
            or executable.sha256_v1() != plan.runtime.executable_sha256
        ):
            _close_unowned_path_capability(executable, label="executable")
            raise CodexChildWin32ErrorV1(
                "runtime executable identity changed before commitment"
            )
        guards.append(
            _OwnedPathGuard.acquire(executable, "path-executable", ledger)
        )
        directory_paths = (
            (
                "attempt-root",
                plan.attempt_root,
                plan.attempt_root_identity,
                plan.attempt_root_entries,
            ),
            (
                "working",
                plan.working_directory,
                plan.working_directory_identity,
                plan.working_directory_entries,
            ),
            (
                "capture-parent",
                plan.capture_parent,
                plan.capture_parent_identity,
                plan.capture_parent_entries,
            ),
            (
                "temporary",
                plan.temporary_directory,
                plan.temporary_directory_identity,
                plan.temporary_directory_entries,
            ),
            (
                "codex-home",
                plan.codex_home,
                plan.codex_home_identity,
                plan.codex_home_entries,
            ),
            (
                "sqlite-home",
                plan.sqlite_home,
                plan.sqlite_home_identity,
                plan.sqlite_home_entries,
            ),
            (
                "literature-authoritative-root",
                plan.literature_authoritative_root,
                plan.literature_authoritative_root_identity,
                None,
            ),
            (
                "knowledge-authoritative-root",
                plan.knowledge_authoritative_root,
                plan.knowledge_authoritative_root_identity,
                None,
            ),
        )
        for label, path, expected_identity, expected_entries in directory_paths:
            if not path:
                if expected_identity is not None or expected_entries not in {None, ()}:
                    raise CodexChildWin32ErrorV1(
                        f"{label} proof is inconsistent"
                    )
                continue
            directory = open_validated_data_root_v1(path)
            canonical = directory.inspection.canonical_path
            identity = directory.inspection.identity
            if (
                canonical is None
                or identity is None
                or expected_identity is None
                or not _same_windows_path(canonical, path)
                or identity != expected_identity
            ):
                _close_unowned_path_capability(directory, label=label)
                raise CodexChildWin32ErrorV1(
                    f"{label} identity changed before commitment"
                )
            if (
                expected_entries is not None
                and directory.relative_entry_names_v1() != expected_entries
            ):
                _close_unowned_path_capability(directory, label=label)
                raise CodexChildWin32ErrorV1(
                    f"{label} content changed before commitment"
                )
            guards.append(
                _OwnedPathGuard.acquire(directory, f"path-{label}", ledger)
            )
        if plan.schema_path:
            schema = open_validated_local_file_v1(plan.schema_path)
            if (
                plan.schema_identity is None
                or plan.schema_size is None
                or plan.schema_sha256 is None
                or not _same_windows_path(schema.canonical_path, plan.schema_path)
                or schema.identity != plan.schema_identity
                or schema.size != plan.schema_size
                or schema.sha256_v1() != plan.schema_sha256
            ):
                _close_unowned_path_capability(schema, label="schema")
                raise CodexChildWin32ErrorV1(
                    "schema identity changed before commitment"
                )
            guards.append(_OwnedPathGuard.acquire(schema, "path-schema", ledger))
        elif any(
            value is not None
            for value in (
                plan.schema_identity,
                plan.schema_size,
                plan.schema_sha256,
            )
        ):
            raise CodexChildWin32ErrorV1("schema proof is inconsistent")
        return tuple(guards)
    except (DataRootLifecycleErrorV1, DataRootOpenErrorV1) as error:
        failures = _close_path_guards(guards)
        if failures:
            raise CodexChildUnsafeHoldErrorV1(
                "path guard rollback did not settle"
            ) from failures[0]
        raise CodexChildWin32ErrorV1("attempt path identity is unavailable") from error
    except BaseException:
        failures = _close_path_guards(guards)
        if failures:
            raise CodexChildUnsafeHoldErrorV1(
                "path guard rollback did not settle"
            ) from failures[0]
        raise


def _prepare_attempt(
    plan: FrozenCodexLaunchPlanV1,
    test_hooks: CodexChildTestHooksV1 | None,
) -> _PreparedAttempt:
    staging = Path(plan.staging_directory)
    staging_created = False
    ledger = _ResourceLedger()
    path_guards: tuple[_OwnedPathGuard, ...] = ()
    events_fd: _OwnedFd | None = None
    handles: list[_OwnedHandle] = []
    root_process_slot: _OwnedHandle | None = None
    primary_thread_slot: _OwnedHandle | None = None
    attribute_list: _AttributeList | None = None
    prepared: _PreparedAttempt | None = None
    writer_prompt = plan.prompt
    selected_command_line = plan.quoted_command_line
    try:
        root_process_slot = _OwnedHandle.reserve("root-process", ledger)
        handles.append(root_process_slot)
        primary_thread_slot = _OwnedHandle.reserve("primary-thread", ledger)
        handles.append(primary_thread_slot)
        path_guards = _open_attempt_path_guards(plan, ledger)
        if os.path.lexists(plan.capture_directory) or os.path.lexists(staging):
            raise FileExistsError("attempt capture namespace is not fresh")
        os.mkdir(staging)
        staging_created = True
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        raw_fd = os.open(plan.events_staging_path, flags, 0o600)
        events_fd = _OwnedFd.acquire(raw_fd, "events-sink", ledger)
        os.set_inheritable(events_fd.value, False)
        stdin_read, stdin_write = _create_pipe_pair(prefix="stdin", ledger=ledger)
        handles.extend((stdin_read, stdin_write))
        stdout_read, stdout_write = _create_pipe_pair(prefix="stdout", ledger=ledger)
        handles.extend((stdout_read, stdout_write))
        _clear_inheritance(stdin_write)
        _clear_inheritance(stdout_read)
        if test_hooks is not None:
            writer_prompt, selected_command_line = _apply_pipe_test_directives(
                stdin_read,
                stdout_read,
                test_hooks,
                default_prompt=writer_prompt,
                default_command_line=selected_command_line,
            )
        stderr_nul = _create_nul(ledger)
        handles.append(stderr_nul)
        job = _create_job(ledger)
        handles.append(job)
        go_event = _create_event("go-event", ledger)
        handles.append(go_event)
        abort_event = _create_event("abort-event", ledger)
        handles.append(abort_event)
        wake_event = _create_event("wake-event", ledger)
        handles.append(wake_event)
        attribute_list = _create_attribute_list(
            (stdin_read, stdout_write, stderr_nul),
            ledger,
        )
        startup = _STARTUPINFOEXW()
        startup.StartupInfo.cb = ctypes.sizeof(_STARTUPINFOEXW)
        startup.StartupInfo.dwFlags = _STARTF_USESTDHANDLES
        startup.StartupInfo.hStdInput = stdin_read.value
        startup.StartupInfo.hStdOutput = stdout_write.value
        startup.StartupInfo.hStdError = stderr_nul.value
        startup.lpAttributeList = attribute_list.pointer
        facts = _WorkerFacts(lock=threading.Lock())
        writer_ready = threading.Event()
        collector_ready = threading.Event()
        worker_activation = threading.Event()
        precommit_rejected = threading.Event()
        command_buffer = ctypes.create_unicode_buffer(selected_command_line)
        ledger.acquire("command-line-buffer")
        environment = _environment_array(plan.environment_block)
        ledger.acquire("environment-block")
        process_info = _PROCESS_INFORMATION()
        ledger.acquire("process-information")
        environment_pointer = ctypes.cast(environment, ctypes.c_void_p)
        startup_pointer = ctypes.cast(
            ctypes.pointer(startup),
            ctypes.POINTER(_STARTUPINFOW),
        )
        process_info_pointer = ctypes.pointer(process_info)
        prepared = _PreparedAttempt(
            ledger=ledger,
            root_process_slot=root_process_slot,
            primary_thread_slot=primary_thread_slot,
            job=job,
            stdin_read=stdin_read,
            stdin_write=stdin_write,
            stdout_read=stdout_read,
            stdout_write=stdout_write,
            stderr_nul=stderr_nul,
            go_event=go_event,
            abort_event=abort_event,
            wake_event=wake_event,
            events_fd=events_fd,
            facts=facts,
            writer_ready=writer_ready,
            collector_ready=collector_ready,
            worker_activation=worker_activation,
            precommit_rejected=precommit_rejected,
            writer=None,
            collector=None,
            attribute_list=attribute_list,
            startup=startup,
            command_buffer=command_buffer,
            environment=environment,
            process_info=process_info,
            environment_pointer=environment_pointer,
            startup_pointer=startup_pointer,
            process_info_pointer=process_info_pointer,
            path_guards=path_guards,
            test_hooks=test_hooks,
        )
        writer = threading.Thread(
            target=_writer_worker,
            args=(
                writer_prompt,
                stdin_write,
                go_event,
                abort_event,
                wake_event,
                facts,
                writer_ready,
                worker_activation,
                precommit_rejected,
                test_hooks,
            ),
            name=f"gezhi-codex-stdin-{plan.attempt_ordinal}",
            daemon=False,
        )
        collector = threading.Thread(
            target=_collector_worker,
            args=(
                stdout_read,
                events_fd,
                wake_event,
                facts,
                collector_ready,
                worker_activation,
                precommit_rejected,
            ),
            kwargs={
                "events_capture_cap": _events_capture_cap_v1(plan.capture_profile),
                "test_hooks": test_hooks,
            },
            name=f"gezhi-codex-stdout-{plan.attempt_ordinal}",
            daemon=False,
        )
        prepared.writer = writer
        prepared.collector = collector
        writer.start()
        ledger.acquire("stdin-worker")
        collector.start()
        ledger.acquire("stdout-worker")
        if not writer_ready.wait(_PRECOMMIT_THREAD_READY_SECONDS):
            raise RuntimeError("stdin worker did not become ready")
        if not collector_ready.wait(_PRECOMMIT_THREAD_READY_SECONDS):
            raise RuntimeError("stdout worker did not become ready")
        snapshot = _snapshot_worker_facts(prepared)
        if snapshot.writer_done or snapshot.collector_done:
            raise RuntimeError("worker failed before ready-to-commit")
        return prepared
    except BaseException as original:
        cleanup_failures: list[BaseException] = []
        if attribute_list is not None:
            attribute_list.delete()
        if prepared is not None:
            try:
                prepared.precommit_rejected.set()
                with prepared.facts.lock:
                    prepared.facts.abort_requested = True
                prepared.worker_activation.set()
                for duplicate in (
                    prepared.stdin_read,
                    prepared.stdout_write,
                    prepared.stderr_nul,
                ):
                    if not duplicate.closed:
                        duplicate.close()
                for worker in (prepared.writer, prepared.collector):
                    if worker is not None and worker.ident is not None:
                        worker.join()
                for label in ("stdin-worker", "stdout-worker"):
                    if ledger.contains(label):
                        ledger.settle(label)
            except (
                CodexChildUnsafeHoldErrorV1,
                CodexChildWin32ErrorV1,
                RuntimeError,
            ) as cleanup_error:
                cleanup_failures.append(cleanup_error)
        for label in (
            "process-information",
            "environment-block",
            "command-line-buffer",
        ):
            if ledger.contains(label):
                ledger.settle(label)
        if events_fd is not None and not events_fd.closed:
            try:
                events_fd.close()
            except CodexChildUnsafeHoldErrorV1 as cleanup_error:
                cleanup_failures.append(cleanup_error)
        for handle in reversed(handles):
            if handle.reserved or not handle.closed:
                try:
                    handle.close()
                except CodexChildUnsafeHoldErrorV1 as cleanup_error:
                    cleanup_failures.append(cleanup_error)
        if staging_created:
            try:
                _rollback_precommit_staging(plan)
            except CodexChildUnsafeHoldErrorV1 as cleanup_error:
                cleanup_failures.append(cleanup_error)
        cleanup_failures.extend(_close_path_guards(path_guards))
        if cleanup_failures or ledger.count() != 0:
            raise CodexChildUnsafeHoldErrorV1(
                "precommit preparation cleanup did not settle"
            ) from original
        raise


def _job_active_processes(job: _OwnedHandle) -> int:
    accounting = _JOBOBJECT_BASIC_ACCOUNTING_INFORMATION()
    if not _QUERY_INFORMATION_JOB_OBJECT(
        job.value,
        _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION_CLASS,
        ctypes.byref(accounting),
        ctypes.sizeof(accounting),
        None,
    ):
        raise _win32_error("QueryInformationJobObject failed")
    return int(accounting.ActiveProcesses)


def _set_event(event: _OwnedHandle, *, label: str) -> None:
    if not _SET_EVENT(event.value):
        raise _win32_error(f"SetEvent({label}) failed")


def _request_writer_abort(
    prepared: _PreparedAttempt,
    structural_failures: list[str],
) -> None:
    with prepared.facts.lock:
        prepared.facts.abort_requested = True
    try:
        _set_event(prepared.abort_event, label="abort")
    except CodexChildWin32ErrorV1 as error:
        structural_failures.append(f"abort_signal:{error}")


def _release_writer_go(
    prepared: _PreparedAttempt,
    structural_failures: list[str],
) -> bool:
    try:
        _set_event(prepared.go_event, label="go")
    except CodexChildWin32ErrorV1 as error:
        structural_failures.append(f"go_signal:{error}")
        _request_writer_abort(prepared, structural_failures)
        return False
    return True


def _reset_wake(prepared: _PreparedAttempt) -> _WorkerFacts:
    with prepared.facts.lock:
        if not _RESET_EVENT(prepared.wake_event.value):
            raise _win32_error("ResetEvent(wake) failed")
        return _WorkerFacts(
            lock=threading.Lock(),
            writer_done=prepared.facts.writer_done,
            writer_failure=prepared.facts.writer_failure,
            collector_done=prepared.facts.collector_done,
            collector_eof=prepared.facts.collector_eof,
            collector_failure=prepared.facts.collector_failure,
            events_overflow=prepared.facts.events_overflow,
        )


def _snapshot_worker_facts(prepared: _PreparedAttempt) -> _WorkerFacts:
    with prepared.facts.lock:
        return _WorkerFacts(
            lock=threading.Lock(),
            writer_done=prepared.facts.writer_done,
            writer_failure=prepared.facts.writer_failure,
            collector_done=prepared.facts.collector_done,
            collector_eof=prepared.facts.collector_eof,
            collector_failure=prepared.facts.collector_failure,
            events_overflow=prepared.facts.events_overflow,
        )


def _environment_array(block: str) -> ctypes.Array:
    if not block.endswith("\0\0"):
        raise ValueError("environment block is not double-NUL terminated")
    array_type = ctypes.c_wchar * len(block)
    return array_type(*block)


def _file_identity(handle: int) -> tuple[int, bytes]:
    attributes = _FILE_ATTRIBUTE_TAG_INFO()
    if not _GET_FILE_INFORMATION_BY_HANDLE_EX(
        handle,
        _FILE_ATTRIBUTE_TAG_INFO_CLASS,
        ctypes.byref(attributes),
        ctypes.sizeof(attributes),
    ):
        raise _win32_error("GetFileInformationByHandleEx(attributes) failed")
    if attributes.FileAttributes & (
        _FILE_ATTRIBUTE_REPARSE_POINT | _FILE_ATTRIBUTE_DIRECTORY
    ):
        raise CodexChildUnsafeHoldErrorV1("final source is not a regular file")
    identity = _FILE_ID_INFO()
    if not _GET_FILE_INFORMATION_BY_HANDLE_EX(
        handle,
        _FILE_ID_INFO_CLASS,
        ctypes.byref(identity),
        ctypes.sizeof(identity),
    ):
        raise _win32_error("GetFileInformationByHandleEx(FileIdInfo) failed")
    return (
        int(identity.VolumeSerialNumber),
        bytes(identity.FileId.Identifier),
    )


def _active_final_probe(
    path: str,
    *,
    cap: int,
    ledger: _ResourceLedger,
) -> tuple[int, bytes] | None:
    handle = _CREATE_FILE(
        path,
        _GENERIC_READ,
        _FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE,
        None,
        _OPEN_EXISTING,
        _FILE_ATTRIBUTE_NORMAL | _FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    if handle in {None, 0, _INVALID_HANDLE_VALUE}:
        if ctypes.get_last_error() in {
            _ERROR_FILE_NOT_FOUND,
            _ERROR_PATH_NOT_FOUND,
            _ERROR_SHARING_VIOLATION,
            _ERROR_ACCESS_DENIED,
        }:
            return None
        raise _win32_error("active final probe open failed")
    owned = _OwnedHandle.acquire(handle, "active-final-probe", ledger)
    try:
        identity = _file_identity(owned.value)
        if not _SET_FILE_POINTER_EX(owned.value, cap, None, _FILE_BEGIN):
            raise _win32_error("active final probe seek failed")
        buffer = ctypes.create_string_buffer(1)
        read = ctypes.c_ulong()
        if not _READ_FILE(owned.value, buffer, 1, ctypes.byref(read), None):
            raise _win32_error("active final probe read failed")
        return identity if read.value == 1 else None
    finally:
        owned.close()


def _read_final_source(
    plan: FrozenCodexLaunchPlanV1,
    ledger: _ResourceLedger,
    *,
    early_overflow_identity: tuple[int, bytes] | None,
) -> _FinalCapture:
    if plan.final_spool_path is None:
        return _FinalCapture(False, False, None, None)
    source_path = plan.final_spool_path
    handle = _CREATE_FILE(
        source_path,
        _GENERIC_READ | _DELETE,
        0,
        None,
        _OPEN_EXISTING,
        _FILE_ATTRIBUTE_NORMAL
        | _FILE_FLAG_OPEN_REPARSE_POINT
        | _FILE_FLAG_DELETE_ON_CLOSE,
        None,
    )
    if handle in {None, 0, _INVALID_HANDLE_VALUE}:
        if ctypes.get_last_error() in {_ERROR_FILE_NOT_FOUND, _ERROR_PATH_NOT_FOUND}:
            if early_overflow_identity is not None:
                raise CodexChildUnsafeHoldErrorV1(
                    "witnessed final generation disappeared before finalization"
                )
            return _FinalCapture(False, False, None, None)
        raise _win32_error("authoritative final open failed")
    source = _OwnedHandle.acquire(handle, "final-source", ledger)
    private_capture = Path(plan.staging_directory) / ".final.capture"
    fd: _OwnedFd | None = None
    overflow = False
    identity: tuple[int, bytes] | None = None
    close_errors: list[BaseException] = []
    try:
        identity = _file_identity(source.value)
        size = ctypes.c_longlong()
        if not _GET_FILE_SIZE_EX(source.value, ctypes.byref(size)) or size.value < 0:
            raise _win32_error("GetFileSizeEx(final) failed")
        final_capture_cap = _final_capture_cap_v1(plan.capture_profile)
        limit = final_capture_cap
        raw_fd = os.open(
            private_capture,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
            0o600,
        )
        fd = _OwnedFd.acquire(raw_fd, "final-capture-sink", ledger)
        retained = 0
        while retained < limit:
            requested = min(CODEX_PIPE_IO_CHUNK_BYTES_V1, limit - retained)
            buffer = ctypes.create_string_buffer(requested)
            read = ctypes.c_ulong()
            if not _READ_FILE(
                source.value,
                buffer,
                requested,
                ctypes.byref(read),
                None,
            ):
                raise _win32_error("ReadFile(final) failed")
            count = int(read.value)
            if count == 0:
                break
            if count > requested:
                raise CodexChildUnsafeHoldErrorV1("final read overreported bytes")
            _write_all_fd(fd.value, buffer.raw[:count])
            retained += count
        if retained == limit:
            witness = ctypes.create_string_buffer(1)
            read = ctypes.c_ulong()
            if not _READ_FILE(source.value, witness, 1, ctypes.byref(read), None):
                raise _win32_error("ReadFile(final witness) failed")
            overflow = read.value == 1
        elif retained < int(size.value):
            raise CodexChildUnsafeHoldErrorV1("final source truncated during read")
        if (
            early_overflow_identity is not None
            and identity != early_overflow_identity
        ):
            raise CodexChildUnsafeHoldErrorV1(
                "final generation changed after overflow witness"
            )
        if early_overflow_identity is not None and not overflow:
            raise CodexChildUnsafeHoldErrorV1(
                "final overflow was not independently confirmed"
            )
    finally:
        if fd is not None and not fd.closed:
            try:
                fd.close()
            except CodexChildUnsafeHoldErrorV1 as error:
                close_errors.append(error)
        if not source.closed:
            try:
                source.close()
            except CodexChildUnsafeHoldErrorV1 as error:
                close_errors.append(error)
    if close_errors:
        raise CodexChildUnsafeHoldErrorV1(
            "authoritative final resources did not settle"
        ) from close_errors[0]
    attributes = int(_GET_FILE_ATTRIBUTES(source_path))
    if attributes != _INVALID_FILE_ATTRIBUTES:
        raise CodexChildUnsafeHoldErrorV1(
            "final pathname still exists after generation deletion"
        )
    if ctypes.get_last_error() not in {_ERROR_FILE_NOT_FOUND, _ERROR_PATH_NOT_FOUND}:
        raise _win32_error("final pathname deletion verification failed")
    return _FinalCapture(True, overflow, identity, private_capture)


def _capture_evidence(path: Path, *, overflow: bool) -> CaptureEvidenceV1:
    digest = hashlib.sha256()
    length = 0
    with path.open("rb", buffering=0) as source:
        while True:
            chunk = source.read(CODEX_PIPE_IO_CHUNK_BYTES_V1)
            if not chunk:
                break
            digest.update(chunk)
            length += len(chunk)
    return CaptureEvidenceV1(path, length, digest.hexdigest(), overflow)


def _install_captures(
    plan: FrozenCodexLaunchPlanV1,
    ledger: _ResourceLedger,
    *,
    events_overflow: bool,
    final_capture: _FinalCapture,
) -> tuple[CaptureEvidenceV1, CaptureEvidenceV1 | None]:
    staging = Path(plan.staging_directory)
    events_private = Path(plan.events_staging_path)
    events_preview = _capture_evidence(
        events_private,
        overflow=events_overflow,
    )
    events_capture_cap = _events_capture_cap_v1(plan.capture_profile)
    if (
        events_overflow
        and events_preview.byte_length != events_capture_cap
    ) or events_preview.byte_length > events_capture_cap:
        raise CodexChildUnsafeHoldErrorV1(
            "Role events overflow did not retain the exact cap prefix"
        )
    if final_capture.existed:
        assert final_capture.private_capture_path is not None
        final_preview = _capture_evidence(
            final_capture.private_capture_path,
            overflow=final_capture.overflow,
        )
        final_capture_cap = _final_capture_cap_v1(plan.capture_profile)
        if (
            (
                final_capture.overflow
                and final_preview.byte_length != final_capture_cap
            )
            or final_preview.byte_length > final_capture_cap
        ):
            raise CodexChildUnsafeHoldErrorV1(
                "Role final overflow did not retain the exact cap prefix"
            )
    events_formal = staging / "events.jsonl"
    os.replace(events_private, events_formal)
    final_formal: Path | None = None
    if final_capture.existed:
        assert final_capture.private_capture_path is not None
        final_formal = staging / "final_message.txt"
        os.replace(final_capture.private_capture_path, final_formal)
    elif plan.capture_profile == "knowledge":
        final_formal = staging / "final_message.txt"
        raw_fd = os.open(
            final_formal,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
            0o600,
        )
        empty_final = _OwnedFd.acquire(raw_fd, "empty-final-sink", ledger)
        empty_final.close()
    os.replace(staging, plan.capture_directory)
    target = Path(plan.capture_directory)
    events = _capture_evidence(
        target / "events.jsonl",
        overflow=events_overflow,
    )
    final = (
        _capture_evidence(
            target / "final_message.txt",
            overflow=final_capture.overflow,
        )
        if final_formal is not None
        else None
    )
    return events, final


def _wait_threads(prepared: _PreparedAttempt) -> None:
    assert prepared.writer is not None
    assert prepared.collector is not None
    if prepared.test_hooks is not None:
        observed = prepared.test_hooks.collector_read_observed
        if observed is not None:
            prepared.test_hooks.collector_read_seen_before_writer_join = (
                observed.is_set()
            )
    prepared.writer.join()
    prepared.collector.join()
    if prepared.writer.is_alive() or prepared.collector.is_alive():
        raise CodexChildUnsafeHoldErrorV1("worker join did not settle")
    for label in ("stdin-worker", "stdout-worker"):
        if prepared.ledger.contains(label):
            prepared.ledger.settle(label)


def _close_prepared_non_job(prepared: _PreparedAttempt) -> None:
    for handle in (
        prepared.go_event,
        prepared.abort_event,
        prepared.wake_event,
    ):
        handle.close()


def _cleanup_precommit(
    prepared: _PreparedAttempt,
    plan: FrozenCodexLaunchPlanV1,
) -> None:
    prepared.precommit_rejected.set()
    with prepared.facts.lock:
        prepared.facts.abort_requested = True
    prepared.worker_activation.set()
    for handle in (
        prepared.stdin_read,
        prepared.stdout_write,
        prepared.stderr_nul,
    ):
        if not handle.closed:
            handle.close()
    prepared.root_process_slot.close()
    prepared.primary_thread_slot.close()
    _wait_threads(prepared)
    prepared.attribute_list.delete()
    for label in (
        "process-information",
        "environment-block",
        "command-line-buffer",
    ):
        if prepared.ledger.contains(label):
            prepared.ledger.settle(label)
    prepared.process_info = None
    prepared.process_info_pointer = None
    prepared.environment = None
    prepared.environment_pointer = None
    prepared.command_buffer = None
    prepared.startup_pointer = None
    _close_prepared_non_job(prepared)
    prepared.job.close()
    _rollback_precommit_staging(plan)
    path_failures = _close_path_guards(prepared.path_guards)
    if path_failures:
        raise CodexChildUnsafeHoldErrorV1(
            "precommit path guards did not settle"
        ) from path_failures[0]
    if prepared.ledger.count() != 0:
        raise CodexChildUnsafeHoldErrorV1("precommit ledger did not reach zero")


def _wait_once(
    process: _OwnedHandle | None,
    wake: _OwnedHandle,
    *,
    root_signaled: bool,
    milliseconds: int,
) -> None:
    if process is not None and not root_signaled:
        handles_type = ctypes.c_void_p * 2
        handles = handles_type(process.value, wake.value)
        verdict = int(
            _WAIT_FOR_MULTIPLE_OBJECTS(2, handles, False, milliseconds)
        )
        if verdict not in {
            _WAIT_OBJECT_0,
            _WAIT_OBJECT_0 + 1,
            _WAIT_TIMEOUT,
        }:
            raise _win32_error("WaitForMultipleObjects failed")
        return
    verdict = int(_WAIT_FOR_SINGLE_OBJECT(wake.value, milliseconds))
    if verdict not in {_WAIT_OBJECT_0, _WAIT_TIMEOUT}:
        raise _win32_error("WaitForSingleObject(wake) failed")


def _poll_milliseconds(active_deadline_ns: int | None, now_ns: int) -> int:
    if active_deadline_ns is None:
        return CODEX_CHILD_POLL_QUANTUM_MS_V1
    remaining_ns = max(0, active_deadline_ns - now_ns)
    remaining_ms = (remaining_ns + 999_999) // 1_000_000
    return min(CODEX_CHILD_POLL_QUANTUM_MS_V1, remaining_ms)


def _classify_mechanical_outcome_v1(
    *,
    events_overflow: bool,
    final_overflow: bool,
    has_structural_failure: bool,
    cancel_observed_at_ns: int | None,
    active_deadline_ns: int | None,
    classification_ready_at_ns: int,
    exit_code: int | None,
) -> MechanicalOutcomeV1:
    if events_overflow or final_overflow or has_structural_failure:
        return "process_error"
    if (
        cancel_observed_at_ns is not None
        and cancel_observed_at_ns <= classification_ready_at_ns
        and (
            active_deadline_ns is None
            or cancel_observed_at_ns <= active_deadline_ns
        )
    ):
        return "interrupted"
    if (
        active_deadline_ns is not None
        and active_deadline_ns <= classification_ready_at_ns
    ):
        return "timeout"
    if exit_code not in {None, 0}:
        return "provider_or_process_exit"
    return "clean"


def _run_codex_child_core_v1(
    plan: FrozenCodexLaunchPlanV1,
    cancellation: CancellationObservationV1,
    test_hooks: CodexChildTestHooksV1 | None,
) -> PreAttemptRejectedV1 | AttemptTerminalEvidenceV1:
    """Run one frozen role attempt and return only after its ledger is zero."""

    if type(plan) is not FrozenCodexLaunchPlanV1:
        raise TypeError("a frozen Codex launch plan is required")
    if not hasattr(cancellation, "observed_at_monotonic_ns"):
        raise TypeError("a read-only cancellation observation is required")
    try:
        prepared = _prepare_attempt(plan, test_hooks)
    except CodexChildUnsafeHoldErrorV1:
        raise
    except Exception as error:  # noqa: BLE001 - BaseException must cross this boundary.
        return PreAttemptRejectedV1(
            reason=f"preparation_failed:{type(error).__name__}",
            resource_ledger_count=0,
        )
    process_info = prepared.process_info
    command_buffer = prepared.command_buffer
    environment = prepared.environment
    environment_pointer = prepared.environment_pointer
    startup_pointer = prepared.startup_pointer
    process_info_pointer = prepared.process_info_pointer
    if (
        process_info is None
        or command_buffer is None
        or environment is None
        or environment_pointer is None
        or startup_pointer is None
        or process_info_pointer is None
    ):
        raise CodexChildUnsafeHoldErrorV1("launch allocations are not owned")
    process: _OwnedHandle | None = None
    primary_thread: _OwnedHandle | None = None
    created = False
    create_process_observation_failed = False
    contain_suspended_root_directly = False
    assignment_succeeded = False
    structural_failures = _StructuralFailures()
    external_exceptions = _ExternalBaseExceptionLatch()
    committed_unsafe_error: CodexChildUnsafeHoldErrorV1 | None = None
    create_process_calls = 1
    stop_calls = 0
    stop_requested = False
    provider_started_ns: int | None = None
    attempt_deadline_ns: int | None = None
    shared_deadline_ns = plan.existing_shared_deadline_monotonic_ns
    active_deadline_ns = shared_deadline_ns
    root_signaled = False
    exit_code: int | None = None
    early_final_overflow_identity: tuple[int, bytes] | None = None
    final_probe_disabled = False
    final_capture: _FinalCapture | None = None

    def latch_committed_unsafe(
        label: str,
        error: CodexChildUnsafeHoldErrorV1,
    ) -> None:
        nonlocal committed_unsafe_error
        structural_failures.append(f"{label}:{error}")
        if committed_unsafe_error is None:
            committed_unsafe_error = error
    try:
        commit_wall_time = _utc_now()
        cancel_before_commit = _observe_cancellation_v1(cancellation)
        commit_monotonic_ns = _monotonic_now_ns_v1()
    except BaseException as error:
        _cleanup_precommit(prepared, plan)
        if not isinstance(error, Exception):
            raise
        return PreAttemptRejectedV1(
            reason=f"commit_gate_failed:{type(error).__name__}",
            resource_ledger_count=prepared.ledger.count(),
        )
    if (
        cancel_before_commit is not None
        and cancel_before_commit <= commit_monotonic_ns
    ) or (
        plan.existing_shared_deadline_monotonic_ns is not None
        and plan.existing_shared_deadline_monotonic_ns <= commit_monotonic_ns
    ):
        _cleanup_precommit(prepared, plan)
        return PreAttemptRejectedV1(
            reason=(
                "cancelled_before_commit"
                if cancel_before_commit is not None
                else "shared_deadline_before_commit"
            ),
            resource_ledger_count=prepared.ledger.count(),
        )

    try:
        created = bool(
            _CREATE_PROCESS(
                plan.executable_path,
                command_buffer,
                None,
                None,
                True,
                _CREATION_FLAGS,
                environment_pointer,
                plan.working_directory,
                startup_pointer,
                process_info_pointer,
            )
        )
    except BaseException as error:  # noqa: BLE001 - committed syscall adapter.
        external_exceptions.observe(error)
        structural_failures.append(
            f"create_process_exception:{type(error).__name__}"
        )
        create_process_observation_failed = True
        created = False
    finally:
        try:
            prepared.attribute_list.delete()
        except CodexChildUnsafeHoldErrorV1 as error:
            latch_committed_unsafe("attribute_list_delete", error)
        except BaseException as error:  # noqa: BLE001 - committed settlement.
            if external_exceptions.observe(error):
                structural_failures.append(
                    f"attribute_list_delete:{type(error).__name__}"
                )
            else:
                latch_committed_unsafe(
                    "attribute_list_delete",
                    CodexChildUnsafeHoldErrorV1(
                        f"attribute list deletion raised {type(error).__name__}"
                    ),
                )
        prepared.worker_activation.set()
        for label in ("environment-block", "command-line-buffer"):
            if prepared.ledger.contains(label):
                try:
                    prepared.ledger.settle(label)
                except CodexChildUnsafeHoldErrorV1 as error:
                    latch_committed_unsafe(f"{label}_settle", error)
        prepared.environment = None
        prepared.environment_pointer = None
        prepared.command_buffer = None
        prepared.startup_pointer = None
        for path_close_error in _close_path_guards(prepared.path_guards):
            latch_committed_unsafe("path_guard_close", path_close_error)
    del (
        command_buffer,
        environment,
        environment_pointer,
        startup_pointer,
        process_info_pointer,
    )
    raw_process = int(process_info.hProcess or 0)
    raw_thread = int(process_info.hThread or 0)
    if (
        create_process_observation_failed
        and raw_process not in {0, _INVALID_HANDLE_VALUE}
        and raw_thread not in {0, _INVALID_HANDLE_VALUE}
    ):
        created = True
        contain_suspended_root_directly = True
    if created:
        process = prepared.root_process_slot
        primary_thread = prepared.primary_thread_slot
        adoption_failed = contain_suspended_root_directly
        try:
            process.activate(raw_process)
            primary_thread.activate(raw_thread)
        except BaseException as error:  # noqa: BLE001 - committed adoption.
            external_exceptions.observe(error)
            adoption_failed = True
            structural_failures.append(
                f"process_handle_adoption:{type(error).__name__}"
            )
            for slot, raw_value in (
                (process, raw_process),
                (primary_thread, raw_thread),
            ):
                if (
                    slot.reserved
                    and raw_value not in {0, _INVALID_HANDLE_VALUE}
                ):
                    slot.value = raw_value
                    slot.closed = False
                    slot.reserved = False
        if process.reserved:
            unsafe = CodexChildUnsafeHoldErrorV1(
                "CreateProcessW returned no ownable root process handle"
            )
            latch_committed_unsafe("process_handle_adoption", unsafe)
        elif not adoption_failed:
            try:
                assignment_succeeded = bool(
                    _ASSIGN_PROCESS_TO_JOB_OBJECT(
                        prepared.job.value,
                        process.value,
                    )
                )
            except BaseException as error:  # noqa: BLE001 - committed syscall.
                external_exceptions.observe(error)
                structural_failures.append(
                    f"assign_process_to_job_exception:{type(error).__name__}"
                )
            if not assignment_succeeded:
                structural_failures.append(
                    f"assign_process_to_job:{ctypes.get_last_error()}"
                )
    else:
        prepared.root_process_slot.close()
        prepared.primary_thread_slot.close()
        structural_failures.append(f"create_process:{ctypes.get_last_error()}")
    if prepared.ledger.contains("process-information"):
        try:
            prepared.ledger.settle("process-information")
        except CodexChildUnsafeHoldErrorV1 as error:
            latch_committed_unsafe("process_information_settle", error)
    prepared.process_info = None
    prepared.process_info_pointer = None

    for duplicate in (
        prepared.stdin_read,
        prepared.stdout_write,
        prepared.stderr_nul,
    ):
        try:
            duplicate.close()
        except CodexChildUnsafeHoldErrorV1 as error:
            latch_committed_unsafe(f"child_duplicate_close:{duplicate.label}", error)

    if not created:
        _request_writer_abort(prepared, structural_failures)
        root_signaled = True
    elif not assignment_succeeded:
        assert process is not None
        _request_writer_abort(prepared, structural_failures)
        if not _TERMINATE_PROCESS(process.value, CODEX_JOB_STOP_EXIT_DWORD_V1):
            structural_failures.append(
                f"terminate_suspended_root:{ctypes.get_last_error()}"
            )
    else:
        gate_cancel, gate_cancel_fault = _observe_cancellation_after_commit(
            cancellation,
            structural_failures,
            external_exceptions,
        )
        gate_now_ns, gate_clock_fault = _monotonic_after_commit(
            structural_failures,
            external_exceptions,
            fallback_ns=commit_monotonic_ns,
        )
        gate_deadline_ns = plan.existing_shared_deadline_monotonic_ns
        gate_blocked = bool(structural_failures) or gate_cancel_fault or gate_clock_fault or (
            gate_cancel is not None and gate_cancel <= gate_now_ns
        ) or (
            gate_deadline_ns is not None and gate_deadline_ns <= gate_now_ns
        )
        if gate_blocked:
            _request_writer_abort(prepared, structural_failures)
            stop_requested = True
        else:
            assert primary_thread is not None
            try:
                previous = int(_RESUME_THREAD(primary_thread.value))
            except BaseException as error:  # noqa: BLE001 - committed syscall.
                external_exceptions.observe(error)
                structural_failures.append(
                    f"resume_thread_exception:{type(error).__name__}"
                )
                _request_writer_abort(prepared, structural_failures)
                stop_requested = True
            else:
                if previous == 1:
                    started_observation_ns, started_clock_fault = (
                        _monotonic_after_commit(
                            structural_failures,
                            external_exceptions,
                            fallback_ns=gate_now_ns,
                        )
                    )
                    if started_clock_fault:
                        structural_failures.append(
                            "provider_started_timestamp_unavailable"
                        )
                        _request_writer_abort(prepared, structural_failures)
                        stop_requested = True
                    else:
                        provider_started_ns = started_observation_ns
                        attempt_deadline_ns = provider_started_ns + plan.timeout_ns
                        if shared_deadline_ns is None:
                            shared_deadline_ns = (
                                provider_started_ns + plan.shared_window_ns
                            )
                        active_deadline_ns = min(
                            value
                            for value in (attempt_deadline_ns, shared_deadline_ns)
                            if value is not None
                        )
                        if not _release_writer_go(prepared, structural_failures):
                            stop_requested = True
                else:
                    structural_failures.append(f"resume_thread:{previous}")
                    _request_writer_abort(prepared, structural_failures)
                    stop_requested = True
    if primary_thread is not None:
        try:
            primary_thread.close()
        except CodexChildUnsafeHoldErrorV1 as error:
            latch_committed_unsafe("primary_thread_close", error)

    if committed_unsafe_error is not None and not stop_requested:
        _request_writer_abort(prepared, structural_failures)
        stop_requested = True

    if stop_requested and assignment_succeeded:
        assert process is not None
        try:
            initially_nonempty = _job_active_processes(prepared.job) != 0
        except CodexChildWin32ErrorV1 as error:
            structural_failures.append(f"job_query:{error}")
            initially_nonempty = True
        if initially_nonempty:
            stop_calls += 1
            if not _TERMINATE_JOB_OBJECT(
                prepared.job.value,
                CODEX_JOB_STOP_EXIT_DWORD_V1,
            ):
                structural_failures.append(
                    f"terminate_job:{ctypes.get_last_error()}"
                )

    last_now_ns = provider_started_ns or commit_monotonic_ns
    while True:
        cancellation_time_ns, _cancel_fault = (
            _observe_cancellation_after_commit(
                cancellation,
                structural_failures,
                external_exceptions,
            )
        )
        now_ns, _clock_fault = _monotonic_after_commit(
            structural_failures,
            external_exceptions,
            fallback_ns=last_now_ns,
        )
        last_now_ns = now_ns
        try:
            snapshot = _reset_wake(prepared)
        except CodexChildWin32ErrorV1 as error:
            structural_failures.append(f"wake_reset:{error}")
            snapshot = _snapshot_worker_facts(prepared)
        if snapshot.writer_failure is not None:
            structural_failures.append(snapshot.writer_failure)
        if snapshot.collector_failure is not None:
            structural_failures.append(snapshot.collector_failure)
        try:
            job_empty = _job_active_processes(prepared.job) == 0
        except CodexChildWin32ErrorV1 as error:
            structural_failures.append(f"job_query:{error}")
            job_empty = False
        if process is not None and not root_signaled:
            verdict = int(_WAIT_FOR_SINGLE_OBJECT(process.value, 0))
            if verdict == _WAIT_OBJECT_0:
                root_signaled = True
                code = ctypes.c_ulong()
                if _GET_EXIT_CODE_PROCESS(process.value, ctypes.byref(code)):
                    exit_code = int(code.value)
                else:
                    structural_failures.append(
                        f"get_exit_code:{ctypes.get_last_error()}"
                    )
                try:
                    process.close()
                except CodexChildUnsafeHoldErrorV1 as error:
                    latch_committed_unsafe("root_process_close", error)
            elif verdict not in {_WAIT_TIMEOUT}:
                structural_failures.append(
                    f"wait_root:{ctypes.get_last_error()}:{verdict}"
                )
        if (
            plan.final_spool_path is not None
            and not job_empty
            and not final_probe_disabled
        ):
            try:
                witness = _active_final_probe(
                    plan.final_spool_path,
                    cap=_final_capture_cap_v1(plan.capture_profile),
                    ledger=prepared.ledger,
                )
            except CodexChildWin32ErrorV1 as error:
                structural_failures.append(f"final_probe:{error}")
                witness = None
            except CodexChildUnsafeHoldErrorV1 as error:
                latch_committed_unsafe("final_probe_close", error)
                final_probe_disabled = True
                witness = None
            if witness is not None:
                early_final_overflow_identity = witness
        due_cancel = (
            cancellation_time_ns is not None and cancellation_time_ns <= now_ns
        )
        due_deadline = (
            active_deadline_ns is not None and active_deadline_ns <= now_ns
        )
        due_structure = bool(
            structural_failures
            or snapshot.events_overflow
            or early_final_overflow_identity is not None
        )
        if (due_cancel or due_deadline or due_structure) and not stop_requested:
            stop_requested = True
            _request_writer_abort(prepared, structural_failures)
            if not job_empty and assignment_succeeded:
                stop_calls += 1
                if not _TERMINATE_JOB_OBJECT(
                    prepared.job.value,
                    CODEX_JOB_STOP_EXIT_DWORD_V1,
                ):
                    structural_failures.append(
                        f"terminate_job:{ctypes.get_last_error()}"
                    )
        if (
            root_signaled
            and job_empty
            and snapshot.writer_done
            and snapshot.collector_done
        ):
            if not snapshot.collector_eof and snapshot.collector_failure is None:
                structural_failures.append("stdout_missing_eof")
            break
        try:
            _wait_once(
                process,
                prepared.wake_event,
                root_signaled=root_signaled,
                milliseconds=_poll_milliseconds(active_deadline_ns, now_ns),
            )
        except CodexChildWin32ErrorV1 as error:
            structural_failures.append(f"wait:{error}")

    _wait_threads(prepared)
    try:
        final_capture = _read_final_source(
            plan,
            prepared.ledger,
            early_overflow_identity=early_final_overflow_identity,
        )
        try:
            snapshot = _reset_wake(prepared)
        except CodexChildWin32ErrorV1 as error:
            structural_failures.append(f"wake_reset:{error}")
            snapshot = _snapshot_worker_facts(prepared)
        events_overflow = snapshot.events_overflow
        final_overflow = final_capture.overflow
        events, final = _install_captures(
            plan,
            prepared.ledger,
            events_overflow=events_overflow,
            final_capture=final_capture,
        )
        _close_prepared_non_job(prepared)
        capture_ready_observation_ns, capture_clock_fault = (
            _monotonic_after_commit(
                structural_failures,
                external_exceptions,
                fallback_ns=last_now_ns,
            )
        )
        capture_ready_ns = (
            None if capture_clock_fault else capture_ready_observation_ns
        )
        if capture_clock_fault:
            structural_failures.append("capture_ready_timestamp_unavailable")
        classification_cancel_ns, _classification_cancel_fault = (
            _observe_cancellation_after_commit(
                cancellation,
                structural_failures,
                external_exceptions,
            )
        )
        outcome = _classify_mechanical_outcome_v1(
            events_overflow=events_overflow,
            final_overflow=final_overflow,
            has_structural_failure=bool(structural_failures),
            cancel_observed_at_ns=classification_cancel_ns,
            active_deadline_ns=active_deadline_ns,
            classification_ready_at_ns=capture_ready_observation_ns,
            exit_code=exit_code,
        )
    except BaseException as terminal_error:
        try:
            _close_prepared_non_job(prepared)
            prepared.job.close()
        except BaseException as cleanup_error:
            raise CodexChildUnsafeHoldErrorV1(
                "terminal failure cleanup did not settle"
            ) from cleanup_error
        if prepared.ledger.count() != 0:
            raise CodexChildUnsafeHoldErrorV1(
                "terminal failure ledger is not zero"
            ) from terminal_error
        if external_exceptions.error is not None:
            raise external_exceptions.error
        raise
    prepared.job.close()
    if external_exceptions.error is not None:
        if prepared.ledger.count() != 0:
            raise CodexChildUnsafeHoldErrorV1(
                "external interruption ledger is not zero"
            ) from external_exceptions.error
        raise external_exceptions.error
    if committed_unsafe_error is not None:
        raise CodexChildUnsafeHoldErrorV1(
            "committed attempt settled but resource ownership is uncertain"
        ) from committed_unsafe_error
    if prepared.ledger.count() != 0:
        raise CodexChildUnsafeHoldErrorV1("terminal resource ledger is not zero")
    return AttemptTerminalEvidenceV1(
        role=plan.role,
        attempt_ordinal=plan.attempt_ordinal,
        commit_wall_time=commit_wall_time,
        commit_monotonic_ns=commit_monotonic_ns,
        provider_started_monotonic_ns=provider_started_ns,
        attempt_deadline_monotonic_ns=attempt_deadline_ns,
        shared_deadline_monotonic_ns=shared_deadline_ns,
        capture_ready_monotonic_ns=capture_ready_ns,
        exit_code=exit_code,
        mechanical_outcome=outcome,
        events=events,
        final_message=final,
        create_process_calls=create_process_calls,
        stop_calls=stop_calls,
        resource_ledger_count=prepared.ledger.count(),
        lifecycle_facts=tuple(structural_failures),
    )


def run_codex_child_v1(
    plan: FrozenCodexLaunchPlanV1,
    cancellation: CancellationObservationV1,
) -> PreAttemptRejectedV1 | AttemptTerminalEvidenceV1:
    plan = _require_codex_launch_plan_v1(plan, target_kind="production_codex")
    return _run_codex_child_core_v1(plan, cancellation, None)


def _run_codex_child_test_double_v1(
    plan: FrozenCodexLaunchPlanV1,
    cancellation: CancellationObservationV1,
) -> PreAttemptRejectedV1 | AttemptTerminalEvidenceV1:
    plan = _require_codex_launch_plan_v1(plan, target_kind="test_double")
    return _run_codex_child_core_v1(plan, cancellation, None)


def _run_codex_child_with_test_hooks_v1(
    plan: FrozenCodexLaunchPlanV1,
    cancellation: CancellationObservationV1,
    hooks: CodexChildTestHooksV1,
) -> PreAttemptRejectedV1 | AttemptTerminalEvidenceV1:
    if type(hooks) is not CodexChildTestHooksV1:
        raise TypeError("CodexChildTestHooksV1 is required")
    plan = _require_codex_launch_plan_v1(plan, target_kind="test_double")
    return _run_codex_child_core_v1(plan, cancellation, hooks)
