from __future__ import annotations

import ctypes
import hashlib
import threading
from dataclasses import dataclass
from typing import Literal, Self, TypeAlias

from gezhi._windows_data_root import FileIdentity
from gezhi._work_id import is_work_id_v1

_WAIT_OBJECT_0 = 0x00000000
_WAIT_ABANDONED = 0x00000080
_WAIT_TIMEOUT = 0x00000102
_WAIT_FAILED = 0xFFFFFFFF
_ERROR_FILE_NOT_FOUND = 2
_MUTANT_QUERY_STATE = 0x0001


class _MutantBasicInformationV1(ctypes.Structure):
    _fields_ = (
        ("current_count", ctypes.c_long),
        ("owned_by_caller", ctypes.c_ubyte),
        ("abandoned_state", ctypes.c_ubyte),
    )


_KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
_NTDLL = ctypes.WinDLL("ntdll", use_last_error=True)
_CREATE_MUTEX = _KERNEL32.CreateMutexW
_CREATE_MUTEX.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
_CREATE_MUTEX.restype = ctypes.c_void_p
_OPEN_MUTEX = _KERNEL32.OpenMutexW
_OPEN_MUTEX.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_wchar_p]
_OPEN_MUTEX.restype = ctypes.c_void_p
_WAIT_FOR_SINGLE_OBJECT = _KERNEL32.WaitForSingleObject
_WAIT_FOR_SINGLE_OBJECT.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
_WAIT_FOR_SINGLE_OBJECT.restype = ctypes.c_ulong
_RELEASE_MUTEX = _KERNEL32.ReleaseMutex
_RELEASE_MUTEX.argtypes = [ctypes.c_void_p]
_RELEASE_MUTEX.restype = ctypes.c_int
_CLOSE_HANDLE = _KERNEL32.CloseHandle
_CLOSE_HANDLE.argtypes = [ctypes.c_void_p]
_CLOSE_HANDLE.restype = ctypes.c_int
_NT_QUERY_MUTANT = _NTDLL.NtQueryMutant
_NT_QUERY_MUTANT.argtypes = [
    ctypes.c_void_p,
    ctypes.c_int,
    ctypes.c_void_p,
    ctypes.c_ulong,
    ctypes.POINTER(ctypes.c_ulong),
]
_NT_QUERY_MUTANT.restype = ctypes.c_long

WriterScope: TypeAlias = Literal[
    "identity_intake",
    "work",
    "catalog_projection",
    "knowledge_registry",
    "knowledge_answer",
]
_registry_guard = threading.Lock()
_process_leases: dict[str, int] = {}
_thread_work_leases: dict[int, str] = {}


class WriterOwnershipLifecycleErrorV1(RuntimeError):
    """A writer mutex could not be settled deterministically."""


