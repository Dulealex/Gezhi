from __future__ import annotations

import ctypes
import hashlib
import ntpath
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from gezhi import _windows_data_root as windows_root
from gezhi._windows_data_root import (
    DataRootInspectionV1,
    data_root_does_not_physically_contain_project,
    data_roots_are_physically_isolated,
    inspect_data_root_v1,
    open_validated_data_root_v1,
    open_validated_local_file_v1,
)


def test_existing_local_directory_has_a_stable_ready_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "literature"
    data_root.mkdir()
    monkeypatch.setattr(
        windows_root,
        "_reject_hidden_short_alias",
        lambda _parent, _component: None,
    )

    inspection = inspect_data_root_v1(str(data_root))

    assert (
        inspection.status,
        inspection.identity is not None,
        inspection.canonical_path,
    ) == ("ready", True, str(data_root))


def test_local_file_is_opened_no_follow_and_streamed_from_one_held_handle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "paper.pdf"
    payload = b"%PDF-1.7\n" + b"x" * (1024 * 1024 + 7)
    source.write_bytes(payload)
    monkeypatch.setattr(
        windows_root,
        "_reject_hidden_short_alias",
        lambda _parent, _component: None,
    )

    with open_validated_local_file_v1(str(source)) as opened:
        original_identity = opened.identity
        chunks = tuple(opened.iter_verified_chunks_v1())
        assert opened.size == len(payload)
        assert opened.identity == original_identity

    assert b"".join(chunks) == payload
    assert hashlib.sha256(b"".join(chunks)).hexdigest() == hashlib.sha256(
        payload
    ).hexdigest()


@pytest.mark.parametrize(
    "value",
    [
        r"relative\paper.pdf",
        r"\\server\share\paper.pdf",
        r"\\?\Volume{00000000-0000-0000-0000-000000000000}\paper.pdf",
        r"E:\paper.pdf:stream",
    ],
)
def test_local_file_rejects_unsupported_namespaces(value: str) -> None:
    with pytest.raises(windows_root.DataRootOpenErrorV1) as raised:
        open_validated_local_file_v1(value)

    assert raised.value.status == "unsafe"


