from __future__ import annotations

import ctypes
import hashlib
import ntpath
import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal, Self, TypeAlias

DataRootStatus: TypeAlias = Literal["ready", "unsafe", "unavailable"]
DataRootOpenCause: TypeAlias = Literal["identity_unavailable"]
FileIdentity: TypeAlias = tuple[int, int]

_DRIVE_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")
_LOCAL_EXTENDED_DRIVE = re.compile(r"^\\\\\?\\[A-Za-z]:[\\/]")
_HARD_DISK_VOLUME = re.compile(r"^\\Device\\HarddiskVolume[0-9]+$")
_DOS_DEVICE_NAME = re.compile(
    r"^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?$",
    re.IGNORECASE,
)

_FILE_ATTRIBUTE_DIRECTORY = 0x10
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_FILE_LIST_DIRECTORY = 0x0001
_FILE_READ_DATA = 0x0001
_FILE_TRAVERSE = 0x0020
_FILE_READ_ATTRIBUTES = 0x0080
_SYNCHRONIZE = 0x00100000
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_OPEN_EXISTING = 3
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_OPEN = 1
_FILE_DIRECTORY_FILE = 0x00000001
_FILE_NON_DIRECTORY_FILE = 0x00000040
_FILE_SYNCHRONOUS_IO_NONALERT = 0x00000020
_FILE_OPEN_REPARSE_POINT = 0x00200000
_OBJ_CASE_INSENSITIVE = 0x00000040
_FILE_ATTRIBUTE_TAG_INFO_CLASS = 9
_FILE_ID_BOTH_DIR_INFO_CLASS = 10
_FILE_ID_BOTH_DIR_RESTART_INFO_CLASS = 11
_FILE_ID_INFO_CLASS = 18
_FILE_NAMED_STREAMS = 0x00040000
_DRIVE_UNKNOWN = 0
_DRIVE_NO_ROOT_DIR = 1
_DRIVE_FIXED = 3
_ERROR_MORE_DATA = 234
_ERROR_NO_MORE_FILES = 18
_ERROR_HANDLE_EOF = 38
_BUFFER_SIZE = 32_768
_DIRECTORY_QUERY_BUFFER = 65_536
_MAX_VOLUME_PATH_BUFFER = 1_048_576
_MAX_ENUMERATED_ENTRIES = 4_096
_MAX_ENUMERATION_DEPTH = 64


class _UNICODE_STRING(ctypes.Structure):
    _fields_ = (
        ("Length", ctypes.c_ushort),
        ("MaximumLength", ctypes.c_ushort),
        ("Buffer", ctypes.POINTER(ctypes.c_wchar)),
    )


class _OBJECT_ATTRIBUTES(ctypes.Structure):
    _fields_ = (
        ("Length", ctypes.c_ulong),
        ("RootDirectory", ctypes.c_void_p),
        ("ObjectName", ctypes.POINTER(_UNICODE_STRING)),
        ("Attributes", ctypes.c_ulong),
        ("SecurityDescriptor", ctypes.c_void_p),
        ("SecurityQualityOfService", ctypes.c_void_p),
    )


class _IO_STATUS_BLOCK_UNION(ctypes.Union):
    _fields_ = (
        ("Status", ctypes.c_long),
        ("Pointer", ctypes.c_void_p),
    )