@dataclass(slots=True)
class WriterOwnershipV1:
    scope: WriterScope
    work_id: str | None
    _name: str
    _handle: int
    _thread_id: int
    _closed: bool = False
    _knowledge_answer_publish_consumed: bool = False
    _knowledge_answer_active_staging_id: str | None = None

    def __enter__(self) -> Self:
        if self._closed:
            raise RuntimeError("writer ownership is closed")
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def assert_work_ownership_v1(
        self,
        root_identity: FileIdentity,
        work_id: str,
    ) -> None:
        """Prove this live token owns one exact Work on the current thread."""

        identity = _validated_root_identity(root_identity)
        if not is_work_id_v1(work_id):
            raise ValueError("Work ID is invalid")
        expected_name = _mutex_name(identity, scope="work", work_id=work_id)
        thread_id = threading.get_ident()
        with _registry_guard:
            if (
                self._closed
                or self.scope != "work"
                or self.work_id != work_id
                or self._name != expected_name
                or self._handle == 0
                or self._thread_id != thread_id
                or _process_leases.get(expected_name) != thread_id
                or _thread_work_leases.get(thread_id) != expected_name
            ):
                raise WriterOwnershipLifecycleErrorV1(
                    "Work writer ownership proof is invalid"
                )

    def assert_knowledge_answer_ownership_v1(
        self,
        root_identity: FileIdentity,
    ) -> None:
        """Prove this live token owns one Knowledge Answer root."""

        identity = _validated_answer_root_identity(root_identity)
        expected_name = _mutex_name(
            identity,
            scope="knowledge_answer",
            work_id=None,
        )
        thread_id = threading.get_ident()
        with _registry_guard:
            if (
                self._closed
                or self.scope != "knowledge_answer"
                or self.work_id is not None
                or self._name != expected_name
                or self._handle == 0
                or self._thread_id != thread_id
                or _process_leases.get(expected_name) != thread_id
            ):
                raise WriterOwnershipLifecycleErrorV1(
                    "Knowledge Answer writer ownership proof is invalid"
                )

    def consume_knowledge_answer_publish_v1(
        self,
        root_identity: FileIdentity,
    ) -> None:
        """Consume the one current-Answer publication allowed by this lease."""

        self.assert_knowledge_answer_ownership_v1(root_identity)
        with _registry_guard:
            if self._knowledge_answer_publish_consumed:
                raise WriterOwnershipLifecycleErrorV1(
                    "Knowledge Answer publication is already consumed"
                )
            self._knowledge_answer_publish_consumed = True

    def bind_knowledge_answer_active_staging_v1(
        self,
        root_identity: FileIdentity,
        answer_id: str,
    ) -> None:
        """Bind this lease's consumed publication to its current staging ID."""

        self.assert_knowledge_answer_ownership_v1(root_identity)
        if type(answer_id) is not str or not answer_id:
            raise ValueError("Knowledge Answer staging identity is invalid")
        with _registry_guard:
            if (
                not self._knowledge_answer_publish_consumed
                or self._knowledge_answer_active_staging_id is not None
            ):
                raise WriterOwnershipLifecycleErrorV1(
                    "Knowledge Answer active staging cannot be rebound"
                )
            self._knowledge_answer_active_staging_id = answer_id

    def assert_knowledge_answer_orphan_ownership_v1(
        self,
        root_identity: FileIdentity,
        answer_id: str,
    ) -> None:
        """Reject the current publication from historical orphan seams."""

        self.assert_knowledge_answer_ownership_v1(root_identity)
        if type(answer_id) is not str or not answer_id:
            raise ValueError("Knowledge Answer orphan identity is invalid")
        with _registry_guard:
            if self._knowledge_answer_active_staging_id == answer_id:
                raise WriterOwnershipLifecycleErrorV1(
                    "current Knowledge Answer staging is not an orphan"
                )

    def close(self) -> None:
        if self._closed:
            return
        if threading.get_ident() != self._thread_id:
            raise RuntimeError("writer ownership belongs to another thread")
        if not _RELEASE_MUTEX(self._handle):
            raise WriterOwnershipLifecycleErrorV1("ReleaseMutex failed")
        close_succeeded = bool(_CLOSE_HANDLE(self._handle))
        with _registry_guard:
            if _process_leases.get(self._name) != self._thread_id:
                raise WriterOwnershipLifecycleErrorV1(
                    "writer ownership registry is inconsistent"
                )
            if self.scope == "work":
                if _thread_work_leases.get(self._thread_id) != self._name:
                    raise WriterOwnershipLifecycleErrorV1(
                        "thread Work ownership registry is inconsistent"
                    )
                del _thread_work_leases[self._thread_id]
            del _process_leases[self._name]
        self._closed = True
        self._handle = 0
        if not close_succeeded:
            raise WriterOwnershipLifecycleErrorV1("CloseHandle failed")

    def __del__(self) -> None:
        if (
            not getattr(self, "_closed", True)
            and getattr(self, "_thread_id", None) == threading.get_ident()
        ):
            try:
                self.close()
            except Exception:  # noqa: BLE001, S110 - destructor is best effort.
                pass


def _validated_root_identity(value: object) -> FileIdentity:
    if (
        type(value) is not tuple
        or len(value) != 2
        or any(type(item) is not int or item <= 0 for item in value)
    ):
        raise ValueError("Data Root identity is invalid")
    return value


def _validated_answer_root_identity(value: object) -> FileIdentity:
    if (
        type(value) is not tuple
        or len(value) != 2
        or type(value[0]) is not int
        or not 0 <= value[0] <= 0xFFFFFFFFFFFFFFFF
        or type(value[1]) is not int
        or not 1 <= value[1] <= (1 << 128) - 1
    ):
        raise ValueError("Knowledge Answer Data Root identity is invalid")
    return value


def _mutex_name(
    root_identity: FileIdentity,
    *,
    scope: WriterScope,
    work_id: str | None,
) -> str:
    if scope == "knowledge_answer":
        identity = _validated_answer_root_identity(root_identity)
        material = (
            b"gezhi.knowledge_answer_writer.v1\x00"
            + identity[0].to_bytes(8, "little", signed=False)
            + identity[1].to_bytes(16, "little", signed=False)
        )
        return (
            "Global\\Gezhi.KnowledgeAnswerWriter.v1."
            + hashlib.sha256(material).hexdigest()
        )
    material = (
        f"{root_identity[0]}:{root_identity[1]}:{scope}:{work_id or '-'}"
    ).encode("ascii")
    context = "Knowledge" if scope == "knowledge_registry" else "Literature"
    return f"Global\\Gezhi.{context}.Writer." + hashlib.sha256(material).hexdigest()