def test_non_bmp_components_use_their_actual_utf16_length(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "😀😀"
    data_root.mkdir()
    monkeypatch.setattr(
        windows_root,
        "_reject_hidden_short_alias",
        lambda _parent, _component: None,
    )

    assert inspect_data_root_v1(str(data_root)).status == "ready"


def test_validated_root_owns_the_final_handle_and_closes_it_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "literature"
    data_root.mkdir()
    monkeypatch.setattr(
        windows_root,
        "_reject_hidden_short_alias",
        lambda _parent, _component: None,
    )
    closed: list[int] = []
    real_close = windows_root._CLOSE_HANDLE

    def close_once(handle: int) -> int:
        closed.append(int(handle))
        return real_close(handle)

    monkeypatch.setattr(windows_root, "_CLOSE_HANDLE", close_once)

    with open_validated_data_root_v1(str(data_root)) as capability:
        final_handle = capability.borrowed_handle()
        assert final_handle not in closed
        assert capability.inspection.status == "ready"
        assert capability.inspection.identity is not None
        assert capability.inspection.identity[1].bit_length() <= 128

    assert closed.count(final_handle) == 1
    with pytest.raises(RuntimeError, match="closed"):
        capability.borrowed_handle()


def test_validated_root_opens_and_enumerates_one_held_relative_subroot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtimes" / "codex"
    (runtime / "vendor" / "bin").mkdir(parents=True)
    (runtime / "package.json").write_text("{}", encoding="utf-8")
    (runtime / "vendor" / "bin" / "codex.exe").write_bytes(b"exe")
    (tmp_path / "outside.txt").write_text("outside", encoding="utf-8")
    monkeypatch.setattr(
        windows_root,
        "_reject_hidden_short_alias",
        lambda _parent, _component: None,
    )

    with open_validated_data_root_v1(str(tmp_path)) as project:
        project_handle = project.borrowed_handle()
        with project.open_relative_data_root_v1(("runtimes", "codex")) as child:
            child_handle = child.borrowed_handle()
            assert child_handle != project_handle
            assert child.inspection.canonical_path == str(runtime)
            assert child.relative_file_paths_v1() == (
                "package.json",
                "vendor/bin/codex.exe",
            )
        with pytest.raises(RuntimeError, match="closed"):
            child.borrowed_handle()
        assert project.borrowed_handle() == project_handle


def test_relative_subroot_closes_a_partial_chain_when_opening_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = windows_root.ValidatedDataRootV1(
        inspection=DataRootInspectionV1(
            status="ready",
            canonical_path=r"D:\Root",
            identity=(7, 11),
            ancestor_identities=((7, 11),),
        ),
        handles=(1,),
    )
    closed: list[tuple[int, ...]] = []

    def open_child(_parent: int, component: str, *, directory: bool) -> int:
        assert directory
        if component == "runtime":
            return 2
        raise windows_root.DataRootOpenErrorV1("unavailable")

    monkeypatch.setattr(windows_root, "_open_relative_handle", open_child)
    monkeypatch.setattr(
        windows_root,
        "_handle_facts",
        lambda _handle, *, directory: SimpleNamespace(
            canonical_path=r"D:\Root\runtime",
            identity=(7, 13),
            attributes=windows_root._FILE_ATTRIBUTE_DIRECTORY,
        ),
    )
    monkeypatch.setattr(
        windows_root,
        "_reject_hidden_short_alias",
        lambda _parent, _component: None,
    )
    monkeypatch.setattr(
        windows_root,
        "_close_handles",
        lambda handles: closed.append(handles),
    )

    with pytest.raises(windows_root.DataRootOpenErrorV1):
        root.open_relative_data_root_v1(("runtime", "native"))

    assert closed == [(2,)]
    root._handles = ()
    root._closed = True


def test_relative_subroot_surfaces_cleanup_failure_over_open_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = windows_root.ValidatedDataRootV1(
        inspection=DataRootInspectionV1(
            status="ready",
            canonical_path=r"D:\Root",
            identity=(7, 11),
            ancestor_identities=((7, 11),),
        ),
        handles=(1,),
    )

    def open_child(_parent: int, component: str, *, directory: bool) -> int:
        assert directory
        if component == "runtime":
            return 2
        raise windows_root.DataRootOpenErrorV1("unavailable")

    monkeypatch.setattr(windows_root, "_open_relative_handle", open_child)
    monkeypatch.setattr(
        windows_root,
        "_handle_facts",
        lambda _handle, *, directory: SimpleNamespace(
            canonical_path=r"D:\Root\runtime",
            identity=(7, 13),
            attributes=windows_root._FILE_ATTRIBUTE_DIRECTORY,
        ),
    )
    monkeypatch.setattr(
        windows_root,
        "_reject_hidden_short_alias",
        lambda _parent, _component: None,
    )
    monkeypatch.setattr(
        windows_root,
        "_close_handles",
        lambda _handles: (_ for _ in ()).throw(
            windows_root.DataRootLifecycleErrorV1("cleanup failed")
        ),
    )

    with pytest.raises(
        windows_root.DataRootLifecycleErrorV1,
        match="cleanup failed",
    ):
        root.open_relative_data_root_v1(("runtime", "native"))

    root._handles = ()
    root._closed = True


def test_validated_root_lists_immediate_entry_names_without_case_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".codex").mkdir()
    (tmp_path / "AGENTS.md").write_text("rules", encoding="utf-8")
    (tmp_path / "Asset.BIN").write_bytes(b"asset")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "hidden.txt").write_text("hidden", encoding="utf-8")
    monkeypatch.setattr(
        windows_root,
        "_reject_hidden_short_alias",
        lambda _parent, _component: None,
    )

    with open_validated_data_root_v1(str(tmp_path)) as root:
        assert root.relative_entry_names_v1() == (
            ".codex",
            "AGENTS.md",
            "Asset.BIN",
            "nested",
        )


def test_physical_isolation_rejects_a_root_nested_by_file_identity() -> None:
    literature = DataRootInspectionV1(
        status="ready",
        canonical_path=r"D:\Literature",
        identity=(7, 11),
        ancestor_identities=((7, 1), (7, 11)),
    )
    knowledge = DataRootInspectionV1(
        status="ready",
        canonical_path=r"Q:\Knowledge",
        identity=(7, 13),
        ancestor_identities=((7, 1), (7, 11), (7, 13)),
    )

    assert not data_roots_are_physically_isolated(literature, knowledge)


def test_unsupported_namespace_and_missing_directory_have_distinct_statuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        windows_root,
        "_reject_hidden_short_alias",
        lambda _parent, _component: None,
    )
    assert inspect_data_root_v1(r"\\wsl.localhost\Ubuntu\data").status == "unsafe"
    assert inspect_data_root_v1("E:\\data\x00hidden").status == "unsafe"
    assert inspect_data_root_v1(str(tmp_path / "missing")).status == "unavailable"


