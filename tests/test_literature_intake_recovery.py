from __future__ import annotations

import json
import queue
import sqlite3
import threading
from collections.abc import Iterator
from os import PathLike
from pathlib import Path

import pytest

from gezhi import _literature_intake as intake
from gezhi import _windows_data_root as windows_root
from gezhi._literature_intake import (
    AddInputInvalidV1,
    AddLocalPdfRequestV1,
    AddStoppedV1,
    add_local_pdf,
)
from gezhi._windows_data_root import (
    DataRootOpenErrorV1,
    open_validated_data_root_v1,
)
from gezhi._windows_ownership import (
    try_acquire_catalog_projection_v1,
    try_acquire_identity_intake_v1,
    try_acquire_work_writer_v1,
)


@pytest.fixture
def local_add_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[Path, Path]]:
    monkeypatch.setattr(
        windows_root,
        "_reject_hidden_short_alias",
        lambda _parent, _component: None,
    )
    data_root = tmp_path / "lit"
    data_root.mkdir()
    pdf_path = tmp_path / "paper.pdf"
    yield data_root, pdf_path


def _request(
    pdf_path: Path,
    *,
    work_id: str | None = None,
    doi: str | None = None,
) -> AddLocalPdfRequestV1:
    return AddLocalPdfRequestV1(
        pdf_path=str(pdf_path),
        work_id=work_id,
        doi=doi,
        arxiv_id=None,
        citation=None,
    )


def _add(
    data_root: Path,
    request: AddLocalPdfRequestV1,
):  # type: ignore[no-untyped-def]
    with open_validated_data_root_v1(str(data_root)) as root:
        return add_local_pdf(request, root=root)


