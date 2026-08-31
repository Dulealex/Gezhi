from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, cast

from gezhi._literature_intake import (
    ActiveSourceAuthorityStoppedV1,
    ActiveSourceAuthorityV1,
    load_active_source_authority_v1,
)
from gezhi._windows_data_root import (
    DataRootOpenErrorV1,
    ValidatedDataRootV1,
    open_validated_data_root_v1,
)
from gezhi._windows_ownership import work_writer_is_active_v1
from gezhi._work_id import is_work_id_v1

if TYPE_CHECKING:
    from gezhi._literature_canonical import (
        CurrentCanonicalAssetV1,
        _ValidatedCanonicalRunV1,
    )
    from gezhi._literature_reader import ReaderAdvanceV1
    from gezhi._literature_resume import _ValidatedRunV1

_WORK_STATUS_ORDER = (
    "pending",
    "running",
    "succeeded",
    "blocked",
    "failed",
    "interrupted",
    "partial",
    "staging",
    "orphaned",
    "quarantined",
    "inconsistent",
)
_STAGE_ORDER = (
    "ingest",
    "ocr",
    "canonicalize",
    "read",
    "review",
    "handoff",
    "knowledge_import",
)
_ZERO_RECOVERY = {
    "staging_count": 0,
    "orphaned_count": 0,
    "quarantined_count": 0,
    "inconsistent_count": 0,
}


class LiteratureStatusProjectionFailedV1(RuntimeError):
    """Literature cannot form a bounded read-only status projection."""


def _recovery(**changes: int) -> dict[str, int]:
    value = dict(_ZERO_RECOVERY)
    value.update(changes)
    return value


def _staging_count(works: ValidatedDataRootV1) -> int:
    names = works.relative_entry_names_v1()
    if ".staging" not in names:
        return 0
    with works.open_relative_data_root_v1((".staging",)) as staging:
        count = 0
        for name in staging.relative_entry_names_v1():
            if name != "reservations":
                count += 1
                continue
            with staging.open_relative_data_root_v1(("reservations",)) as reservations:
                count += len(reservations.relative_entry_names_v1())
        return count


def _work_intake_staging_count(root: ValidatedDataRootV1, work_id: str) -> int:
    names = root.relative_entry_names_v1()
    if "works" not in names:
        return 0
    with root.open_relative_data_root_v1(("works",)) as works:
        work_names = works.relative_entry_names_v1()
        if ".staging" not in work_names:
            return 0
        with works.open_relative_data_root_v1((".staging",)) as staging:
            staging_names = staging.relative_entry_names_v1()
            count = int(work_id in staging_names)
    root_path = root.inspection.canonical_path
    if root_path is None:
        raise LiteratureStatusProjectionFailedV1("Literature root path is unavailable")
    try:
        from gezhi import _literature_intake as intake

        count += sum(
            reservation.work_id == work_id
            for reservation in intake._load_reservations(Path(root_path))
        )
    except Exception as error:
        raise LiteratureStatusProjectionFailedV1(
            "Literature intake staging is invalid"
        ) from error
    return count


def _base_stages(authority: ActiveSourceAuthorityV1) -> list[dict[str, str]]:
    ingest = "succeeded" if authority.ingest_identity_ready else "blocked"
    return [
        {"stage": "ingest", "status": ingest},
        {"stage": "ocr", "status": "pending"},
        {"stage": "canonicalize", "status": "pending"},
        {"stage": "read", "status": "pending"},
        {"stage": "review", "status": "pending"},
        {"stage": "handoff", "status": "pending"},
        {"stage": "knowledge_import", "status": "pending"},
    ]


def _set_stage(
    stages: list[dict[str, str]],
    stage: str,
    status: str,
) -> None:
    for item in stages:
        if item["stage"] == stage:
            item["status"] = status
            return
    raise RuntimeError("Literature stage is unavailable")