def test_unknown_drive_type_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(windows_root, "_GET_DRIVE_TYPE", lambda _root: 0)

    assert windows_root._volume_is_supported(r"X:\data") == "unavailable"


def test_shadow_copy_device_mapping_is_unsafe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        windows_root,
        "_GET_DRIVE_TYPE",
        lambda _root: windows_root._DRIVE_FIXED,
    )

    def query(_drive: str, buffer: object, _size: int) -> int:
        typed_buffer = cast(Any, buffer)
        typed_buffer.value = r"\Device\HarddiskVolumeShadowCopy42"
        return len(typed_buffer.value) + 2

    monkeypatch.setattr(windows_root, "_QUERY_DOS_DEVICE", query)

    assert windows_root._volume_is_supported(r"X:\data") == "unsafe"


def test_an_extra_drive_letter_for_the_same_volume_is_unsafe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        windows_root,
        "_GET_DRIVE_TYPE",
        lambda _root: windows_root._DRIVE_FIXED,
    )

    def query(_drive: str, buffer: object, _size: int) -> int:
        typed_buffer = cast(Any, buffer)
        typed_buffer.value = r"\Device\HarddiskVolume42"
        return len(typed_buffer.value) + 2

    monkeypatch.setattr(windows_root, "_QUERY_DOS_DEVICE", query)
    monkeypatch.setattr(
        windows_root,
        "_GET_LOGICAL_DRIVES",
        lambda: (1 << (ord("X") - ord("A"))) | (1 << (ord("Y") - ord("A"))),
    )

    assert windows_root._volume_is_supported(r"X:\data") == "unsafe"


def test_an_extra_directory_mount_for_the_same_volume_is_unsafe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        windows_root,
        "_GET_DRIVE_TYPE",
        lambda _root: windows_root._DRIVE_FIXED,
    )

    def query(_drive: str, buffer: Any, _size: int) -> int:
        buffer.value = r"\Device\HarddiskVolume42"
        return len(buffer.value) + 2

    monkeypatch.setattr(windows_root, "_QUERY_DOS_DEVICE", query)
    monkeypatch.setattr(
        windows_root,
        "_GET_LOGICAL_DRIVES",
        lambda: 1 << (ord("X") - ord("A")),
    )
    def volume_name(_root: str, buffer: Any, _size: int) -> int:
        buffer.value = r"\\?\Volume{00000000-0000-0000-0000-000000000000}\\"
        return 1

    monkeypatch.setattr(
        windows_root,
        "_GET_VOLUME_NAME_FOR_VOLUME_MOUNT_POINT",
        volume_name,
    )

    def volume_paths(
        _volume: str,
        buffer: Any,
        _buffer_size: int,
        returned_length: Any,
    ) -> int:
        value = "X:\\\x00X:\\mounted\\\x00\x00"
        returned_length._obj.value = len(value)
        if buffer is None:
            ctypes.set_last_error(windows_root._ERROR_MORE_DATA)
            return 0
        for index, character in enumerate(value):
            buffer[index] = character
        return 1

    monkeypatch.setattr(
        windows_root,
        "_GET_VOLUME_PATH_NAMES_FOR_VOLUME_NAME",
        volume_paths,
    )

    assert windows_root._volume_is_supported(r"X:\data") == "unsafe"


def test_handle_attribute_reparse_evidence_is_unsafe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "literature"
    data_root.mkdir()
    real_information = windows_root._GET_FILE_INFORMATION_BY_HANDLE_EX

    def information(
        handle: int,
        information_class: int,
        value: Any,
        size: int,
    ) -> int:
        if information_class == windows_root._FILE_ATTRIBUTE_TAG_INFO_CLASS:
            attributes = ctypes.cast(
                value,
                ctypes.POINTER(windows_root._FILE_ATTRIBUTE_TAG_INFO),
            ).contents
            attributes.FileAttributes = (
                windows_root._FILE_ATTRIBUTE_DIRECTORY
                | windows_root._FILE_ATTRIBUTE_REPARSE_POINT
            )
            attributes.ReparseTag = 0xA000000C
            return 1
        return real_information(handle, information_class, value, size)

    monkeypatch.setattr(
        windows_root,
        "_GET_FILE_INFORMATION_BY_HANDLE_EX",
        information,
    )

    assert inspect_data_root_v1(str(data_root)).status == "unsafe"