def _try_acquire(
    root_identity: FileIdentity,
    *,
    scope: WriterScope,
    work_id: str | None,
) -> WriterOwnershipV1 | None:
    identity = (
        _validated_answer_root_identity(root_identity)
        if scope == "knowledge_answer"
        else _validated_root_identity(root_identity)
    )
    name = _mutex_name(identity, scope=scope, work_id=work_id)
    thread_id = threading.get_ident()
    with _registry_guard:
        held_work_name = _thread_work_leases.get(thread_id)
        if scope == "work" and held_work_name is not None:
            if held_work_name == name:
                return None
            raise WriterOwnershipLifecycleErrorV1(
                "a thread cannot hold two Work writer ownerships"
            )
        if name in _process_leases:
            return None
        handle = _CREATE_MUTEX(None, False, name)
        if handle in {None, 0}:
            raise WriterOwnershipLifecycleErrorV1("CreateMutexW failed")
        numeric_handle = int(handle)
        verdict = int(_WAIT_FOR_SINGLE_OBJECT(numeric_handle, 0))
        if verdict == _WAIT_TIMEOUT:
            if not _CLOSE_HANDLE(numeric_handle):
                raise WriterOwnershipLifecycleErrorV1("CloseHandle failed")
            return None
        if verdict not in {_WAIT_OBJECT_0, _WAIT_ABANDONED}:
            _CLOSE_HANDLE(numeric_handle)
            if verdict == _WAIT_FAILED:
                raise WriterOwnershipLifecycleErrorV1("WaitForSingleObject failed")
            raise WriterOwnershipLifecycleErrorV1(
                "WaitForSingleObject returned an invalid verdict"
            )
        _process_leases[name] = thread_id
        if scope == "work":
            _thread_work_leases[thread_id] = name
    return WriterOwnershipV1(
        scope=scope,
        work_id=work_id,
        _name=name,
        _handle=numeric_handle,
        _thread_id=thread_id,
    )


def try_acquire_identity_intake_v1(
    root_identity: FileIdentity,
) -> WriterOwnershipV1 | None:
    return _try_acquire(
        root_identity,
        scope="identity_intake",
        work_id=None,
    )


def try_acquire_work_writer_v1(
    root_identity: FileIdentity,
    work_id: str,
) -> WriterOwnershipV1 | None:
    if not is_work_id_v1(work_id):
        raise ValueError("Work ID is invalid")
    return _try_acquire(
        root_identity,
        scope="work",
        work_id=work_id,
    )


def work_writer_is_active_v1(
    root_identity: FileIdentity,
    work_id: str,
) -> bool:
    """Observe one named Work mutex without acquiring or creating it."""

    identity = _validated_root_identity(root_identity)
    if not is_work_id_v1(work_id):
        raise ValueError("Work ID is invalid")
    name = _mutex_name(identity, scope="work", work_id=work_id)
    handle = _OPEN_MUTEX(_MUTANT_QUERY_STATE, False, name)
    if handle in {None, 0}:
        if ctypes.get_last_error() == _ERROR_FILE_NOT_FOUND:
            return False
        raise WriterOwnershipLifecycleErrorV1("OpenMutexW query failed")
    numeric_handle = int(handle)
    information = _MutantBasicInformationV1()
    returned = ctypes.c_ulong(0)
    try:
        status = int(
            _NT_QUERY_MUTANT(
                numeric_handle,
                0,
                ctypes.byref(information),
                ctypes.sizeof(information),
                ctypes.byref(returned),
            )
        )
        if status != 0:
            raise WriterOwnershipLifecycleErrorV1("NtQueryMutant failed")
        if (
            information.current_count > 1
            or information.owned_by_caller not in {0, 1}
            or information.abandoned_state not in {0, 1}
        ):
            raise WriterOwnershipLifecycleErrorV1(
                "Work writer activity observation is invalid"
            )
        active = information.current_count <= 0 and information.abandoned_state == 0
    finally:
        if not _CLOSE_HANDLE(numeric_handle):
            raise WriterOwnershipLifecycleErrorV1("CloseHandle failed")
    return active


def try_acquire_catalog_projection_v1(
    root_identity: FileIdentity,
) -> WriterOwnershipV1 | None:
    return _try_acquire(
        root_identity,
        scope="catalog_projection",
        work_id=None,
    )


def try_acquire_knowledge_registry_writer_v1(
    root_identity: FileIdentity,
) -> WriterOwnershipV1 | None:
    return _try_acquire(
        root_identity,
        scope="knowledge_registry",
        work_id=None,
    )


def try_acquire_knowledge_answer_writer_v1(
    root_identity: FileIdentity,
) -> WriterOwnershipV1 | None:
    return _try_acquire(
        root_identity,
        scope="knowledge_answer",
        work_id=None,
    )