def test_catalog_failure_preserves_authority_and_retry_rebuilds_projection(
    local_add_paths: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root, pdf_path = local_add_paths
    pdf_path.write_bytes(b"%PDF-1.7\ncatalog failure\n")
    real_project = intake._project_catalog

    def fail_projection(
        _root_path: Path, *, root: windows_root.ValidatedDataRootV1
    ) -> None:
        del root
        raise AddStoppedV1("failed", "catalog_projection_failed")

    monkeypatch.setattr(intake, "_project_catalog", fail_projection)
    with pytest.raises(AddStoppedV1) as caught:
        _add(data_root, _request(pdf_path, doi="10.1000/Catalog"))

    assert (caught.value.outcome, caught.value.reason) == (
        "failed",
        "catalog_projection_failed",
    )
    official_works = [
        item
        for item in (data_root / "works").iterdir()
        if item.name != ".staging"
    ]
    assert len(official_works) == 1
    active_before = (official_works[0] / "active_source.json").read_bytes()
    assert not (data_root / "catalog.sqlite3").exists()

    monkeypatch.setattr(intake, "_project_catalog", real_project)
    retried = _add(data_root, _request(pdf_path, doi="10.1000/Catalog"))

    assert retried.work_id == official_works[0].name
    assert retried.disposition == "reused_source"
    assert retried.active_source_changed is False
    assert (official_works[0] / "active_source.json").read_bytes() == active_before
    assert (data_root / "catalog.sqlite3").exists()


def test_catalog_projection_contention_fails_without_rolling_back_authority(
    local_add_paths: tuple[Path, Path],
) -> None:
    data_root, pdf_path = local_add_paths
    pdf_path.write_bytes(b"%PDF-1.7\ncatalog contention\n")
    with open_validated_data_root_v1(str(data_root)) as root:
        assert root.inspection.identity is not None
        lease = try_acquire_catalog_projection_v1(root.inspection.identity)
        assert lease is not None
        try:
            with pytest.raises(AddStoppedV1) as caught:
                add_local_pdf(_request(pdf_path), root=root)
        finally:
            lease.close()

    assert (caught.value.outcome, caught.value.reason) == (
        "failed",
        "catalog_projection_failed",
    )
    official = [
        item
        for item in (data_root / "works").iterdir()
        if item.name != ".staging"
    ]
    assert len(official) == 1
    assert (official[0] / "active_source.json").is_file()

    retried = _add(data_root, _request(pdf_path))
    assert retried.work_id == official[0].name
    assert retried.disposition == "reused_source"


def test_catalog_freezes_aliases_and_identity_hash_from_one_revision(
    local_add_paths: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root, pdf_path = local_add_paths
    pdf_path.write_bytes(b"%PDF-1.7\ncatalog identity snapshot\n")
    first = _add(data_root, _request(pdf_path, doi="10.1000/catalog-old"))
    work_dir = data_root / "works" / first.work_id
    old_current = json.loads(
        (work_dir / "identity" / "current.json").read_bytes()
    )
    old_identity_sha256 = old_current["identity_sha256"]
    projection_thread = threading.current_thread()
    snapshot_captured = threading.Event()
    update_finished = threading.Event()
    observed: queue.Queue[object] = queue.Queue()
    real_snapshot = intake._authority_snapshot

    def pause_after_projection_snapshot(root_path: Path):  # type: ignore[no-untyped-def]
        authority = real_snapshot(root_path)
        if threading.current_thread() is projection_thread:
            snapshot_captured.set()
            assert update_finished.wait(timeout=10)
        return authority

    monkeypatch.setattr(intake, "_authority_snapshot", pause_after_projection_snapshot)

    def update_other_writer() -> None:
        assert snapshot_captured.wait(timeout=10)
        try:
            observed.put(
                _add(
                    data_root,
                    _request(pdf_path, doi="10.1000/catalog-new"),
                )
            )
        except BaseException as error:  # noqa: BLE001 - concurrency witness.
            observed.put(error)
        finally:
            update_finished.set()

    with open_validated_data_root_v1(str(data_root)) as root:
        assert root.inspection.identity is not None
        catalog_owner = try_acquire_catalog_projection_v1(root.inspection.identity)
        assert catalog_owner is not None
        updater = threading.Thread(target=update_other_writer)
        updater.start()
        try:
            intake._project_catalog(data_root, root=root)
        finally:
            catalog_owner.close()
        updater.join(timeout=10)

    assert not updater.is_alive()
    update_outcome = observed.get_nowait()
    assert isinstance(update_outcome, AddStoppedV1)
    assert (update_outcome.outcome, update_outcome.reason) == (
        "failed",
        "catalog_projection_failed",
    )
    new_current = json.loads(
        (work_dir / "identity" / "current.json").read_bytes()
    )
    assert new_current["identity_sha256"] != old_identity_sha256
    with sqlite3.connect(data_root / "catalog.sqlite3") as database:
        projected = database.execute(
            "SELECT alias_value, identity_sha256 FROM work_aliases "
            "WHERE work_id = ? ORDER BY alias_value",
            (first.work_id,),
        ).fetchall()
    assert projected == [("10.1000/catalog-old", old_identity_sha256)]


def test_committed_source_with_stale_pointer_is_reused_on_retry(
    local_add_paths: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root, first_pdf = local_add_paths
    first_pdf.write_bytes(b"%PDF-1.7\nfirst active\n")
    first = _add(data_root, _request(first_pdf))
    second_pdf = first_pdf.with_name("paper2.pdf")
    second_pdf.write_bytes(b"%PDF-1.7\nsecond source\n")
    real_replace = intake.os.replace

    def fail_active(
        source: str | PathLike[str], target: str | PathLike[str]
    ) -> None:
        if Path(target).name == "active_source.json":
            raise OSError("injected Active Source replace failure")
        real_replace(source, target)  # type: ignore[arg-type]

    monkeypatch.setattr(intake.os, "replace", fail_active)
    with pytest.raises(AddStoppedV1) as caught:
        _add(
            data_root,
            _request(second_pdf, work_id=first.work_id),
        )

    assert (caught.value.outcome, caught.value.reason) == (
        "failed",
        "commit_failed",
    )
    work_dir = data_root / "works" / first.work_id
    official_sources = [
        item for item in (work_dir / "sources").iterdir() if item.name != ".staging"
    ]
    assert len(official_sources) == 2
    assert json.loads((work_dir / "active_source.json").read_bytes())[
        "source_id"
    ] == first.source_id
    assert not tuple(work_dir.glob(".active_source.json.*.tmp"))

    monkeypatch.setattr(intake.os, "replace", real_replace)
    retried = _add(data_root, _request(second_pdf, work_id=first.work_id))

    assert retried.disposition == "reused_source"
    assert retried.active_source_changed is True
    assert json.loads((work_dir / "active_source.json").read_bytes())[
        "source_id"
    ] == retried.source_id
    assert len(
        [
            item
            for item in (work_dir / "sources").iterdir()
            if item.name != ".staging"
        ]
    ) == 2


def test_partial_source_manifest_never_becomes_authority_and_retry_is_clean(
    local_add_paths: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root, first_pdf = local_add_paths
    first_pdf.write_bytes(b"%PDF-1.7\nbase source\n")
    first = _add(data_root, _request(first_pdf))
    second_pdf = first_pdf.with_name("paper2.pdf")
    second_pdf.write_bytes(b"%PDF-1.7\nmanifest failure\n")
    real_write = intake._write_new_verified

    def fail_manifest(path: Path, payload: bytes) -> None:
        if path.name == "manifest.json":
            raise AddStoppedV1("failed", "commit_failed")
        real_write(path, payload)

    monkeypatch.setattr(intake, "_write_new_verified", fail_manifest)
    with pytest.raises(AddStoppedV1) as caught:
        _add(data_root, _request(second_pdf, work_id=first.work_id))

    assert (caught.value.outcome, caught.value.reason) == (
        "failed",
        "commit_failed",
    )
    work_dir = data_root / "works" / first.work_id
    assert json.loads((work_dir / "active_source.json").read_bytes())[
        "source_id"
    ] == first.source_id
    assert len(
        [
            item
            for item in (work_dir / "sources").iterdir()
            if item.name != ".staging"
        ]
    ) == 1
    partials = tuple((work_dir / "sources" / ".staging").iterdir())
    assert len(partials) == 1
    assert not (partials[0] / "manifest.json").exists()

    monkeypatch.setattr(intake, "_write_new_verified", real_write)
    retried = _add(data_root, _request(second_pdf, work_id=first.work_id))

    assert retried.disposition == "added_source"
    assert retried.active_source_changed is True
    assert len(
        [
            item
            for item in (work_dir / "sources").iterdir()
            if item.name != ".staging"
        ]
    ) == 2
    assert tuple((work_dir / "sources" / ".staging").iterdir()) == partials


def test_root_checkpoint_drift_is_failed_not_reclassified_as_blocked(
    local_add_paths: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root, pdf_path = local_add_paths
    pdf_path.write_bytes(b"%PDF-1.7\nroot drift\n")

    def drifted(_value: str):  # type: ignore[no-untyped-def]
        raise DataRootOpenErrorV1("unsafe")

    with open_validated_data_root_v1(str(data_root)) as root:
        monkeypatch.setattr(intake, "open_validated_data_root_v1", drifted)
        with pytest.raises(AddStoppedV1) as caught:
            add_local_pdf(_request(pdf_path), root=root)

    assert (caught.value.outcome, caught.value.reason) == (
        "failed",
        "data_root_integrity_lost",
    )
    assert not (data_root / "works").exists()


def test_failure_after_safe_open_is_source_changed(
    local_add_paths: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root, pdf_path = local_add_paths
    pdf_path.write_bytes(b"%PDF-1.7\nsource changes\n")

    class ChangingFile:
        size = 20

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

        def iter_verified_chunks_v1(self):  # type: ignore[no-untyped-def]
            yield b"%PDF-"
            raise DataRootOpenErrorV1("unavailable")

    monkeypatch.setattr(
        intake,
        "open_validated_local_file_v1",
        lambda _value: ChangingFile(),
    )

    with pytest.raises(AddStoppedV1) as caught:
        _add(data_root, _request(pdf_path))

    assert (caught.value.outcome, caught.value.reason) == (
        "failed",
        "source_changed",
    )
    assert not [
        item
        for item in (data_root / "works").iterdir()
        if item.name != ".staging"
    ]


def test_identity_intake_contention_is_zero_wait_and_does_not_open_pdf(
    local_add_paths: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root, pdf_path = local_add_paths
    pdf_path.write_bytes(b"%PDF-1.7\nidentity busy\n")
    with open_validated_data_root_v1(str(data_root)) as root:
        assert root.inspection.identity is not None
        lease = try_acquire_identity_intake_v1(root.inspection.identity)
        assert lease is not None
        monkeypatch.setattr(
            intake,
            "open_validated_local_file_v1",
            lambda _value: pytest.fail("PDF gate must not run while identity is busy"),
        )
        try:
            with pytest.raises(AddStoppedV1) as caught:
                add_local_pdf(_request(pdf_path), root=root)
        finally:
            lease.close()

    assert (caught.value.outcome, caught.value.reason) == (
        "blocked",
        "identity_intake_busy",
    )


def test_resolved_work_contention_uses_work_busy_after_identity_release(
    local_add_paths: tuple[Path, Path],
) -> None:
    data_root, pdf_path = local_add_paths
    pdf_path.write_bytes(b"%PDF-1.7\nwork busy\n")
    created = _add(data_root, _request(pdf_path))
    with open_validated_data_root_v1(str(data_root)) as root:
        assert root.inspection.identity is not None
        lease = try_acquire_work_writer_v1(
            root.inspection.identity,
            created.work_id,
        )
        assert lease is not None
        try:
            with pytest.raises(AddStoppedV1) as caught:
                add_local_pdf(_request(pdf_path), root=root)
        finally:
            lease.close()

    assert (caught.value.outcome, caught.value.reason) == (
        "blocked",
        "work_busy",
    )


def test_corrupted_committed_source_is_collision_and_is_not_overwritten(
    local_add_paths: tuple[Path, Path],
) -> None:
    data_root, pdf_path = local_add_paths
    original = b"%PDF-1.7\noriginal authority\n"
    pdf_path.write_bytes(original)
    created = _add(data_root, _request(pdf_path))
    authoritative = (
        data_root
        / "works"
        / created.work_id
        / "sources"
        / created.source_id
        / "original.pdf"
    )
    authoritative.write_bytes(b"%PDF-1.7\ncorrupted authority\n")

    with pytest.raises(AddStoppedV1) as caught:
        _add(data_root, _request(pdf_path))

    assert (caught.value.outcome, caught.value.reason) == (
        "failed",
        "content_identity_collision",
    )
    assert authoritative.read_bytes() == b"%PDF-1.7\ncorrupted authority\n"


def test_invalid_raw_input_precedes_writer_ownership(
    local_add_paths: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root, _pdf_path = local_add_paths
    monkeypatch.setattr(
        intake,
        "try_acquire_identity_intake_v1",
        lambda _identity: pytest.fail("ownership must not run for invalid input"),
    )
    request = AddLocalPdfRequestV1(
        pdf_path="relative.pdf",
        work_id=None,
        doi=None,
        arxiv_id=None,
        citation=None,
    )

    with open_validated_data_root_v1(str(data_root)) as root, pytest.raises(
        AddInputInvalidV1
    ) as caught:
        add_local_pdf(request, root=root)

    assert caught.value.field == "pdf_path"


def test_identity_reservation_prevents_concurrent_duplicate_works(
    local_add_paths: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root, pdf_path = local_add_paths
    pdf_path.write_bytes(b"%PDF-1.7\nconcurrent identity\n")
    real_acquire = intake.try_acquire_work_writer_v1
    acquisition_count = 0
    count_guard = threading.Lock()
    first_has_work = threading.Event()
    second_reached_work = threading.Event()
    release_first = threading.Event()
    observed: queue.Queue[object] = queue.Queue()

    def controlled_acquire(identity: object, work_id: str):  # type: ignore[no-untyped-def]
        nonlocal acquisition_count
        lease = real_acquire(identity, work_id)  # type: ignore[arg-type]
        with count_guard:
            acquisition_count += 1
            ordinal = acquisition_count
        if ordinal == 1:
            first_has_work.set()
            assert second_reached_work.wait(timeout=5)
            assert release_first.wait(timeout=5)
        else:
            second_reached_work.set()
        return lease

    monkeypatch.setattr(intake, "try_acquire_work_writer_v1", controlled_acquire)

    def invoke() -> None:
        try:
            observed.put(_add(data_root, _request(pdf_path)))
        except BaseException as error:  # noqa: BLE001 - concurrency witness.
            observed.put(error)

    first_thread = threading.Thread(target=invoke)
    first_thread.start()
    assert first_has_work.wait(timeout=5)
    second_thread = threading.Thread(target=invoke)
    second_thread.start()
    assert second_reached_work.wait(timeout=5)
    release_first.set()
    first_thread.join(timeout=10)
    second_thread.join(timeout=10)

    assert not first_thread.is_alive() and not second_thread.is_alive()
    values = [observed.get_nowait(), observed.get_nowait()]
    successes = [
        value for value in values if isinstance(value, intake.AddLocalPdfResultV1)
    ]
    blockers = [value for value in values if isinstance(value, AddStoppedV1)]
    assert len(successes) == 1
    assert [(item.outcome, item.reason) for item in blockers] == [
        ("blocked", "work_busy")
    ]
    retried = _add(data_root, _request(pdf_path))
    assert retried.work_id == successes[0].work_id
    assert retried.disposition == "reused_source"
    assert len(
        [
            item
            for item in (data_root / "works").iterdir()
            if item.name != ".staging"
        ]
    ) == 1


def test_new_work_pointer_gap_recovers_the_reserved_work_id(
    local_add_paths: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root, pdf_path = local_add_paths
    pdf_path.write_bytes(b"%PDF-1.7\nnew work recovery\n")
    real_replace = intake._atomic_replace_json

    def fail_active(parent: Path, name: str, value: object) -> bytes:
        if name == "active_source.json":
            raise AddStoppedV1("failed", "commit_failed")
        return real_replace(parent, name, value)

    monkeypatch.setattr(intake, "_atomic_replace_json", fail_active)
    with pytest.raises(AddStoppedV1) as caught:
        _add(data_root, _request(pdf_path))
    assert (caught.value.outcome, caught.value.reason) == (
        "failed",
        "commit_failed",
    )
    reservation_path = next(
        (data_root / "works" / ".staging" / "reservations").iterdir()
    )
    reservation = json.loads(reservation_path.read_bytes())
    reserved_work_id = reservation["work_id"]
    assert not [
        item
        for item in (data_root / "works" / ".staging").iterdir()
        if item.name.startswith("wrk_")
    ]

    monkeypatch.setattr(intake, "_atomic_replace_json", real_replace)
    recovered = _add(data_root, _request(pdf_path))

    assert recovered.work_id == reserved_work_id
    assert recovered.disposition == "created_work"
    assert (data_root / "works" / reserved_work_id).is_dir()
    assert not [
        item
        for item in (data_root / "works" / ".staging").iterdir()
        if item.name.startswith("wrk_")
    ]


def test_new_work_early_private_stage_failure_reuses_reservation_id(
    local_add_paths: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root, pdf_path = local_add_paths
    pdf_path.write_bytes(b"%PDF-1.7\nearly private stage recovery\n")
    real_write = intake._write_new_verified

    def fail_first_work_descriptor(path: Path, payload: bytes) -> None:
        if path.name == "work.json":
            raise AddStoppedV1("failed", "commit_failed")
        real_write(path, payload)

    monkeypatch.setattr(intake, "_write_new_verified", fail_first_work_descriptor)
    with pytest.raises(AddStoppedV1) as caught:
        _add(data_root, _request(pdf_path))
    assert (caught.value.outcome, caught.value.reason) == (
        "failed",
        "commit_failed",
    )
    reservation_path = next(
        (data_root / "works" / ".staging" / "reservations").iterdir()
    )
    reservation = json.loads(reservation_path.read_bytes())
    reserved_work_id = reservation["work_id"]

    monkeypatch.setattr(intake, "_write_new_verified", real_write)
    recovered = _add(data_root, _request(pdf_path))

    assert recovered.work_id == reserved_work_id
    official_works = [
        item
        for item in (data_root / "works").iterdir()
        if item.name != ".staging"
    ]
    assert [item.name for item in official_works] == [reserved_work_id]
    sources = [
        item
        for item in (official_works[0] / "sources").iterdir()
        if item.name != ".staging"
    ]
    assert [item.name for item in sources] == [recovered.source_id]


def test_complete_staged_work_recovers_after_final_directory_rename_failure(
    local_add_paths: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root, pdf_path = local_add_paths
    pdf_path.write_bytes(b"%PDF-1.7\nwork rename recovery\n")
    real_rename = intake.os.rename

    def fail_work_publish(
        source: str | PathLike[str], target: str | PathLike[str]
    ) -> None:
        source_path = Path(source)
        target_path = Path(target)
        if (
            source_path.name.startswith("wrk_")
            and source_path.parent.name == ".staging"
            and target_path.parent.name == "works"
        ):
            raise OSError("injected Work directory rename failure")
        real_rename(source, target)  # type: ignore[arg-type]

    monkeypatch.setattr(intake.os, "rename", fail_work_publish)
    with pytest.raises(AddStoppedV1) as caught:
        _add(data_root, _request(pdf_path))
    assert (caught.value.outcome, caught.value.reason) == (
        "failed",
        "commit_failed",
    )
    staged = [
        item
        for item in (data_root / "works" / ".staging").iterdir()
        if item.name.startswith("wrk_")
    ]
    assert len(staged) == 1
    reserved_work_id = staged[0].name
    assert (staged[0] / "active_source.json").is_file()

    monkeypatch.setattr(intake.os, "rename", real_rename)
    recovered = _add(data_root, _request(pdf_path))

    assert recovered.work_id == reserved_work_id
    assert recovered.disposition == "created_work"
    assert (data_root / "works" / reserved_work_id).is_dir()


def test_identity_pointer_publish_rechecks_frozen_root(
    local_add_paths: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root, pdf_path = local_add_paths
    pdf_path.write_bytes(b"%PDF-1.7\nidentity pointer checkpoint\n")
    first = _add(data_root, _request(pdf_path, doi="10.1000/identity-old"))
    work_dir = data_root / "works" / first.work_id
    current_path = work_dir / "identity" / "current.json"
    current_before = current_path.read_bytes()
    real_checkpoint = intake._root_checkpoint

    def drift_before_identity_pointer(
        root: windows_root.ValidatedDataRootV1,
    ) -> None:
        revisions = work_dir / "identity" / "revisions"
        if (
            any(
                b"10.1000/identity-new" in path.read_bytes()
                for path in revisions.iterdir()
            )
            and current_path.read_bytes() == current_before
        ):
            raise AddStoppedV1("failed", "data_root_integrity_lost")
        real_checkpoint(root)

    monkeypatch.setattr(intake, "_root_checkpoint", drift_before_identity_pointer)
    with pytest.raises(AddStoppedV1) as caught:
        _add(data_root, _request(pdf_path, doi="10.1000/identity-new"))

    assert (caught.value.outcome, caught.value.reason) == (
        "failed",
        "data_root_integrity_lost",
    )
    assert current_path.read_bytes() == current_before


def test_catalog_publish_rechecks_frozen_root_after_integrity_check(
    local_add_paths: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root, pdf_path = local_add_paths
    pdf_path.write_bytes(b"%PDF-1.7\ncatalog publish checkpoint\n")
    real_checkpoint = intake._root_checkpoint

    def drift_before_catalog_replace(
        root: windows_root.ValidatedDataRootV1,
    ) -> None:
        if tuple(data_root.glob(".catalog-*.tmp")):
            raise AddStoppedV1("failed", "data_root_integrity_lost")
        real_checkpoint(root)

    monkeypatch.setattr(intake, "_root_checkpoint", drift_before_catalog_replace)
    with pytest.raises(AddStoppedV1) as caught:
        _add(data_root, _request(pdf_path))

    assert (caught.value.outcome, caught.value.reason) == (
        "failed",
        "data_root_integrity_lost",
    )
    assert not (data_root / "catalog.sqlite3").exists()


def test_missing_identity_current_blocks_duplicate_without_losing_aliases(
    local_add_paths: tuple[Path, Path],
) -> None:
    data_root, pdf_path = local_add_paths
    pdf_path.write_bytes(b"%PDF-1.7\nmissing identity duplicate\n")
    first = _add(data_root, _request(pdf_path, doi="10.1000/current-gap"))
    work_dir = data_root / "works" / first.work_id
    current_path = work_dir / "identity" / "current.json"
    revisions_dir = work_dir / "identity" / "revisions"
    revisions_before = {
        item.name: item.read_bytes() for item in revisions_dir.iterdir()
    }
    current_path.unlink()

    with pytest.raises(AddStoppedV1) as caught:
        _add(data_root, _request(pdf_path))

    assert (caught.value.outcome, caught.value.reason) == (
        "blocked",
        "identity_review_required",
    )
    assert not current_path.exists()
    assert {
        item.name: item.read_bytes() for item in revisions_dir.iterdir()
    } == revisions_before
    assert [
        item.name
        for item in (data_root / "works").iterdir()
        if item.name != ".staging"
    ] == [first.work_id]


def test_missing_identity_current_cannot_create_second_strong_alias_owner(
    local_add_paths: tuple[Path, Path],
) -> None:
    data_root, first_pdf = local_add_paths
    first_pdf.write_bytes(b"%PDF-1.7\nmissing current first source\n")
    first = _add(data_root, _request(first_pdf, doi="10.1000/current-owner"))
    work_dir = data_root / "works" / first.work_id
    current_path = work_dir / "identity" / "current.json"
    revisions_dir = work_dir / "identity" / "revisions"
    revisions_before = {
        item.name: item.read_bytes() for item in revisions_dir.iterdir()
    }
    current_path.unlink()
    second_pdf = first_pdf.with_name("second-owner.pdf")
    second_pdf.write_bytes(b"%PDF-1.7\nmissing current second source\n")

    with pytest.raises(AddStoppedV1) as caught:
        _add(data_root, _request(second_pdf, doi="10.1000/current-owner"))

    assert (caught.value.outcome, caught.value.reason) == (
        "blocked",
        "identity_review_required",
    )
    assert not current_path.exists()
    assert {
        item.name: item.read_bytes() for item in revisions_dir.iterdir()
    } == revisions_before
    assert [
        item.name
        for item in (data_root / "works").iterdir()
        if item.name != ".staging"
    ] == [first.work_id]


def test_tampered_active_pointer_is_not_treated_as_idempotent_success(
    local_add_paths: tuple[Path, Path],
) -> None:
    data_root, pdf_path = local_add_paths
    pdf_path.write_bytes(b"%PDF-1.7\nactive pointer integrity\n")
    created = _add(data_root, _request(pdf_path))
    pointer_path = data_root / "works" / created.work_id / "active_source.json"
    pointer = json.loads(pointer_path.read_bytes())
    pointer["manifest_sha256"] = "0" * 64
    tampered = intake._canonical_json_bytes(pointer)
    pointer_path.write_bytes(tampered)

    with pytest.raises(AddStoppedV1) as caught:
        _add(data_root, _request(pdf_path))

    assert (caught.value.outcome, caught.value.reason) == (
        "failed",
        "content_identity_collision",
    )
    assert pointer_path.read_bytes() == tampered


def test_identity_current_cannot_escape_its_revision_directory(
    local_add_paths: tuple[Path, Path],
) -> None:
    data_root, pdf_path = local_add_paths
    pdf_path.write_bytes(b"%PDF-1.7\nidentity pointer integrity\n")
    created = _add(data_root, _request(pdf_path))
    current_path = data_root / "works" / created.work_id / "identity" / "current.json"
    current = json.loads(current_path.read_bytes())
    current["revision"] = "..\\..\\outside.json"
    tampered = intake._canonical_json_bytes(current)
    current_path.write_bytes(tampered)

    with pytest.raises(AddStoppedV1) as caught:
        _add(data_root, _request(pdf_path))

    assert (caught.value.outcome, caught.value.reason) == (
        "blocked",
        "identity_review_required",
    )
    assert current_path.read_bytes() == tampered