def test_relative_open_probes_reparse_before_applying_a_type_constraint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, int]] = []

    def raw(
        _parent: int,
        _component: str,
        *,
        desired_access: int,
        share: int,
        options: int,
    ) -> int:
        calls.append((desired_access, options))
        return 11

    monkeypatch.setattr(windows_root, "_nt_open_relative", raw)
    monkeypatch.setattr(
        windows_root,
        "_handle_facts",
        lambda _handle, *, directory: (_ for _ in ()).throw(
            windows_root.DataRootOpenErrorV1("unsafe")
        ),
    )
    monkeypatch.setattr(windows_root, "_close_handles", lambda _handles: None)

    with pytest.raises(windows_root.DataRootOpenErrorV1) as raised:
        windows_root._open_relative_handle(7, "broken-link", directory=True)

    assert raised.value.status == "unsafe"
    assert len(calls) == 1
    assert not calls[0][1] & (
        windows_root._FILE_DIRECTORY_FILE
        | windows_root._FILE_NON_DIRECTORY_FILE
    )


def test_file_id_info_keeps_all_128_identifier_bits() -> None:
    value = windows_root._FILE_ID_INFO()
    value.VolumeSerialNumber = 7
    raw = (1 << 127) | 11
    value.FileId.Identifier[:] = raw.to_bytes(16, "little")

    assert windows_root._identity_from_file_id_info(value) == (7, raw)


def test_directory_enumeration_preserves_an_8dot3_short_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def information(
        _handle: int,
        _information_class: int,
        buffer: Any,
        _size: int,
    ) -> int:
        nonlocal calls
        calls += 1
        if calls > 1:
            ctypes.set_last_error(windows_root._ERROR_NO_MORE_FILES)
            return 0
        entry = windows_root._FILE_ID_BOTH_DIR_INFO.from_buffer(buffer)
        name = "Literature".encode("utf-16-le")
        short_name = "LITERA~1".encode("utf-16-le")
        entry.FileAttributes = windows_root._FILE_ATTRIBUTE_DIRECTORY
        entry.FileNameLength = len(name)
        entry.ShortNameLength = len(short_name)
        ctypes.memmove(
            ctypes.addressof(buffer)
            + windows_root._FILE_ID_BOTH_DIR_INFO.ShortName.offset,
            short_name,
            len(short_name),
        )
        ctypes.memmove(
            ctypes.addressof(buffer)
            + windows_root._FILE_ID_BOTH_DIR_INFO.FileName.offset,
            name,
            len(name),
        )
        return 1

    monkeypatch.setattr(
        windows_root,
        "_GET_FILE_INFORMATION_BY_HANDLE_EX",
        information,
    )

    entries = windows_root._enumerate_directory(7)

    assert len(entries) == 1
    assert entries[0].name == "Literature"
    assert entries[0].short_name == "LITERA~1"


def test_target_component_with_a_short_alias_is_unsafe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry_type = getattr(windows_root, "_DirectoryEntryV1", None)
    assert entry_type is not None
    monkeypatch.setattr(
        windows_root,
        "_enumerate_directory",
        lambda _handle: (
            entry_type(
                name="Literature",
                attributes=windows_root._FILE_ATTRIBUTE_DIRECTORY,
                short_name="LITERA~1",
            ),
        ),
    )

    with pytest.raises(windows_root.DataRootOpenErrorV1) as raised:
        windows_root._reject_hidden_short_alias(7, "Literature")

    assert raised.value.status == "unsafe"


