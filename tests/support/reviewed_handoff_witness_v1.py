from __future__ import annotations

ACCEPT_CANDIDATES_V1 = (
    '{"action":"accept","candidate":{"candidate_id":"cand_3a421e895f79e2c167e2ef4b","payload":{"candidate_type":"claim","canonical_content_sha256":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","descriptor_refs":[],"schema_version":"gezhi.candidate_payload.v1","source_id":"src_bbbbbbbbbbbbbbbbbbbbbbbb","source_sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","statement":{"evidence_pointers":[{"block_id":"block-001","canonical_content_sha256":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","schema_version":"gezhi.evidence_pointer.v1"}],"risk_flags":[],"source_terms":["source term"],"support_kind":"direct","text":"示例结论"},"work_id":"wrk_123e4567-e89b-42d3-a456-426614174000"},"payload_sha256":"3a421e895f79e2c167e2ef4b4f42ece44839ca487c11e6659870904f268eabf1","schema_version":"gezhi.candidate_knowledge.v1"},"citation":{"arxiv_id":null,"author_count":1,"doi":null,"primary_authors":["张三"],"source_id":"src_bbbbbbbbbbbbbbbbbbbbbbbb","source_sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","title":"示例论文","work_id":"wrk_123e4567-e89b-42d3-a456-426614174000","year":2024},"descriptor_snapshots":[],"evidence_snapshots":[{"excerpt":"Example evidence.","page_index":null,"pointer":{"block_id":"block-001","canonical_content_sha256":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","schema_version":"gezhi.evidence_pointer.v1"}}],"review_receipt":{"review_revision":1,"review_status":"accepted","reviewer_kind":"local_human_cli"},"schema_version":"gezhi.reviewed_candidate_action.v1"}\n'
).encode()

ACCEPT_MANIFEST_V1 = (
    b'{"candidates_sha256":"9a9724ea798c15059e06b2bb60aef971ec491af0f43b4a68745b5c0b01e3c507","canonical_content_sha256":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","canonical_run_id":"canonical_fixture_001","handoff_id":"hnd_a90bf219d563804b283af452","provenance":{"canonical_run_id":"canonical_fixture_001","semantic_run_id":"semantic_fixture_001"},"record_count":1,"schema_version":"gezhi.reviewed_handoff_manifest.v1","source_id":"src_bbbbbbbbbbbbbbbbbbbbbbbb","source_sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","work_id":"wrk_123e4567-e89b-42d3-a456-426614174000"}\n'
)

WITHDRAW_CANDIDATES_V1 = (
    b'{"action":"withdraw","candidate_id":"cand_3a421e895f79e2c167e2ef4b","payload_sha256":"3a421e895f79e2c167e2ef4b4f42ece44839ca487c11e6659870904f268eabf1","review_receipt":{"review_revision":2,"review_status":"rejected","reviewer_kind":"local_human_cli"},"schema_version":"gezhi.reviewed_candidate_action.v1"}\n'
)

WITHDRAW_MANIFEST_V1 = (
    b'{"candidates_sha256":"0eb7acfdbb5b679171ffa4b898393d2d58fe9300a61f509711b5659dd99f0d9e","canonical_content_sha256":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","canonical_run_id":"canonical_fixture_001","handoff_id":"hnd_39cf03ad1f8fd432e3b83a5b","provenance":{"canonical_run_id":"canonical_fixture_001","semantic_run_id":"semantic_fixture_001"},"record_count":1,"schema_version":"gezhi.reviewed_handoff_manifest.v1","source_id":"src_bbbbbbbbbbbbbbbbbbbbbbbb","source_sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","work_id":"wrk_123e4567-e89b-42d3-a456-426614174000"}\n'
)

REACCEPT_CANDIDATES_V1 = ACCEPT_CANDIDATES_V1.replace(
    b'"review_revision":1',
    b'"review_revision":3',
)
REACCEPT_MANIFEST_V1 = (
    ACCEPT_MANIFEST_V1.replace(
        b"9a9724ea798c15059e06b2bb60aef971ec491af0f43b4a68745b5c0b01e3c507",
        b"bf637498ec6b94a0602065d2f3430afe0a55b7ff077f61cf6eeb110d5a08e25b",
    ).replace(
        b"hnd_a90bf219d563804b283af452",
        b"hnd_8ca3faee9a3a985c08b4c17c",
    )
)

CANDIDATE_ID_V1 = "cand_3a421e895f79e2c167e2ef4b"
HANDOFF_ID_ACCEPT_V1 = "hnd_a90bf219d563804b283af452"
HANDOFF_ID_WITHDRAW_V1 = "hnd_39cf03ad1f8fd432e3b83a5b"
HANDOFF_ID_REACCEPT_V1 = "hnd_8ca3faee9a3a985c08b4c17c"
PAYLOAD_SHA256_V1 = (
    "3a421e895f79e2c167e2ef4b4f42ece44839ca487c11e6659870904f268eabf1"
)
