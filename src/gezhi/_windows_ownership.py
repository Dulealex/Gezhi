from __future__ import annotations

import ctypes
import hashlib
import re
import threading
from dataclasses import dataclass
from typing import Literal, Self, TypeAlias

from gezhi._windows_data_root import FileIdentity

_WORK_ID = re.compile(
    r"^wrk_[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_WAIT_OBJECT_0 = 0x00000000
_WAIT_ABANDONED = 0x00000080
_WAIT_TIMEOUT = 0x00000102
_WAIT_FAILED = 0xFFFFFFFF

_KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
_CREATE_MUTEX = _KERNEL32.CreateMutexW
_CREATE_MUTEX.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
_CREATE_MUTEX.restype = ctypes.c_void_p
_WAIT_FOR_SINGLE_OBJECT = _KERNEL32.WaitForSingleObject
_WAIT_FOR_SINGLE_OBJECT.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
_WAIT_FOR_SINGLE_OBJECT.restype = ctypes.c_ulong
_RELEASE_MUTEX = _KERNEL32.ReleaseMutex
_RELEASE_MUTEX.argtypes = [ctypes.c_void_p]
_RELEASE_MUTEX.restype = ctypes.c_int
_CLOSE_HANDLE = _KERNEL32.CloseHandle
_CLOSE_HANDLE.argtypes = [ctypes.c_void_p]
_CLOSE_HANDLE.restype = ctypes.c_int

WriterScope: TypeAlias = Literal[
    "identity_intake",
    "work",
    "catalog_projection",
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
        if type(work_id) is not str or _WORK_ID.fullmatch(work_id) is None:
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


def _mutex_name(
    root_identity: FileIdentity,
    *,
    scope: WriterScope,
    work_id: str | None,
) -> str:
    material = (
        f"{root_identity[0]}:{root_identity[1]}:{scope}:{work_id or '-'}"
    ).encode("ascii")
    return "Global\\Gezhi.Literature.Writer." + hashlib.sha256(material).hexdigest()


def _try_acquire(
    root_identity: FileIdentity,
    *,
    scope: WriterScope,
    work_id: str | None,
) -> WriterOwnershipV1 | None:
    identity = _validated_root_identity(root_identity)
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
                raise WriterOwnershipLifecycleErrorV1(
                    "WaitForSingleObject failed"
                )
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
    if type(work_id) is not str or _WORK_ID.fullmatch(work_id) is None:
        raise ValueError("Work ID is invalid")
    return _try_acquire(
        root_identity,
        scope="work",
        work_id=work_id,
    )


def try_acquire_catalog_projection_v1(
    root_identity: FileIdentity,
) -> WriterOwnershipV1 | None:
    return _try_acquire(
        root_identity,
        scope="catalog_projection",
        work_id=None,
    )