class _IO_STATUS_BLOCK(ctypes.Structure):
    _fields_ = (
        ("Value", _IO_STATUS_BLOCK_UNION),
        ("Information", ctypes.c_size_t),
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


class _FILE_ID_BOTH_DIR_INFO(ctypes.Structure):
    _fields_ = (
        ("NextEntryOffset", ctypes.c_ulong),
        ("FileIndex", ctypes.c_ulong),
        ("CreationTime", ctypes.c_longlong),
        ("LastAccessTime", ctypes.c_longlong),
        ("LastWriteTime", ctypes.c_longlong),
        ("ChangeTime", ctypes.c_longlong),
        ("EndOfFile", ctypes.c_longlong),
        ("AllocationSize", ctypes.c_longlong),
        ("FileAttributes", ctypes.c_ulong),
        ("FileNameLength", ctypes.c_ulong),
        ("EaSize", ctypes.c_ulong),
        ("ShortNameLength", ctypes.c_byte),
        ("ShortName", ctypes.c_wchar * 12),
        ("FileId", ctypes.c_longlong),
        ("FileName", ctypes.c_wchar * 1),
    )


class _WIN32_FIND_STREAM_DATA(ctypes.Structure):
    _fields_ = (
        ("StreamSize", ctypes.c_longlong),
        ("cStreamName", ctypes.c_wchar * 296),
    )


_KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
_NTDLL = ctypes.WinDLL("ntdll", use_last_error=True)

_GET_DRIVE_TYPE = _KERNEL32.GetDriveTypeW
_GET_DRIVE_TYPE.argtypes = [ctypes.c_wchar_p]
_GET_DRIVE_TYPE.restype = ctypes.c_uint
_GET_LOGICAL_DRIVES = _KERNEL32.GetLogicalDrives
_GET_LOGICAL_DRIVES.argtypes = []
_GET_LOGICAL_DRIVES.restype = ctypes.c_ulong
_QUERY_DOS_DEVICE = _KERNEL32.QueryDosDeviceW
_QUERY_DOS_DEVICE.argtypes = [
    ctypes.c_wchar_p,
    ctypes.c_wchar_p,
    ctypes.c_ulong,
]
_QUERY_DOS_DEVICE.restype = ctypes.c_ulong
_GET_VOLUME_NAME_FOR_VOLUME_MOUNT_POINT = _KERNEL32.GetVolumeNameForVolumeMountPointW
_GET_VOLUME_NAME_FOR_VOLUME_MOUNT_POINT.argtypes = [
    ctypes.c_wchar_p,
    ctypes.c_wchar_p,
    ctypes.c_ulong,
]
_GET_VOLUME_NAME_FOR_VOLUME_MOUNT_POINT.restype = ctypes.c_int
_GET_VOLUME_PATH_NAMES_FOR_VOLUME_NAME = _KERNEL32.GetVolumePathNamesForVolumeNameW
_GET_VOLUME_PATH_NAMES_FOR_VOLUME_NAME.argtypes = [
    ctypes.c_wchar_p,
    ctypes.c_void_p,
    ctypes.c_ulong,
    ctypes.POINTER(ctypes.c_ulong),
]
_GET_VOLUME_PATH_NAMES_FOR_VOLUME_NAME.restype = ctypes.c_int
_CREATE_FILE = _KERNEL32.CreateFileW
_CREATE_FILE.argtypes = [
    ctypes.c_wchar_p,
    ctypes.c_ulong,
    ctypes.c_ulong,
    ctypes.c_void_p,
    ctypes.c_ulong,
    ctypes.c_ulong,
    ctypes.c_void_p,
]
_CREATE_FILE.restype = ctypes.c_void_p
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
_GET_FINAL_PATH_NAME_BY_HANDLE = _KERNEL32.GetFinalPathNameByHandleW
_GET_FINAL_PATH_NAME_BY_HANDLE.argtypes = [
    ctypes.c_void_p,
    ctypes.c_wchar_p,
    ctypes.c_ulong,
    ctypes.c_ulong,
]
_GET_FINAL_PATH_NAME_BY_HANDLE.restype = ctypes.c_ulong
_GET_FILE_SIZE_EX = _KERNEL32.GetFileSizeEx
_GET_FILE_SIZE_EX.argtypes = [
    ctypes.c_void_p,
    ctypes.POINTER(ctypes.c_longlong),
]
_GET_FILE_SIZE_EX.restype = ctypes.c_int
_READ_FILE = _KERNEL32.ReadFile
_READ_FILE.argtypes = [
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_ulong,
    ctypes.POINTER(ctypes.c_ulong),
    ctypes.c_void_p,
]
_READ_FILE.restype = ctypes.c_int
_GET_VOLUME_INFORMATION_BY_HANDLE = _KERNEL32.GetVolumeInformationByHandleW
_GET_VOLUME_INFORMATION_BY_HANDLE.argtypes = [
    ctypes.c_void_p,
    ctypes.c_wchar_p,
    ctypes.c_ulong,
    ctypes.POINTER(ctypes.c_ulong),
    ctypes.POINTER(ctypes.c_ulong),
    ctypes.POINTER(ctypes.c_ulong),
    ctypes.c_wchar_p,
    ctypes.c_ulong,
]
_GET_VOLUME_INFORMATION_BY_HANDLE.restype = ctypes.c_int
_FIND_FIRST_STREAM = _KERNEL32.FindFirstStreamW
_FIND_FIRST_STREAM.argtypes = [
    ctypes.c_wchar_p,
    ctypes.c_int,
    ctypes.POINTER(_WIN32_FIND_STREAM_DATA),
    ctypes.c_ulong,
]
_FIND_FIRST_STREAM.restype = ctypes.c_void_p
_FIND_NEXT_STREAM = _KERNEL32.FindNextStreamW
_FIND_NEXT_STREAM.argtypes = [
    ctypes.c_void_p,
    ctypes.POINTER(_WIN32_FIND_STREAM_DATA),
]
_FIND_NEXT_STREAM.restype = ctypes.c_int
_FIND_CLOSE = _KERNEL32.FindClose
_FIND_CLOSE.argtypes = [ctypes.c_void_p]
_FIND_CLOSE.restype = ctypes.c_int
_NT_CREATE_FILE = _NTDLL.NtCreateFile
_NT_CREATE_FILE.argtypes = [
    ctypes.POINTER(ctypes.c_void_p),
    ctypes.c_ulong,
    ctypes.POINTER(_OBJECT_ATTRIBUTES),
    ctypes.POINTER(_IO_STATUS_BLOCK),
    ctypes.c_void_p,
    ctypes.c_ulong,
    ctypes.c_ulong,
    ctypes.c_ulong,
    ctypes.c_ulong,
    ctypes.c_void_p,
    ctypes.c_ulong,
]
_NT_CREATE_FILE.restype = ctypes.c_long

_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


@dataclass(frozen=True, slots=True)
class DataRootInspectionV1:
    status: DataRootStatus
    canonical_path: str | None = None
    identity: FileIdentity | None = None
    ancestor_identities: tuple[FileIdentity, ...] = ()


@dataclass(frozen=True, slots=True)
class DataRootEntryV1:
    name: str
    is_directory: bool
    is_reparse: bool
    short_name: str | None


@dataclass(frozen=True, slots=True)
class _HandleFacts:
    canonical_path: str
    identity: FileIdentity
    attributes: int


@dataclass(frozen=True, slots=True)
class _DirectoryEntryV1:
    name: str
    attributes: int
    short_name: str | None


class DataRootOpenErrorV1(OSError):
    def __init__(
        self,
        status: DataRootStatus,
        *,
        cause: DataRootOpenCause | None = None,
    ) -> None:
        if cause is not None and (
            status != "unavailable" or cause != "identity_unavailable"
        ):
            raise ValueError("Data Root open cause is invalid")
        detail = f" ({cause})" if cause is not None else ""
        super().__init__(f"Data Root is {status}{detail}")
        self.status = status
        self.cause = cause


class DataRootLifecycleErrorV1(RuntimeError):
    """A Data Root handle could not be settled deterministically."""


class ValidatedFileV1:
    """A root-relative, no-follow file handle and its held parent chain."""

    __slots__ = ("_closed", "_handles", "canonical_path", "identity", "size")

    def __init__(
        self,
        *,
        canonical_path: str,
        identity: FileIdentity,
        size: int,
        handles: tuple[int, ...],
    ) -> None:
        self.canonical_path = canonical_path
        self.identity = identity
        self.size = size
        self._handles = handles
        self._closed = False

    def __enter__(self) -> Self:
        if self._closed:
            raise RuntimeError("validated file is closed")
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def borrowed_handle(self) -> int:
        if self._closed or not self._handles:
            raise RuntimeError("validated file is closed")
        return self._handles[-1]

    def read_bytes_v1(self, *, limit: int) -> bytes:
        if type(limit) is not int or limit < 0:
            raise ValueError("validated file exceeds its read limit")
        handle = self.borrowed_handle()
        try:
            payload = _read_handle_bounded_bytes(handle, limit)
        except ValueError:
            self._revalidate(handle)
            raise
        self._revalidate(handle)
        if len(payload) != self.size:
            raise DataRootOpenErrorV1("unavailable")
        return payload

    def validate_streams_v1(self) -> None:
        handle = self.borrowed_handle()
        _validate_stream_profile_v1(
            handle,
            self.canonical_path,
            directory=False,
        )
        self._revalidate(handle)

    def sha256_v1(self) -> str:
        handle = self.borrowed_handle()
        digest = hashlib.sha256()
        for chunk in _read_handle_chunks(handle, self.size):
            digest.update(chunk)
        self._revalidate(handle)
        return digest.hexdigest()

    def iter_verified_chunks_v1(self) -> Iterator[bytes]:
        """Stream the held file once and revalidate the same handle at EOF."""

        handle = self.borrowed_handle()
        yield from _read_handle_chunks(handle, self.size)
        self._revalidate(handle)

    def revalidate_identity_v1(self) -> None:
        """Prove that a held mutable file still names the same local object."""

        handle = self.borrowed_handle()
        facts = _handle_facts(handle, directory=False)
        if facts.identity != self.identity or _key(facts.canonical_path) != _key(
            self.canonical_path
        ):
            raise DataRootOpenErrorV1("unavailable")

    def _revalidate(self, handle: int) -> None:
        facts = _handle_facts(handle, directory=False)
        if (
            facts.identity != self.identity
            or _key(facts.canonical_path) != _key(self.canonical_path)
            or _file_size(handle) != self.size
        ):
            raise DataRootOpenErrorV1("unavailable")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        handles, self._handles = self._handles, ()
        _close_handles(handles)

    def __del__(self) -> None:
        if not getattr(self, "_closed", True):
            _close_handles_best_effort(getattr(self, "_handles", ()))
            self._handles = ()
            self._closed = True


class ValidatedDataRootV1:
    """A validated root whose full ancestor handle chain remains owned."""

    __slots__ = ("_closed", "_handles", "inspection")

    def __init__(
        self,
        *,
        inspection: DataRootInspectionV1,
        handles: tuple[int, ...],
    ) -> None:
        self.inspection = inspection
        self._handles = handles
        self._closed = False

    def __enter__(self) -> Self:
        if self._closed:
            raise RuntimeError("validated Data Root is closed")
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def borrowed_handle(self) -> int:
        if self._closed or not self._handles:
            raise RuntimeError("validated Data Root is closed")
        return self._handles[-1]

    def open_relative_data_root_v1(
        self,
        parts: tuple[str, ...],
    ) -> ValidatedDataRootV1:
        """Open one no-follow descendant root from this held capability."""

        if self._closed:
            raise RuntimeError("validated Data Root is closed")
        normalized = validate_relative_parts_v1(parts)
        if not normalized:
            raise ValueError("a relative directory path is required")
        expected_root = self.inspection.canonical_path
        root_identity = self.inspection.identity
        if expected_root is None or root_identity is None:
            raise RuntimeError("validated Data Root facts are incomplete")

        held: list[int] = []
        identities: list[FileIdentity] = []
        expected_paths: list[str] = []
        parent = self.borrowed_handle()
        current = expected_root
        try:
            for component in normalized:
                current = ntpath.join(current, component)
                handle = _open_relative_handle(parent, component, directory=True)
                held.append(handle)
                facts = _handle_facts(handle, directory=True)
                _validate_expected_facts(facts, current, root_identity[0])
                _reject_hidden_short_alias(parent, component)
                if facts.identity in {
                    *self.inspection.ancestor_identities,
                    *identities,
                }:
                    raise DataRootOpenErrorV1("unsafe")
                identities.append(facts.identity)
                expected_paths.append(current)
                parent = handle

            parent_handles = (self.borrowed_handle(), *held[:-1])
            final_facts: _HandleFacts | None = None
            for component, expected_path, parent_handle, handle, identity in zip(
                normalized,
                expected_paths,
                parent_handles,
                held,
                identities,
                strict=True,
            ):
                facts = _handle_facts(handle, directory=True)
                _validate_expected_facts(facts, expected_path, root_identity[0])
                _reject_hidden_short_alias(parent_handle, component)
                if facts.identity != identity:
                    raise DataRootOpenErrorV1("unavailable")
                final_facts = facts
            if final_facts is None:
                raise DataRootOpenErrorV1("unavailable")
        except BaseException as error:
            try:
                _close_handles(tuple(held))
            except Exception as close_error:
                raise close_error from error
            raise
        return ValidatedDataRootV1(
            inspection=DataRootInspectionV1(
                status="ready",
                canonical_path=final_facts.canonical_path,
                identity=identities[-1],
                ancestor_identities=(
                    *self.inspection.ancestor_identities,
                    *identities,
                ),
            ),
            handles=tuple(held),
        )

    def open_relative_file_v1(self, parts: tuple[str, ...]) -> ValidatedFileV1:
        if self._closed:
            raise RuntimeError("validated Data Root is closed")
        normalized = validate_relative_parts_v1(parts)
        if not normalized:
            raise ValueError("a relative file path is required")
        expected_root = self.inspection.canonical_path
        root_identity = self.inspection.identity
        if expected_root is None or root_identity is None:
            raise RuntimeError("validated Data Root facts are incomplete")

        held: list[int] = []
        parent = self.borrowed_handle()
        current = expected_root
        try:
            for component in normalized[:-1]:
                current = ntpath.join(current, component)
                handle = _open_relative_handle(parent, component, directory=True)
                held.append(handle)
                facts = _handle_facts(handle, directory=True)
                _validate_expected_facts(facts, current, root_identity[0])
                parent = handle
            current = ntpath.join(current, normalized[-1])
            handle = _open_relative_handle(parent, normalized[-1], directory=False)
            held.append(handle)
            facts = _handle_facts(handle, directory=False)
            _validate_expected_facts(facts, current, root_identity[0])
            size = _file_size(handle)
        except BaseException as error:
            try:
                _close_handles(tuple(held))
            except Exception as close_error:
                raise close_error from error
            raise
        return ValidatedFileV1(
            canonical_path=facts.canonical_path,
            identity=facts.identity,
            size=size,
            handles=tuple(held),
        )

    def relative_entry_names_v1(self) -> tuple[str, ...]:
        """List the held root's immediate, non-reparse children."""

        if self._closed:
            raise RuntimeError("validated Data Root is closed")
        observed: list[str] = []
        for entry in _enumerate_directory(self.borrowed_handle()):
            if len(observed) >= _MAX_ENUMERATED_ENTRIES:
                raise DataRootOpenErrorV1("unavailable")
            if entry.attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
                raise DataRootOpenErrorV1("unsafe")
            observed.append(entry.name)
        return tuple(sorted(observed))

    def relative_entries_v1(self) -> tuple[DataRootEntryV1, ...]:
        """Describe immediate entries without following candidate-local reparses."""

        if self._closed:
            raise RuntimeError("validated Data Root is closed")
        observed: list[DataRootEntryV1] = []
        for entry in _enumerate_directory(self.borrowed_handle()):
            if len(observed) >= _MAX_ENUMERATED_ENTRIES:
                raise DataRootOpenErrorV1("unavailable")
            observed.append(
                DataRootEntryV1(
                    name=entry.name,
                    is_directory=bool(entry.attributes & _FILE_ATTRIBUTE_DIRECTORY),
                    is_reparse=bool(entry.attributes & _FILE_ATTRIBUTE_REPARSE_POINT),
                    short_name=entry.short_name,
                )
            )
        return tuple(sorted(observed, key=lambda item: item.name.encode("utf-8")))

    def validate_streams_v1(self) -> None:
        if self._closed:
            raise RuntimeError("validated Data Root is closed")
        canonical_path = self.inspection.canonical_path
        identity = self.inspection.identity
        if canonical_path is None or identity is None:
            raise RuntimeError("validated Data Root facts are incomplete")
        handle = self.borrowed_handle()
        _validate_stream_profile_v1(handle, canonical_path, directory=True)
        facts = _handle_facts(handle, directory=True)
        if facts.identity != identity or _key(facts.canonical_path) != _key(
            canonical_path
        ):
            raise DataRootOpenErrorV1("unavailable")

    def relative_file_paths_v1(self) -> tuple[str, ...]:
        if self._closed:
            raise RuntimeError("validated Data Root is closed")
        observed: list[str] = []
        self._walk_directory(
            self.borrowed_handle(),
            (),
            observed,
            [0],
            depth=0,
        )
        return tuple(sorted(observed))

    def _walk_directory(
        self,
        directory_handle: int,
        prefix: tuple[str, ...],
        observed: list[str],
        entry_count: list[int],
        *,
        depth: int,
    ) -> None:
        if depth > _MAX_ENUMERATION_DEPTH:
            raise DataRootOpenErrorV1("unavailable")
        for entry in _enumerate_directory(directory_handle):
            name = entry.name
            attributes = entry.attributes
            entry_count[0] += 1
            if entry_count[0] > _MAX_ENUMERATED_ENTRIES:
                raise DataRootOpenErrorV1("unavailable")
            if attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
                raise DataRootOpenErrorV1("unsafe")
            child_prefix = (*prefix, name)
            if attributes & _FILE_ATTRIBUTE_DIRECTORY:
                child = _open_relative_handle(
                    directory_handle,
                    name,
                    directory=True,
                )
                try:
                    _handle_facts(child, directory=True)
                    self._walk_directory(
                        child,
                        child_prefix,
                        observed,
                        entry_count,
                        depth=depth + 1,
                    )
                finally:
                    _close_handles((child,))
            else:
                observed.append("/".join(child_prefix))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        handles, self._handles = self._handles, ()
        _close_handles(handles)

    def __del__(self) -> None:
        if not getattr(self, "_closed", True):
            _close_handles_best_effort(getattr(self, "_handles", ()))
            self._handles = ()
            self._closed = True


def data_roots_are_physically_isolated(
    literature: DataRootInspectionV1,
    knowledge: DataRootInspectionV1,
) -> bool:
    if (
        literature.status != "ready"
        or knowledge.status != "ready"
        or literature.identity is None
        or knowledge.identity is None
    ):
        raise ValueError("physical isolation requires two ready Data Roots")
    return (
        literature.identity not in knowledge.ancestor_identities
        and knowledge.identity not in literature.ancestor_identities
    )


def data_root_does_not_physically_contain_project(
    data_root: DataRootInspectionV1,
    project_root: DataRootInspectionV1,
) -> bool:
    if (
        data_root.status != "ready"
        or project_root.status != "ready"
        or data_root.identity is None
        or project_root.identity is None
    ):
        raise ValueError("project boundary requires two ready identities")
    return data_root.identity not in project_root.ancestor_identities


def _is_safe_component(value: str) -> bool:
    try:
        utf16_length = len(value.encode("utf-16-le"))
    except UnicodeEncodeError:
        return False
    return not (
        not value
        or utf16_length > 510
        or value in {".", ".."}
        or value[-1] in {" ", "."}
        or any(ord(character) < 32 for character in value)
        or any(character in '<>:"/\\|?*' for character in value)
        or _DOS_DEVICE_NAME.fullmatch(value) is not None
    )


def _normal_path(value: str) -> str | None:
    if type(value) is not str or "\x00" in value:
        return None
    candidate = value
    if _LOCAL_EXTENDED_DRIVE.match(candidate):
        candidate = candidate[4:]
    elif not _DRIVE_ABSOLUTE.match(candidate):
        return None
    candidate = candidate.replace("/", "\\")
    if ":" in candidate[2:]:
        return None
    drive, tail = ntpath.splitdrive(candidate)
    parts: list[str] = []
    for component in tail.split("\\"):
        if not component or component == ".":
            continue
        if component == "..":
            if not parts:
                return None
            parts.pop()
            continue
        if not _is_safe_component(component):
            return None
        parts.append(component)
    root = drive.upper() + "\\"
    normalized = ntpath.join(root, *parts) if parts else root
    try:
        if len(normalized.encode("utf-16-le")) > 65_532:
            return None
    except UnicodeEncodeError:
        return None
    return normalized


def normalize_local_path_v1(value: str) -> str | None:
    """Return the supported local DOS spelling without performing I/O."""

    return _normal_path(value)


def validate_relative_parts_v1(parts: tuple[str, ...]) -> tuple[str, ...]:
    """Validate an exact root-relative component tuple without performing I/O."""

    if type(parts) is not tuple or any(
        type(component) is not str or not _is_safe_component(component)
        for component in parts
    ):
        raise ValueError("relative path is unsafe")
    return parts


def _key(value: str) -> str:
    return ntpath.normpath(value.replace("/", "\\")).casefold()


def _query_dos_device_targets(drive: str) -> tuple[str, ...] | None:
    buffer = ctypes.create_unicode_buffer(_BUFFER_SIZE)
    count = _QUERY_DOS_DEVICE(drive, buffer, _BUFFER_SIZE)
    if count == 0:
        return None
    return tuple(item for item in "".join(buffer[:count]).split("\x00") if item)


def _volume_path_names(volume_name: str) -> tuple[str, ...] | None:
    required = ctypes.c_ulong()
    ctypes.set_last_error(0)
    first = _GET_VOLUME_PATH_NAMES_FOR_VOLUME_NAME(
        volume_name,
        None,
        0,
        ctypes.byref(required),
    )
    if not first and ctypes.get_last_error() != _ERROR_MORE_DATA:
        return None
    if not 2 <= required.value <= _MAX_VOLUME_PATH_BUFFER:
        return None
    buffer = ctypes.create_unicode_buffer(required.value)
    returned = ctypes.c_ulong()
    if not _GET_VOLUME_PATH_NAMES_FOR_VOLUME_NAME(
        volume_name,
        buffer,
        required.value,
        ctypes.byref(returned),
    ):
        return None
    if not 2 <= returned.value <= required.value:
        return None
    return tuple(
        item for item in "".join(buffer[: returned.value]).split("\x00") if item
    )


def _volume_is_supported(path: str) -> DataRootStatus | None:
    drive, _tail = ntpath.splitdrive(path)
    drive_root = drive + "\\"
    drive_type = _GET_DRIVE_TYPE(drive_root)
    if drive_type in {_DRIVE_UNKNOWN, _DRIVE_NO_ROOT_DIR}:
        return "unavailable"
    if drive_type != _DRIVE_FIXED:
        return "unsafe"

    device_targets = _query_dos_device_targets(drive)
    if device_targets is None:
        return "unavailable"
    if (
        len(device_targets) != 1
        or _HARD_DISK_VOLUME.fullmatch(device_targets[0]) is None
    ):
        return "unsafe"

    logical_drives = _GET_LOGICAL_DRIVES()
    if logical_drives == 0:
        return "unavailable"
    drive_index = ord(drive[0].upper()) - ord("A")
    if not logical_drives & (1 << drive_index):
        return "unavailable"
    device_key = device_targets[0].casefold()
    for index in range(26):
        if index == drive_index or not logical_drives & (1 << index):
            continue
        other_targets = _query_dos_device_targets(f"{chr(ord('A') + index)}:")
        if other_targets is None:
            return "unavailable"
        if any(target.casefold() == device_key for target in other_targets):
            return "unsafe"

    volume_name_buffer = ctypes.create_unicode_buffer(_BUFFER_SIZE)
    if not _GET_VOLUME_NAME_FOR_VOLUME_MOUNT_POINT(
        drive_root,
        volume_name_buffer,
        _BUFFER_SIZE,
    ):
        return "unavailable"
    volume_paths = _volume_path_names(volume_name_buffer.value)
    if volume_paths is None:
        return "unavailable"
    if len(volume_paths) != 1 or _key(volume_paths[0]) != _key(drive_root):
        return "unsafe"
    return None


def _parent_chain(path: str) -> tuple[str, ...]:
    drive, tail = ntpath.splitdrive(path)
    current = drive + "\\"
    chain = [current]
    for component in (part for part in tail.split("\\") if part):
        current = ntpath.join(current, component)
        chain.append(current)
    return tuple(chain)


def _open_drive_root(path: str) -> int:
    handle = _CREATE_FILE(
        "\\\\?\\" + path,
        _FILE_LIST_DIRECTORY | _FILE_TRAVERSE | _FILE_READ_ATTRIBUTES | _SYNCHRONIZE,
        _FILE_SHARE_READ | _FILE_SHARE_WRITE,
        None,
        _OPEN_EXISTING,
        _FILE_FLAG_BACKUP_SEMANTICS | _FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    if handle in {None, 0, _INVALID_HANDLE_VALUE}:
        raise DataRootOpenErrorV1("unavailable")
    return int(handle)


def _nt_open_relative(
    parent: int,
    component: str,
    *,
    desired_access: int,
    share: int,
    options: int,
) -> int:
    if not _is_safe_component(component):
        raise DataRootOpenErrorV1("unsafe")
    encoded_name = component.encode("utf-16-le")
    name_buffer = ctypes.create_unicode_buffer(component)
    name = _UNICODE_STRING(
        Length=len(encoded_name),
        MaximumLength=ctypes.sizeof(name_buffer),
        Buffer=ctypes.cast(name_buffer, ctypes.POINTER(ctypes.c_wchar)),
    )
    attributes = _OBJECT_ATTRIBUTES(
        Length=ctypes.sizeof(_OBJECT_ATTRIBUTES),
        RootDirectory=parent,
        ObjectName=ctypes.pointer(name),
        Attributes=_OBJ_CASE_INSENSITIVE,
        SecurityDescriptor=None,
        SecurityQualityOfService=None,
    )
    io_status = _IO_STATUS_BLOCK()
    handle = ctypes.c_void_p()
    status = _NT_CREATE_FILE(
        ctypes.byref(handle),
        desired_access,
        ctypes.byref(attributes),
        ctypes.byref(io_status),
        None,
        0,
        share,
        _FILE_OPEN,
        options,
        None,
        0,
    )
    if status < 0 or handle.value in {None, 0, _INVALID_HANDLE_VALUE}:
        raise DataRootOpenErrorV1("unavailable")
    return int(handle.value)


def _open_relative_handle(
    parent: int,
    component: str,
    *,
    directory: bool,
    share_writes: bool = False,
) -> int:
    share = (
        _FILE_SHARE_READ | _FILE_SHARE_WRITE
        if directory or share_writes
        else _FILE_SHARE_READ
    )
    base_options = _FILE_SYNCHRONOUS_IO_NONALERT | _FILE_OPEN_REPARSE_POINT
    probe = _nt_open_relative(
        parent,
        component,
        desired_access=_FILE_READ_ATTRIBUTES | _SYNCHRONIZE,
        share=share,
        options=base_options,
    )
    opened: list[int] = [probe]
    try:
        probe_facts = _handle_facts(probe, directory=directory)
        desired_access = _FILE_READ_ATTRIBUTES | _SYNCHRONIZE
        options = base_options
        if directory:
            desired_access |= _FILE_LIST_DIRECTORY | _FILE_TRAVERSE
            options |= _FILE_DIRECTORY_FILE
        else:
            desired_access |= _FILE_READ_DATA
            options |= _FILE_NON_DIRECTORY_FILE
        handle = _nt_open_relative(
            parent,
            component,
            desired_access=desired_access,
            share=share,
            options=options,
        )
        opened.append(handle)
        typed_facts = _handle_facts(handle, directory=directory)
        if typed_facts.identity != probe_facts.identity or _key(
            typed_facts.canonical_path
        ) != _key(probe_facts.canonical_path):
            raise DataRootOpenErrorV1("unavailable")
    except BaseException as error:
        try:
            _close_handles(tuple(opened))
        except Exception as close_error:
            raise close_error from error
        raise
    try:
        _close_handles((probe,))
    except Exception as error:
        try:
            _close_handles((handle,))
        except Exception as close_error:
            raise close_error from error
        raise
    return handle


def _identity_from_file_id_info(value: _FILE_ID_INFO) -> FileIdentity:
    identifier = int.from_bytes(bytes(value.FileId.Identifier), "little")
    if identifier == 0:
        raise DataRootOpenErrorV1(
            "unavailable",
            cause="identity_unavailable",
        )
    return int(value.VolumeSerialNumber), identifier


def _handle_final_path(handle: int) -> str:
    buffer = ctypes.create_unicode_buffer(_BUFFER_SIZE)
    count = _GET_FINAL_PATH_NAME_BY_HANDLE(handle, buffer, _BUFFER_SIZE, 0)
    if count == 0 or count >= _BUFFER_SIZE:
        raise DataRootOpenErrorV1("unavailable")
    normalized = _normal_path(buffer.value)
    if normalized is None:
        raise DataRootOpenErrorV1("unsafe")
    return normalized


def _handle_facts(handle: int, *, directory: bool) -> _HandleFacts:
    attributes = _FILE_ATTRIBUTE_TAG_INFO()
    if not _GET_FILE_INFORMATION_BY_HANDLE_EX(
        handle,
        _FILE_ATTRIBUTE_TAG_INFO_CLASS,
        ctypes.byref(attributes),
        ctypes.sizeof(attributes),
    ):
        raise DataRootOpenErrorV1("unavailable")
    if attributes.FileAttributes & _FILE_ATTRIBUTE_REPARSE_POINT:
        raise DataRootOpenErrorV1("unsafe")
    is_directory = bool(attributes.FileAttributes & _FILE_ATTRIBUTE_DIRECTORY)
    if is_directory is not directory:
        raise DataRootOpenErrorV1("unavailable")

    file_id = _FILE_ID_INFO()
    if not _GET_FILE_INFORMATION_BY_HANDLE_EX(
        handle,
        _FILE_ID_INFO_CLASS,
        ctypes.byref(file_id),
        ctypes.sizeof(file_id),
    ):
        raise DataRootOpenErrorV1(
            "unavailable",
            cause="identity_unavailable",
        )
    return _HandleFacts(
        canonical_path=_handle_final_path(handle),
        identity=_identity_from_file_id_info(file_id),
        attributes=int(attributes.FileAttributes),
    )


def _validate_expected_facts(
    facts: _HandleFacts,
    expected_path: str,
    volume_serial: int,
) -> None:
    if _key(facts.canonical_path) != _key(expected_path):
        raise DataRootOpenErrorV1("unsafe")
    if facts.identity[0] != volume_serial:
        raise DataRootOpenErrorV1("unsafe")


def _file_size(handle: int) -> int:
    size = ctypes.c_longlong()
    if not _GET_FILE_SIZE_EX(handle, ctypes.byref(size)) or size.value < 0:
        raise DataRootOpenErrorV1("unavailable")
    return int(size.value)


def _read_handle_chunks(handle: int, expected_size: int):  # type: ignore[no-untyped-def]
    buffer = ctypes.create_string_buffer(1024 * 1024)
    total = 0
    while True:
        read = ctypes.c_ulong()
        if not _READ_FILE(
            handle,
            buffer,
            len(buffer),
            ctypes.byref(read),
            None,
        ):
            raise DataRootOpenErrorV1("unavailable")
        count = int(read.value)
        if count == 0:
            break
        total += count
        if total > expected_size:
            raise DataRootOpenErrorV1("unavailable")
        yield buffer.raw[:count]
    if total != expected_size:
        raise DataRootOpenErrorV1("unavailable")


def _read_handle_bounded_bytes(handle: int, limit: int) -> bytes:
    buffer = ctypes.create_string_buffer(min(1024 * 1024, max(1, limit + 1)))
    chunks: list[bytes] = []
    total = 0
    while True:
        requested = min(len(buffer), limit + 1 - total)
        read = ctypes.c_ulong()
        if not _READ_FILE(
            handle,
            buffer,
            requested,
            ctypes.byref(read),
            None,
        ):
            raise DataRootOpenErrorV1("unavailable")
        count = int(read.value)
        if not 0 <= count <= requested:
            raise DataRootOpenErrorV1("unavailable")
        if count == 0:
            return b"".join(chunks)
        chunks.append(buffer.raw[:count])
        total += count
        if total > limit:
            raise ValueError("validated file exceeds its read limit")


def _validate_stream_profile_v1(
    handle: int,
    canonical_path: str,
    *,
    directory: bool,
) -> None:
    filesystem_flags = ctypes.c_ulong()
    if not _GET_VOLUME_INFORMATION_BY_HANDLE(
        handle,
        None,
        0,
        None,
        None,
        ctypes.byref(filesystem_flags),
        None,
        0,
    ):
        raise DataRootOpenErrorV1("unavailable")
    if not filesystem_flags.value & _FILE_NAMED_STREAMS:
        return

    stream_data = _WIN32_FIND_STREAM_DATA()
    ctypes.set_last_error(0)
    search = _FIND_FIRST_STREAM(
        "\\\\?\\" + canonical_path,
        0,
        ctypes.byref(stream_data),
        0,
    )
    if search in {None, 0, _INVALID_HANDLE_VALUE}:
        if ctypes.get_last_error() == _ERROR_HANDLE_EOF and directory:
            return
        raise DataRootOpenErrorV1("unavailable")

    close_failed = False
    try:
        if directory or stream_data.cStreamName != "::$DATA":
            raise DataRootOpenErrorV1("unsafe")
        ctypes.set_last_error(0)
        if _FIND_NEXT_STREAM(search, ctypes.byref(stream_data)):
            raise DataRootOpenErrorV1("unsafe")
        if ctypes.get_last_error() != _ERROR_HANDLE_EOF:
            raise DataRootOpenErrorV1("unavailable")
    finally:
        close_failed = not bool(_FIND_CLOSE(search))
    if close_failed:
        raise DataRootOpenErrorV1("unavailable")


def _enumerate_directory(handle: int) -> tuple[_DirectoryEntryV1, ...]:
    observed: list[_DirectoryEntryV1] = []
    information_class = _FILE_ID_BOTH_DIR_RESTART_INFO_CLASS
    while True:
        buffer = ctypes.create_string_buffer(_DIRECTORY_QUERY_BUFFER)
        ctypes.set_last_error(0)
        succeeded = _GET_FILE_INFORMATION_BY_HANDLE_EX(
            handle,
            information_class,
            buffer,
            len(buffer),
        )
        information_class = _FILE_ID_BOTH_DIR_INFO_CLASS
        if not succeeded:
            if ctypes.get_last_error() == _ERROR_NO_MORE_FILES:
                return tuple(observed)
            raise DataRootOpenErrorV1("unavailable")

        offset = 0
        while True:
            minimum = _FILE_ID_BOTH_DIR_INFO.FileName.offset
            if offset < 0 or offset + minimum > len(buffer):
                raise DataRootOpenErrorV1("unavailable")
            entry = _FILE_ID_BOTH_DIR_INFO.from_buffer(buffer, offset)
            name_length = int(entry.FileNameLength)
            short_name_length = int(entry.ShortNameLength)
            character_size = ctypes.sizeof(ctypes.c_wchar)
            if (
                name_length <= 0
                or name_length % character_size != 0
                or offset + minimum + name_length > len(buffer)
                or short_name_length < 0
                or short_name_length > ctypes.sizeof(ctypes.c_wchar * 12)
                or short_name_length % character_size != 0
            ):
                raise DataRootOpenErrorV1("unavailable")
            name = ctypes.wstring_at(
                ctypes.addressof(buffer) + offset + minimum,
                name_length // character_size,
            )
            short_name = (
                None
                if short_name_length == 0
                else ctypes.wstring_at(
                    ctypes.addressof(buffer)
                    + offset
                    + _FILE_ID_BOTH_DIR_INFO.ShortName.offset,
                    short_name_length // character_size,
                )
            )
            if name not in {".", ".."}:
                if not _is_safe_component(name) or (
                    short_name is not None and not _is_safe_component(short_name)
                ):
                    raise DataRootOpenErrorV1("unsafe")
                observed.append(
                    _DirectoryEntryV1(
                        name=name,
                        attributes=int(entry.FileAttributes),
                        short_name=short_name,
                    )
                )
                if len(observed) > _MAX_ENUMERATED_ENTRIES:
                    raise DataRootOpenErrorV1("unavailable")
            next_offset = int(entry.NextEntryOffset)
            if next_offset == 0:
                break
            if next_offset < minimum or offset + next_offset >= len(buffer):
                raise DataRootOpenErrorV1("unavailable")
            offset += next_offset


def _reject_hidden_short_alias(parent: int, component: str) -> None:
    matches = tuple(
        entry
        for entry in _enumerate_directory(parent)
        if entry.name.casefold() == component.casefold()
    )
    if len(matches) != 1:
        raise DataRootOpenErrorV1("unavailable")
    if matches[0].short_name is not None:
        raise DataRootOpenErrorV1("unsafe")


def _close_handles(handles: tuple[int, ...]) -> None:
    first_error: int | None = None
    for handle in reversed(handles):
        if not _CLOSE_HANDLE(handle) and first_error is None:
            first_error = ctypes.get_last_error()
    if first_error is not None:
        raise DataRootLifecycleErrorV1(f"CloseHandle failed (Win32 {first_error})")


def _close_handles_best_effort(handles: tuple[int, ...]) -> None:
    for handle in reversed(handles):
        try:
            _CLOSE_HANDLE(handle)
        except Exception:  # noqa: BLE001, S110 - destructor rollback is best effort.
            pass


def open_validated_data_root_v1(value: str) -> ValidatedDataRootV1:
    path = _normal_path(value)
    if path is None:
        raise DataRootOpenErrorV1("unsafe")
    volume_status = _volume_is_supported(path)
    if volume_status is not None:
        raise DataRootOpenErrorV1(volume_status)

    handles: list[int] = []
    identities: list[FileIdentity] = []
    chain = _parent_chain(path)
    try:
        for index, expected_path in enumerate(chain):
            if index == 0:
                handle = _open_drive_root(expected_path)
            else:
                parent = handles[-1]
                component = ntpath.basename(expected_path)
                handle = _open_relative_handle(
                    parent,
                    component,
                    directory=True,
                )
            handles.append(handle)
            facts = _handle_facts(handle, directory=True)
            if index == 0:
                volume_serial = facts.identity[0]
            _validate_expected_facts(facts, expected_path, volume_serial)
            if index != 0:
                _reject_hidden_short_alias(parent, component)
            if facts.identity in identities:
                raise DataRootOpenErrorV1("unsafe")
            identities.append(facts.identity)

        final_facts: _HandleFacts | None = None
        for index, (expected_path, handle, identity) in enumerate(
            zip(chain, handles, identities, strict=True)
        ):
            facts = _handle_facts(handle, directory=True)
            _validate_expected_facts(facts, expected_path, identities[0][0])
            if index != 0:
                _reject_hidden_short_alias(
                    handles[index - 1],
                    ntpath.basename(expected_path),
                )
            if facts.identity != identity:
                raise DataRootOpenErrorV1("unavailable")
            final_facts = facts
        volume_status = _volume_is_supported(path)
        if volume_status is not None:
            raise DataRootOpenErrorV1(volume_status)
        if final_facts is None:
            raise DataRootOpenErrorV1("unavailable")
        inspection = DataRootInspectionV1(
            status="ready",
            canonical_path=final_facts.canonical_path,
            identity=identities[-1],
            ancestor_identities=tuple(identities),
        )
        return ValidatedDataRootV1(
            inspection=inspection,
            handles=tuple(handles),
        )
    except BaseException as error:
        try:
            _close_handles(tuple(handles))
        except Exception as close_error:
            raise close_error from error
        raise


def _open_validated_local_file_v1(
    value: str,
    *,
    share_writes: bool,
) -> ValidatedFileV1:

    path = _normal_path(value)
    if path is None:
        raise DataRootOpenErrorV1("unsafe")
    volume_status = _volume_is_supported(path)
    if volume_status is not None:
        raise DataRootOpenErrorV1(volume_status)

    handles: list[int] = []
    identities: list[FileIdentity] = []
    chain = _parent_chain(path)
    if len(chain) < 2:
        raise DataRootOpenErrorV1("unavailable")
    last_index = len(chain) - 1
    try:
        for index, expected_path in enumerate(chain):
            directory = index != last_index
            if index == 0:
                handle = _open_drive_root(expected_path)
            else:
                parent = handles[-1]
                component = ntpath.basename(expected_path)
                handle = _open_relative_handle(
                    parent,
                    component,
                    directory=directory,
                    share_writes=share_writes and not directory,
                )
            handles.append(handle)
            facts = _handle_facts(handle, directory=directory)
            if index == 0:
                volume_serial = facts.identity[0]
            _validate_expected_facts(facts, expected_path, volume_serial)
            if index != 0:
                _reject_hidden_short_alias(parent, component)
            if facts.identity in identities:
                raise DataRootOpenErrorV1("unsafe")
            identities.append(facts.identity)

        final_facts: _HandleFacts | None = None
        for index, (expected_path, handle, identity) in enumerate(
            zip(chain, handles, identities, strict=True)
        ):
            directory = index != last_index
            facts = _handle_facts(handle, directory=directory)
            _validate_expected_facts(facts, expected_path, identities[0][0])
            if index != 0:
                _reject_hidden_short_alias(
                    handles[index - 1],
                    ntpath.basename(expected_path),
                )
            if facts.identity != identity:
                raise DataRootOpenErrorV1("unavailable")
            final_facts = facts
        volume_status = _volume_is_supported(path)
        if volume_status is not None:
            raise DataRootOpenErrorV1(volume_status)
        if final_facts is None:
            raise DataRootOpenErrorV1("unavailable")
        return ValidatedFileV1(
            canonical_path=final_facts.canonical_path,
            identity=final_facts.identity,
            size=_file_size(handles[-1]),
            handles=tuple(handles),
        )
    except BaseException as error:
        try:
            _close_handles(tuple(handles))
        except Exception as close_error:
            raise close_error from error
        raise


def open_validated_local_file_v1(value: str) -> ValidatedFileV1:
    """Open one stable local file through a held no-follow ancestor chain."""

    return _open_validated_local_file_v1(value, share_writes=False)


def open_validated_mutable_local_file_v1(value: str) -> ValidatedFileV1:
    """Hold one no-follow local file while a cooperating writer mutates it."""

    return _open_validated_local_file_v1(value, share_writes=True)


def inspect_data_root_v1(value: str) -> DataRootInspectionV1:
    try:
        capability = open_validated_data_root_v1(value)
    except DataRootOpenErrorV1 as error:
        return DataRootInspectionV1(status=error.status)
    with capability:
        return capability.inspection
