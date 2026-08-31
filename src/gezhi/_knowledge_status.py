from __future__ import annotations

import json
import re
from collections import Counter
from typing import cast

from gezhi._windows_data_root import (
    DataRootOpenErrorV1,
    ValidatedDataRootV1,
)

_WORK_ID = re.compile(
    r"^wrk_[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_ANSWER_STATUS_ORDER = ("succeeded", "blocked", "failed", "interrupted")
_ZERO_RECOVERY = {
    "staging_count": 0,
    "orphaned_count": 0,
    "quarantined_count": 0,
    "inconsistent_count": 0,
}


class KnowledgeStatusProjectionFailedV1(RuntimeError):
    """Knowledge cannot form a bounded read-only status projection."""


def _recovery(**changes: int) -> dict[str, int]:
    value = dict(_ZERO_RECOVERY)
    value.update(changes)
    return value


def _staging_payload_count(
    parent: ValidatedDataRootV1,
    name: str,
) -> int:
    names = parent.relative_entry_names_v1()
    if name not in names:
        return 0
    with parent.open_relative_data_root_v1((name,)) as staging:
        staging_names = staging.relative_entry_names_v1()
        count = sum(item != ".files" for item in staging_names)
        if ".files" in staging_names:
            with staging.open_relative_data_root_v1((".files",)) as files:
                count += len(files.relative_entry_names_v1())
        return count


def _read_candidate_projections(
    root: ValidatedDataRootV1,
) -> tuple[tuple[tuple[str, str], ...], frozenset[str], int]:
    from gezhi import _knowledge_read as knowledge_read

    connection = None
    guard = None
    try:
        connection, guard = knowledge_read._open_registry_read_only_v1(root)
        knowledge_read._validate_registry_for_show_v1(connection)
        candidate_rows = connection.execute(
            "SELECT candidate_id FROM candidate_current "
            "ORDER BY candidate_id COLLATE BINARY"
        ).fetchall()
        handoff_rows = connection.execute(
            "SELECT handoff_id FROM handoff_revisions "
            "ORDER BY handoff_id COLLATE BINARY"
        ).fetchall()
        if any(
            type(row) is not tuple or len(row) != 1 or type(row[0]) is not str
            for row in (*candidate_rows, *handoff_rows)
        ):
            raise KnowledgeStatusProjectionFailedV1(
                "Candidate Registry membership is invalid"
            )
        registered_handoffs = frozenset(cast(str, row[0]) for row in handoff_rows)
        observed: list[tuple[str, str]] = []
        inconsistent_count = 0
        for row in candidate_rows:
            candidate_id = cast(str, row[0])
            try:
                result = knowledge_read._show_candidate_v1(
                    connection,
                    root,
                    candidate_id,
                )
            except (
                knowledge_read._CandidateCorruptV1,
                knowledge_read._CandidateNotFoundV1,
                knowledge_read._EvidenceCorruptV1,
            ):
                inconsistent_count += 1
                continue
            candidate = cast(dict[str, object], result["candidate"])
            payload = candidate.get("payload")
            governance = cast(dict[str, object], result["governance"])
            if (
                type(payload) is not dict
                or type(payload.get("work_id")) is not str
                or _WORK_ID.fullmatch(cast(str, payload["work_id"])) is None
                or governance.get("intake_status") not in {"active", "withdrawn"}
            ):
                inconsistent_count += 1
                continue
            observed.append(
                (cast(str, payload["work_id"]), cast(str, governance["intake_status"]))
            )
        guard.revalidate_identity_v1()
        return tuple(observed), registered_handoffs, inconsistent_count
    except KnowledgeStatusProjectionFailedV1:
        raise
    except Exception as error:
        raise KnowledgeStatusProjectionFailedV1(
            "Candidate Registry cannot be projected"
        ) from error
    finally:
        if connection is not None:
            connection.close()
        if guard is not None:
            guard.close()


def _import_facts(
    root: ValidatedDataRootV1,
    registered_handoffs: frozenset[str],
) -> tuple[int, tuple[str, ...], int]:
    names = root.relative_entry_names_v1()
    if "imports" not in names:
        return 0, (), 0
    from gezhi import _knowledge_read as knowledge_read

    staging_count = 0
    orphan_work_ids: list[str] = []
    inconsistent_count = 0
    try:
        with root.open_relative_data_root_v1(("imports",)) as imports:
            import_names = imports.relative_entry_names_v1()
            staging_count = _staging_payload_count(imports, ".staging")
        for name in import_names:
            if name == ".staging" or name in registered_handoffs:
                continue
            try:
                handoff = knowledge_read._read_handoff_v1(root, name)
                if (
                    handoff.handoff_id != name
                    or _WORK_ID.fullmatch(handoff.work_id) is None
                ):
                    raise ValueError("Knowledge import identity differs")
            except Exception:  # noqa: BLE001 - isolate one immutable import target.
                inconsistent_count += 1
            else:
                orphan_work_ids.append(handoff.work_id)
    except DataRootOpenErrorV1 as error:
        raise KnowledgeStatusProjectionFailedV1(
            "Knowledge imports cannot be bounded"
        ) from error
    return staging_count, tuple(orphan_work_ids), inconsistent_count


def _answer_work_ids(retrieval_view_bytes: bytes | None) -> frozenset[str]:
    if retrieval_view_bytes is None:
        return frozenset()
    try:
        value = json.loads(retrieval_view_bytes)
        if (
            type(value) is not dict
            or value.get("schema_version") != "gezhi.retrieval_view.v1"
            or type(value.get("items")) is not list
        ):
            raise ValueError("Retrieval View shape is invalid")
        observed: set[str] = set()
        for item in value["items"]:
            if type(item) is not dict or type(item.get("candidate")) is not dict:
                raise ValueError("Retrieval View Candidate is invalid")
            payload = item["candidate"].get("payload")
            if type(payload) is not dict or type(payload.get("work_id")) is not str:
                raise ValueError("Retrieval View Work binding is invalid")
            work_id = cast(str, payload["work_id"])
            if _WORK_ID.fullmatch(work_id) is None:
                raise ValueError("Retrieval View Work ID is invalid")
            observed.add(work_id)
        return frozenset(observed)
    except (KeyError, TypeError, ValueError) as error:
        raise KnowledgeStatusProjectionFailedV1(
            "validated Answer relation is unavailable"
        ) from error


def _answer_statuses(
    root: ValidatedDataRootV1,
) -> tuple[tuple[tuple[str, frozenset[str]], ...], int, int]:
    names = root.relative_entry_names_v1()
    if "answers" not in names:
        return (), 0, 0
    from gezhi._answer_terminal import (
        TerminalAnswerBytesReadyV1,
        read_committed_answer_v1,
    )

    facts: list[tuple[str, frozenset[str]]] = []
    staging_count = 0
    inconsistent_count = 0
    try:
        with root.open_relative_data_root_v1(("answers",)) as answers:
            for name in answers.relative_entry_names_v1():
                if name == ".staging":
                    staging_count += _staging_payload_count(answers, ".staging")
                    continue
                terminal = read_committed_answer_v1(root, name)
                if type(terminal) is not TerminalAnswerBytesReadyV1:
                    inconsistent_count += 1
                    continue
                facts.append(
                    (
                        terminal.status,
                        _answer_work_ids(terminal.retrieval_view_bytes),
                    )
                )
    except DataRootOpenErrorV1 as error:
        raise KnowledgeStatusProjectionFailedV1(
            "Knowledge Answers cannot be bounded"
        ) from error
    return tuple(facts), staging_count, inconsistent_count


def project_knowledge_status_v1(
    root: ValidatedDataRootV1,
    *,
    work_id: str | None,
) -> dict[str, object]:
    """Project Registry, import evidence, and Answer terminal facts without mutation."""

    names = root.relative_entry_names_v1()
    known = {"registry.sqlite3", "imports", "answers"}
    foreign_count = len(set(names) - known)
    candidates: tuple[tuple[str, str], ...] = ()
    registered_handoffs: frozenset[str] = frozenset()
    candidate_inconsistent = 0
    if "registry.sqlite3" in names:
        (
            candidates,
            registered_handoffs,
            candidate_inconsistent,
        ) = _read_candidate_projections(root)
    import_staging, orphan_work_ids, import_inconsistent = _import_facts(
        root,
        registered_handoffs,
    )
    answer_facts, answer_staging, answer_inconsistent = _answer_statuses(root)
    untrusted_count = (
        foreign_count
        + candidate_inconsistent
        + import_inconsistent
        + answer_inconsistent
    )
    if work_id is None:
        recovery = _recovery(
            staging_count=import_staging + answer_staging,
            orphaned_count=len(orphan_work_ids),
            inconsistent_count=untrusted_count,
        )
        availability = "partial" if untrusted_count else "ready"
        candidate_counts = Counter(status for _work, status in candidates)
        answer_statuses = Counter(status for status, _work_ids in answer_facts)
        return {
            "availability": availability,
            "active_candidate_count": candidate_counts["active"],
            "withdrawn_candidate_count": candidate_counts["withdrawn"],
            "answer_status_counts": [
                {"status": status, "count": answer_statuses[status]}
                for status in _ANSWER_STATUS_ORDER
                if answer_statuses[status]
            ],
            "recovery": recovery,
        }
    candidate_counts = Counter(
        status for candidate_work, status in candidates if candidate_work == work_id
    )
    related_answer_statuses = Counter(
        status for status, work_ids in answer_facts if work_id in work_ids
    )
    return {
        "availability": "partial" if untrusted_count else "ready",
        "candidate_counts": {
            "active": candidate_counts["active"],
            "withdrawn": candidate_counts["withdrawn"],
        },
        "related_answer_status_counts": [
            {"status": status, "count": related_answer_statuses[status]}
            for status in _ANSWER_STATUS_ORDER
            if related_answer_statuses[status]
        ],
        "recovery": _recovery(
            orphaned_count=sum(orphan == work_id for orphan in orphan_work_ids)
        ),
    }