def _safe_staging_entry_count(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        with open_validated_data_root_v1(str(path)) as staging:
            return len(staging.relative_entry_names_v1())
    except DataRootOpenErrorV1 as error:
        raise LiteratureStatusProjectionFailedV1(
            "Literature staging cannot be bounded"
        ) from error


def _structured_staging_facts(
    path: Path,
    *,
    direct_entries_are_quarantined: bool,
) -> tuple[int, int]:
    if not path.exists():
        return 0, 0
    try:
        with open_validated_data_root_v1(str(path)) as staging:
            names = staging.relative_entry_names_v1()
            file_count = 0
            if ".files" in names:
                with staging.open_relative_data_root_v1((".files",)) as files:
                    file_count = len(files.relative_entry_names_v1())
    except DataRootOpenErrorV1 as error:
        raise LiteratureStatusProjectionFailedV1(
            "Literature structured staging cannot be bounded"
        ) from error
    direct_count = sum(name != ".files" for name in names)
    if direct_entries_are_quarantined:
        return file_count, direct_count
    return file_count + direct_count, 0


def _project_ocr_v1(
    authority: ActiveSourceAuthorityV1,
    stages: list[dict[str, str]],
    recovery: dict[str, int],
) -> _ValidatedRunV1 | None:
    from gezhi import _literature_resume as resume

    ocr_dir = authority.source_directory / "ocr"
    if not ocr_dir.exists():
        return None
    runs_dir = ocr_dir / "runs"
    recovery["staging_count"] += _safe_staging_entry_count(runs_dir / ".staging")
    if not runs_dir.exists():
        recovery["inconsistent_count"] += 1
        _set_stage(stages, "ocr", "failed")
        return None
    valid_runs: list[_ValidatedRunV1] = []
    try:
        with open_validated_data_root_v1(str(runs_dir)) as runs:
            names = runs.relative_entry_names_v1()
    except DataRootOpenErrorV1 as error:
        raise LiteratureStatusProjectionFailedV1(
            "OCR runs cannot be bounded"
        ) from error
    for name in names:
        if name == ".staging":
            continue
        try:
            valid_runs.append(resume._load_run(runs_dir / name, name, authority))
        except Exception:  # noqa: BLE001 - one invalid immutable run is isolated.
            recovery["inconsistent_count"] += 1
    current_path = ocr_dir / "current.json"
    if current_path.exists():
        try:
            current, _payload = resume._load_current_document_run_v1(
                current_path,
                runs_dir,
                authority,
            )
        except Exception:  # noqa: BLE001 - corrupt current is a bounded Work fact.
            recovery["inconsistent_count"] += 1
            _set_stage(stages, "ocr", "failed")
            return None
        _set_stage(stages, "ocr", "succeeded")
        return current
    successes = [run for run in valid_runs if run.status == "succeeded"]
    if successes:
        recovery["orphaned_count"] += len(successes)
    terminal_statuses = {
        run.status for run in valid_runs if run.status in {"blocked", "failed"}
    }
    for status in ("failed", "blocked"):
        if status in terminal_statuses:
            _set_stage(stages, "ocr", status)
            break
    return None


def _project_canonical_v1(
    authority: ActiveSourceAuthorityV1,
    ocr_run: _ValidatedRunV1,
    stages: list[dict[str, str]],
    recovery: dict[str, int],
) -> CurrentCanonicalAssetV1 | None:
    from gezhi import _literature_canonical as canonical

    canonical_dir = authority.source_directory / "canonical"
    if not canonical_dir.exists():
        return None
    runs_dir = canonical_dir / "runs"
    recovery["staging_count"] += _safe_staging_entry_count(runs_dir / ".staging")
    if not runs_dir.exists():
        recovery["inconsistent_count"] += 1
        _set_stage(stages, "canonicalize", "failed")
        return None
    runs: dict[str, _ValidatedCanonicalRunV1] = {}
    try:
        with open_validated_data_root_v1(str(runs_dir)) as runs_root:
            names = runs_root.relative_entry_names_v1()
    except DataRootOpenErrorV1 as error:
        raise LiteratureStatusProjectionFailedV1(
            "Canonical runs cannot be bounded"
        ) from error
    for name in names:
        if name == ".staging":
            continue
        try:
            runs[name] = canonical._load_run(runs_dir / name, name, authority)
        except Exception:  # noqa: BLE001 - one invalid immutable run is isolated.
            recovery["inconsistent_count"] += 1
    current_path = canonical_dir / "current.json"
    if not current_path.exists():
        if runs:
            recovery["orphaned_count"] += len(runs)
        return None
    try:
        current_run, _payload = canonical._load_current_path(
            current_path,
            runs=runs,
            authority=authority,
        )
        current = canonical._as_current(current_run)
    except Exception:  # noqa: BLE001 - corrupt current is a bounded Work fact.
        recovery["inconsistent_count"] += 1
        _set_stage(stages, "canonicalize", "failed")
        return None
    expected_fingerprint = canonical._input_fingerprint(
        work_id=authority.work_id,
        source_id=authority.source_id,
        source_sha256=authority.source_sha256,
        ocr_run_id=ocr_run.run_id,
        ocr_manifest_sha256=ocr_run.manifest_sha256,
        ocr_input_fingerprint_sha256=ocr_run.input_fingerprint_sha256,
    )
    if current.input_fingerprint_sha256 != expected_fingerprint:
        recovery["inconsistent_count"] += 1
        _set_stage(stages, "canonicalize", "failed")
        return None
    _set_stage(stages, "canonicalize", "succeeded")
    return current


def _project_reader_v1(
    authority: ActiveSourceAuthorityV1,
    canonical: CurrentCanonicalAssetV1,
    stages: list[dict[str, str]],
    recovery: dict[str, int],
    *,
    writer_active: bool,
) -> ReaderAdvanceV1 | None:
    from gezhi import _literature_reader as reader

    semantic_dir = authority.source_directory / "semantic"
    if not semantic_dir.exists():
        return None
    runs_dir = semantic_dir / "runs"
    reader_staging = _safe_staging_entry_count(semantic_dir / ".staging")
    recovery["staging_count"] += reader_staging
    current_path = semantic_dir / "current.json"
    if not current_path.exists():
        if runs_dir.exists():
            try:
                with open_validated_data_root_v1(str(runs_dir)) as runs:
                    run_names = runs.relative_entry_names_v1()
            except DataRootOpenErrorV1 as error:
                raise LiteratureStatusProjectionFailedV1(
                    "Reader runs cannot be bounded"
                ) from error
            valid_successes = 0
            terminal_statuses: set[str] = set()
            for name in run_names:
                try:
                    status = reader.validated_terminal_reader_status_v1(
                        runs_dir / name,
                        name,
                        authority,
                        canonical,
                    )
                except Exception:  # noqa: BLE001 - isolate one Reader run.
                    recovery["inconsistent_count"] += 1
                else:
                    if status == "succeeded":
                        valid_successes += 1
                    else:
                        terminal_statuses.add(status)
            recovery["orphaned_count"] += valid_successes
            for status in ("failed", "blocked", "interrupted"):
                if status in terminal_statuses:
                    _set_stage(stages, "read", status)
                    break
        if writer_active and reader_staging:
            _set_stage(stages, "read", "running")
        return None
    try:
        current = reader._load_current(semantic_dir, authority, canonical)
    except Exception:  # noqa: BLE001 - corrupt current is a bounded Work fact.
        recovery["inconsistent_count"] += 1
        _set_stage(stages, "read", "failed")
        return None
    if current is None:
        if writer_active and reader_staging:
            _set_stage(stages, "read", "running")
        return None
    return current


def _orphan_materialization_runs_v1(
    authority: ActiveSourceAuthorityV1,
    canonical: CurrentCanonicalAssetV1,
    reader: ReaderAdvanceV1,
    runs_dir: Path,
    recovery: dict[str, int],
) -> None:
    from gezhi import _literature_candidate as candidate

    try:
        with open_validated_data_root_v1(str(runs_dir)) as runs:
            run_names = runs.relative_entry_names_v1()
    except DataRootOpenErrorV1 as error:
        raise LiteratureStatusProjectionFailedV1(
            "Candidate materialization runs cannot be bounded"
        ) from error
    bundle = candidate._reader_bundle(authority, canonical, reader)
    for run_id in run_names:
        try:
            _manifest, manifest_bytes = candidate._read_canonical_object_v1(
                runs_dir / run_id / "manifest.json"
            )
            _materialized, _observed, _matches = candidate._validate_pointed_success(
                runs_dir,
                run_id,
                candidate._content_sha256(manifest_bytes),
                authority,
                canonical,
                reader,
                bundle,
            )
        except Exception:  # noqa: BLE001 - isolate one immutable run.
            recovery["inconsistent_count"] += 1
        else:
            recovery["orphaned_count"] += 1


def _project_materialization_v1(
    authority: ActiveSourceAuthorityV1,
    canonical: CurrentCanonicalAssetV1,
    reader: ReaderAdvanceV1,
    stages: list[dict[str, str]],
    recovery: dict[str, int],
) -> tuple[str, ...] | None:
    from gezhi import _literature_candidate as candidate

    materializations = authority.source_directory / "semantic" / "materializations"
    if not materializations.exists():
        return None
    runs_dir = materializations / "runs"
    recovery["staging_count"] += _safe_staging_entry_count(
        materializations / ".staging"
    )
    if (materializations / ".current.next.json").exists():
        recovery["staging_count"] += 1
    current_path = materializations / "current.json"
    if not current_path.exists():
        if runs_dir.exists():
            _orphan_materialization_runs_v1(
                authority,
                canonical,
                reader,
                runs_dir,
                recovery,
            )
        return None
    try:
        bundle = candidate._reader_bundle(authority, canonical, reader)
        current, _payload = candidate._read_canonical_object_v1(current_path)
        run_id, manifest_sha256 = candidate._pointer_identity(current)
        materialized, _observed, matches = candidate._validate_pointed_success(
            runs_dir,
            run_id,
            manifest_sha256,
            authority,
            canonical,
            reader,
            bundle,
        )
        if not matches:
            raise ValueError("Candidate materialization is not current")
    except Exception:  # noqa: BLE001 - corrupt current is a bounded Work fact.
        recovery["inconsistent_count"] += 1
        _set_stage(stages, "read", "failed")
        return None
    _set_stage(stages, "read", "succeeded")
    return cast(tuple[str, ...], materialized.pending_candidate_ids)


def _apply_review_stage_projection(
    stages: list[dict[str, str]],
    *,
    start_stage: str,
    stop_stage: str | None,
    stop_outcome: str | None,
) -> None:
    review_stages = ("review", "handoff", "knowledge_import")
    if start_stage == "complete":
        for stage in review_stages:
            _set_stage(stages, stage, "succeeded")
    else:
        start_index = review_stages.index(start_stage)
        for index, stage in enumerate(review_stages):
            _set_stage(stages, stage, "succeeded" if index < start_index else "pending")
    if stop_stage is not None:
        if stop_outcome not in {"blocked", "failed"}:
            raise ValueError("Review stop outcome is invalid")
        _set_stage(stages, stop_stage, stop_outcome)


def _project_review_v1(
    authority: ActiveSourceAuthorityV1,
    pending_candidate_ids: tuple[str, ...],
    root: ValidatedDataRootV1,
    stages: list[dict[str, str]],
    recovery: dict[str, int],
) -> tuple[dict[str, int], str]:
    from gezhi import _literature_review as review

    review_staging, quarantined = _structured_staging_facts(
        authority.work_directory / "reviews" / ".staging",
        direct_entries_are_quarantined=True,
    )
    handoff_staging, _ignored = _structured_staging_facts(
        authority.work_directory / "handoffs" / ".staging",
        direct_entries_are_quarantined=False,
    )
    recovery["staging_count"] += review_staging + handoff_staging
    recovery["quarantined_count"] += quarantined
    if quarantined:
        _set_stage(stages, "review", "failed")
        return {
            "pending": 0,
            "accepted": 0,
            "rejected": 0,
            "deferred": 0,
        }, "inconsistent"
    try:
        plan = review._build_work_review_plan_v1(
            authority,
            pending_candidate_ids,
            root=root,
        )
    except Exception:  # noqa: BLE001 - Review corruption is isolated to this Work.
        recovery["inconsistent_count"] += 1
        _set_stage(stages, "review", "failed")
        return {
            "pending": 0,
            "accepted": 0,
            "rejected": 0,
            "deferred": 0,
        }, "inconsistent"
    counts = Counter({"pending": len(plan.pending_candidate_ids)})
    for item in plan.snapshots:
        if item.decisions:
            counts[item.decisions[-1].status] += 1
        if item.current_repair_required:
            recovery["orphaned_count"] += 1
    review_counts = {
        key: counts[key] for key in ("pending", "accepted", "rejected", "deferred")
    }
    stop = plan.stop
    _apply_review_stage_projection(
        stages,
        start_stage=plan.start_stage,
        stop_stage=None if stop is None else stop.stage,
        stop_outcome=None if stop is None else stop.outcome,
    )

    handoff_obligations = [
        obligation for obligation in plan.obligations if obligation.handoff_required
    ]
    if stop is not None and stop.stage == "handoff":
        handoff_status = "failed" if stop.outcome == "failed" else "blocked"
    elif handoff_obligations:
        handoff_status = "pending"
    elif any(
        obligation.action in {"accept", "withdraw"} for obligation in plan.obligations
    ) or any(item.imports for item in plan.snapshots):
        handoff_status = "available"
    else:
        handoff_status = "none"
    return review_counts, handoff_status


def _work_status(stages: list[dict[str, str]], recovery: dict[str, int]) -> str:
    for key, status in (
        ("inconsistent_count", "inconsistent"),
        ("quarantined_count", "quarantined"),
        ("orphaned_count", "orphaned"),
        ("staging_count", "staging"),
    ):
        if recovery[key]:
            return status
    statuses = {item["status"] for item in stages}
    for status in ("failed", "blocked", "interrupted", "running", "pending"):
        if status in statuses:
            return status
    return "succeeded"


def _project_live_automatic_stage_v1(
    stages: list[dict[str, str]],
    *,
    writer_active: bool,
) -> None:
    if not writer_active:
        return
    for stage in ("ocr", "canonicalize", "read"):
        item = next(candidate for candidate in stages if candidate["stage"] == stage)
        if item["status"] == "succeeded":
            continue
        if item["status"] == "pending":
            item["status"] = "running"
        return


def project_literature_work_status_v1(
    root: ValidatedDataRootV1,
    work_id: str,
    *,
    include_intake_staging: bool,
) -> dict[str, object] | None:
    """Project one Work from Literature-owned immutable authority without mutation."""

    try:
        authority = load_active_source_authority_v1(work_id, root=root)
    except ActiveSourceAuthorityStoppedV1 as error:
        if error.reason == "work_not_found":
            return None
        recovery = _recovery(inconsistent_count=1)
        stages = [
            {"stage": stage, "status": "failed" if stage == "ingest" else "pending"}
            for stage in _STAGE_ORDER
        ]
        return {
            "availability": "partial",
            "stages": stages,
            "review_counts": {
                "pending": 0,
                "accepted": 0,
                "rejected": 0,
                "deferred": 0,
            },
            "handoff_status": "inconsistent",
            "recovery": recovery,
            "_status": "inconsistent",
        }
    recovery = _recovery()
    if include_intake_staging:
        recovery["staging_count"] = _work_intake_staging_count(root, work_id)
    stages = _base_stages(authority)
    root_identity = root.inspection.identity
    if root_identity is None:
        raise LiteratureStatusProjectionFailedV1(
            "Literature root identity is unavailable"
        )
    writer_active = work_writer_is_active_v1(root_identity, work_id)
    review_counts = {
        "pending": 0,
        "accepted": 0,
        "rejected": 0,
        "deferred": 0,
    }
    handoff_status = "none"
    if authority.ingest_identity_ready:
        ocr = _project_ocr_v1(authority, stages, recovery)
        if ocr is not None:
            canonical = _project_canonical_v1(authority, ocr, stages, recovery)
            if canonical is not None:
                reader = _project_reader_v1(
                    authority,
                    canonical,
                    stages,
                    recovery,
                    writer_active=writer_active,
                )
                if reader is not None:
                    pending_candidate_ids = _project_materialization_v1(
                        authority,
                        canonical,
                        reader,
                        stages,
                        recovery,
                    )
                    if pending_candidate_ids is not None:
                        review_counts, handoff_status = _project_review_v1(
                            authority,
                            pending_candidate_ids,
                            root,
                            stages,
                            recovery,
                        )
    if authority.ingest_identity_ready:
        _project_live_automatic_stage_v1(stages, writer_active=writer_active)
    availability = "partial" if recovery["inconsistent_count"] else "ready"
    return {
        "availability": availability,
        "stages": stages,
        "review_counts": review_counts,
        "handoff_status": handoff_status,
        "recovery": recovery,
        "_status": _work_status(stages, recovery),
    }


def _literature_work_ids(root: ValidatedDataRootV1) -> tuple[str, ...]:
    names = root.relative_entry_names_v1()
    if "works" not in names:
        if names:
            raise LiteratureStatusProjectionFailedV1(
                "Literature root has no bounded Work authority"
            )
        return ()
    with root.open_relative_data_root_v1(("works",)) as works:
        return tuple(
            name
            for name in works.relative_entry_names_v1()
            if name != ".staging" and is_work_id_v1(name)
        )


def project_literature_overall_status_v1(
    root: ValidatedDataRootV1,
) -> dict[str, object]:
    """Project the bounded Literature status summary using the Work projection."""

    names = root.relative_entry_names_v1()
    if not names:
        return {
            "availability": "ready",
            "work_count": 0,
            "work_status_counts": [],
            "pending_review_count": 0,
            "pending_handoff_count": 0,
            "recovery": _recovery(),
        }
    work_ids = _literature_work_ids(root)
    statuses: Counter[str] = Counter()
    pending_review = 0
    pending_handoff = 0
    recovery = _recovery()
    with root.open_relative_data_root_v1(("works",)) as works:
        work_names = works.relative_entry_names_v1()
        recovery["inconsistent_count"] += sum(
            name != ".staging" and not is_work_id_v1(name) for name in work_names
        )
        recovery["staging_count"] += _staging_count(works)
    availability = "ready"
    for work_id in work_ids:
        projected = project_literature_work_status_v1(
            root,
            work_id,
            include_intake_staging=False,
        )
        if projected is None:
            recovery["inconsistent_count"] += 1
            availability = "partial"
            continue
        statuses[cast(str, projected.pop("_status"))] += 1
        review_counts = cast(dict[str, int], projected["review_counts"])
        pending_review += review_counts["pending"]
        if projected["handoff_status"] == "pending":
            pending_handoff += 1
        work_recovery = cast(dict[str, int], projected["recovery"])
        for key in recovery:
            recovery[key] += work_recovery[key]
        if projected["availability"] == "partial":
            availability = "partial"
    if recovery["inconsistent_count"]:
        availability = "partial"
    return {
        "availability": availability,
        "work_count": len(work_ids),
        "work_status_counts": [
            {"status": status, "count": statuses[status]}
            for status in _WORK_STATUS_ORDER
            if statuses[status]
        ],
        "pending_review_count": pending_review,
        "pending_handoff_count": pending_handoff,
        "recovery": recovery,
    }