def test_data_root_revalidates_short_alias_evidence_for_every_component(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "literature"
    data_root.mkdir()
    checked: list[str] = []
    monkeypatch.setattr(
        windows_root,
        "_reject_hidden_short_alias",
        lambda _parent, component: checked.append(component),
        raising=False,
    )

    with open_validated_data_root_v1(str(data_root)):
        pass

    components = tuple(
        ntpath.basename(path)
        for path in windows_root._parent_chain(str(data_root))[1:]
    )
    assert checked == [*components, *components]


def test_a_revalidation_fault_closes_every_opened_handle_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "literature"
    data_root.mkdir()
    expected_handles = len(windows_root._parent_chain(str(data_root)))
    real_facts = windows_root._handle_facts
    real_close = windows_root._CLOSE_HANDLE
    real_open_root = windows_root._open_drive_root
    real_nt_open = windows_root._nt_open_relative
    fact_calls = 0
    opened = 0
    closed: list[int] = []

    def facts(handle: int, *, directory: bool) -> Any:
        nonlocal fact_calls
        fact_calls += 1
        if fact_calls == expected_handles * 4 - 2:
            raise windows_root.DataRootOpenErrorV1("unavailable")
        return real_facts(handle, directory=directory)

    def open_root(path: str) -> int:
        nonlocal opened
        handle = real_open_root(path)
        opened += 1
        return handle

    def nt_open(*args: Any, **kwargs: Any) -> int:
        nonlocal opened
        handle = real_nt_open(*args, **kwargs)
        opened += 1
        return handle

    def close(handle: int) -> int:
        closed.append(int(handle))
        return real_close(handle)

    monkeypatch.setattr(windows_root, "_handle_facts", facts)
    monkeypatch.setattr(windows_root, "_open_drive_root", open_root)
    monkeypatch.setattr(windows_root, "_nt_open_relative", nt_open)
    monkeypatch.setattr(windows_root, "_CLOSE_HANDLE", close)
    monkeypatch.setattr(
        windows_root,
        "_reject_hidden_short_alias",
        lambda _parent, _component: None,
    )

    with pytest.raises(windows_root.DataRootOpenErrorV1):
        open_validated_data_root_v1(str(data_root))

    assert len(closed) == opened == expected_handles * 2 - 1


def test_directory_enumeration_budget_counts_directories_and_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = windows_root.ValidatedDataRootV1(
        inspection=DataRootInspectionV1(
            status="ready",
            canonical_path=r"D:\Root",
            identity=(7, 11),
            ancestor_identities=((7, 11),),
        ),
        handles=(1,),
    )
    entries = tuple(
        windows_root._DirectoryEntryV1(
            name=f"directory-{index}",
            attributes=windows_root._FILE_ATTRIBUTE_DIRECTORY,
            short_name=None,
        )
        for index in range(windows_root._MAX_ENUMERATED_ENTRIES + 1)
    )
    monkeypatch.setattr(
        windows_root,
        "_enumerate_directory",
        lambda handle: entries if handle == 1 else (),
    )
    monkeypatch.setattr(
        windows_root,
        "_open_relative_handle",
        lambda *_args, **_kwargs: 2,
    )
    monkeypatch.setattr(
        windows_root,
        "_handle_facts",
        lambda *_args, **_kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(windows_root, "_close_handles", lambda _handles: None)

    with pytest.raises(windows_root.DataRootOpenErrorV1):
        root.relative_file_paths_v1()

    root._handles = ()
    root._closed = True


def test_immediate_entry_budget_rejects_an_oversized_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = windows_root.ValidatedDataRootV1(
        inspection=DataRootInspectionV1(
            status="ready",
            canonical_path=r"D:\Root",
            identity=(7, 11),
            ancestor_identities=((7, 11),),
        ),
        handles=(1,),
    )
    entries = tuple(
        windows_root._DirectoryEntryV1(
            name=f"entry-{index}",
            attributes=0,
            short_name=None,
        )
        for index in range(windows_root._MAX_ENUMERATED_ENTRIES + 1)
    )
    monkeypatch.setattr(windows_root, "_enumerate_directory", lambda _handle: entries)

    with pytest.raises(windows_root.DataRootOpenErrorV1) as raised:
        root.relative_entry_names_v1()

    assert raised.value.status == "unavailable"
    root._handles = ()
    root._closed = True


def test_project_physical_boundary_rejects_equal_or_ancestor_root_identity() -> None:
    project = DataRootInspectionV1(
        status="ready",
        identity=(7, 13),
        ancestor_identities=((7, 1), (7, 11), (7, 13)),
    )
    equal_project = DataRootInspectionV1(
        status="ready",
        identity=(7, 13),
        ancestor_identities=((7, 1), (7, 11), (7, 13)),
    )
    project_ancestor = DataRootInspectionV1(
        status="ready",
        identity=(7, 11),
        ancestor_identities=((7, 1), (7, 11)),
    )
    project_descendant = DataRootInspectionV1(
        status="ready",
        identity=(7, 17),
        ancestor_identities=((7, 1), (7, 11), (7, 13), (7, 17)),
    )

    assert not data_root_does_not_physically_contain_project(equal_project, project)
    assert not data_root_does_not_physically_contain_project(
        project_ancestor,
        project,
    )
    assert data_root_does_not_physically_contain_project(project_descendant, project)
