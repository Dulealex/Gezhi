from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from support.reviewed_handoff_witness_v1 import (
    ACCEPT_CANDIDATES_V1,
    ACCEPT_MANIFEST_V1,
)


def canonical_file_bytes_v1(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


@dataclass(frozen=True, slots=True)
class SyntheticHandoffV1:
    manifest_bytes: bytes
    candidates_bytes: bytes

    @property
    def candidate(self) -> dict[str, object]:
        value = json.loads(self.candidates_bytes)
        candidate = value["candidate"]
        assert type(candidate) is dict
        return candidate

    @property
    def candidate_id(self) -> str:
        value = self.candidate["candidate_id"]
        assert type(value) is str
        return value


def _handoff_id(
    *,
    action: str,
    candidate_id: str,
    payload_sha256: str,
    review_revision: int,
) -> str:
    identity = {
        "action": action,
        "candidate_id": candidate_id,
        "payload_sha256": payload_sha256,
        "review_revision": review_revision,
        "schema_version": "gezhi.reviewed_handoff_identity.v1",
    }
    return (
        "hnd_" + hashlib.sha256(canonical_file_bytes_v1(identity)[:-1]).hexdigest()[:24]
    )


def accepted_handoff_v1(
    *,
    ordinal: int,
    statement_text: str,
    source_terms: list[str],
    title: str = "Synthetic Work",
    review_revision: int = 1,
) -> SyntheticHandoffV1:
    record = json.loads(ACCEPT_CANDIDATES_V1)
    manifest = json.loads(ACCEPT_MANIFEST_V1)
    work_id = f"wrk_00000000-0000-4000-8000-{ordinal:012x}"
    block_id = (
        "blk_" + hashlib.sha256(f"{ordinal}:{statement_text}".encode()).hexdigest()[:24]
    )

    candidate = record["candidate"]
    payload = candidate["payload"]
    statement = payload["statement"]
    statement["text"] = statement_text
    statement["source_terms"] = sorted(
        source_terms,
        key=lambda value: value.encode("utf-8"),
    )
    statement["evidence_pointers"][0]["block_id"] = block_id
    payload["work_id"] = work_id
    payload_sha256 = hashlib.sha256(canonical_file_bytes_v1(payload)[:-1]).hexdigest()
    candidate_id = "cand_" + payload_sha256[:24]
    candidate["candidate_id"] = candidate_id
    candidate["payload_sha256"] = payload_sha256

    record["citation"]["title"] = title
    record["citation"]["work_id"] = work_id
    record["evidence_snapshots"][0]["pointer"]["block_id"] = block_id
    record["review_receipt"]["review_revision"] = review_revision
    candidates_bytes = canonical_file_bytes_v1(record)

    canonical_run_id = "canrun_00000000-0000-4000-8000-000000000001"
    semantic_run_id = "semrun_00000000-0000-4000-8000-000000000002"
    manifest["work_id"] = work_id
    manifest["canonical_run_id"] = canonical_run_id
    manifest["provenance"] = {
        "canonical_run_id": canonical_run_id,
        "semantic_run_id": semantic_run_id,
    }
    manifest["candidates_sha256"] = hashlib.sha256(candidates_bytes).hexdigest()
    manifest["handoff_id"] = _handoff_id(
        action="accept",
        candidate_id=candidate_id,
        payload_sha256=payload_sha256,
        review_revision=review_revision,
    )
    return SyntheticHandoffV1(canonical_file_bytes_v1(manifest), candidates_bytes)


def withdrawn_handoff_v1(
    accepted: SyntheticHandoffV1,
    *,
    review_revision: int,
    review_status: str = "rejected",
) -> SyntheticHandoffV1:
    candidate = accepted.candidate
    candidate_id = candidate["candidate_id"]
    payload_sha256 = candidate["payload_sha256"]
    assert type(candidate_id) is str
    assert type(payload_sha256) is str
    if review_status not in {"rejected", "deferred"}:
        raise ValueError("withdraw review status is invalid")
    record = {
        "action": "withdraw",
        "candidate_id": candidate_id,
        "payload_sha256": payload_sha256,
        "review_receipt": {
            "review_revision": review_revision,
            "review_status": review_status,
            "reviewer_kind": "local_human_cli",
        },
        "schema_version": "gezhi.reviewed_candidate_action.v1",
    }
    candidates_bytes = canonical_file_bytes_v1(record)
    manifest = json.loads(accepted.manifest_bytes)
    manifest["candidates_sha256"] = hashlib.sha256(candidates_bytes).hexdigest()
    manifest["handoff_id"] = _handoff_id(
        action="withdraw",
        candidate_id=candidate_id,
        payload_sha256=payload_sha256,
        review_revision=review_revision,
    )
    return SyntheticHandoffV1(canonical_file_bytes_v1(manifest), candidates_bytes)


__all__ = [
    "SyntheticHandoffV1",
    "accepted_handoff_v1",
    "canonical_file_bytes_v1",
    "withdrawn_handoff_v1",
]
