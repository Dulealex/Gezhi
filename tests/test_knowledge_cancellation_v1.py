from __future__ import annotations

from dataclasses import dataclass

import pytest

from gezhi._knowledge_cancellation import (
    CancellationSnapshotV1,
    KnowledgeCancellationBridgeErrorV1,
    NoInteractiveCancellationBridgeV1,
    _classify_console_cancellation_capability_v1,
    _NativeCancellationApiV1,
    _validated_native_snapshot_v1,
    _verified_native_dll_path_v1,
)


@dataclass(slots=True)
class _CapabilityApiDouble:
    handle: int | None
    mode_result: tuple[bool, int]
    close_succeeds: bool = True
    close_calls: int = 0

    def open_console_input_v1(self) -> int | None:
        return self.handle

    def get_console_mode_v1(self, handle: int) -> tuple[bool, int]:
        assert handle == self.handle
        return self.mode_result

    def close_handle_v1(self, handle: int) -> bool:
        assert handle == self.handle
        self.close_calls += 1
        return self.close_succeeds


@pytest.mark.parametrize(
    ("handle", "mode_result", "expected", "close_calls"),
    [
        (None, (False, 0), "capability_absent", 0),
        (41, (False, 0), "capability_absent", 1),
        (42, (True, 0), "capability_absent", 1),
        (43, (True, 1), "interactive_candidate", 1),
    ],
)
def test_console_capability_uses_only_read_only_conin_processed_input(
    handle: int | None,
    mode_result: tuple[bool, int],
    expected: str,
    close_calls: int,
) -> None:
    api = _CapabilityApiDouble(handle=handle, mode_result=mode_result)

    assert _classify_console_cancellation_capability_v1(api) == expected
    assert api.close_calls == close_calls


def test_console_capability_refuses_to_hide_a_close_failure() -> None:
    api = _CapabilityApiDouble(
        handle=44,
        mode_result=(False, 0),
        close_succeeds=False,
    )

    with pytest.raises(RuntimeError, match="close proof"):
        _classify_console_cancellation_capability_v1(api)


def test_redirected_standard_input_does_not_override_a_valid_conin_proof() -> None:
    api = _CapabilityApiDouble(handle=45, mode_result=(True, 1))

    assert _classify_console_cancellation_capability_v1(api) == "interactive_candidate"
    assert api.close_calls == 1


def test_packaged_native_bridge_has_the_frozen_hash_and_x64_pe_identity() -> None:
    verified = _verified_native_dll_path_v1()

    assert verified.name == "gezhi_cancel_v1.dll"
    assert verified.stat().st_size == 107_008


@pytest.mark.parametrize(
    ("raw_export", "method"),
    (
        ("_try_begin_work", "try_begin_work_v1"),
        ("_try_answer_id_cutover", "try_answer_id_cutover_v1"),
    ),
)
def test_native_boolean_admission_rejects_a_poison_proof_sentinel(
    raw_export: str,
    method: str,
) -> None:
    api = object.__new__(_NativeCancellationApiV1)
    setattr(api, raw_export, lambda: -1)

    with pytest.raises(KnowledgeCancellationBridgeErrorV1, match="proof failed"):
        getattr(api, method)()


@pytest.mark.parametrize(
    (
        "phase",
        "generation",
        "latched",
        "observed_ns",
        "accepted_in_flight",
        "publication_ready",
        "sealed_token",
    ),
    (
        ("accepting", 0, 0, 0, 0, 1, 0),
        ("accepting", 0, 0, 1, 0, 0, 0),
        ("accepting", 1, 0, 0, 0, 0, 0),
        ("accepting", 0, 1, 0, 0, 1, 0),
        ("accepting", 1, 1, -1, 0, 1, 0),
        ("accepting", 1, 1, 1, 0, 1, 7),
        ("sealed", 0, 0, 0, 0, 0, 0),
        ("released", 0, 0, 0, 1, 0, 7),
    ),
)
def test_native_snapshot_rejects_every_incoherent_lifecycle_combination(
    phase: str,
    generation: int,
    latched: int,
    observed_ns: int,
    accepted_in_flight: int,
    publication_ready: int,
    sealed_token: int,
) -> None:
    with pytest.raises(RuntimeError, match="snapshot fields"):
        _validated_native_snapshot_v1(
            phase=phase,
            generation=generation,
            latched=latched,
            observed_ns=observed_ns,
            accepted_in_flight=accepted_in_flight,
            publication_ready=publication_ready,
            sealed_candidate_token=sealed_token,
        )


@pytest.mark.parametrize(
    "expected",
    (
        CancellationSnapshotV1("outside", 0, None, 0, False, 0),
        CancellationSnapshotV1("armed", 0, None, 0, False, 0),
        CancellationSnapshotV1("accepting", 0, None, 0, False, 0),
        CancellationSnapshotV1("accepting", 2, 5, 1, True, 0),
        CancellationSnapshotV1("sealed", 2, 5, 0, True, 7),
        CancellationSnapshotV1("released", 0, None, 0, False, 7),
    ),
)
def test_native_snapshot_accepts_only_coherent_lifecycle_combinations(
    expected: CancellationSnapshotV1,
) -> None:
    assert (
        _validated_native_snapshot_v1(
            phase=expected.phase,
            generation=expected.generation,
            latched=int(expected.observed_monotonic_ns is not None),
            observed_ns=expected.observed_monotonic_ns or 0,
            accepted_in_flight=expected.accepted_in_flight,
            publication_ready=int(expected.publication_ready),
            sealed_candidate_token=expected.sealed_candidate_token,
        )
        == expected
    )


def test_no_source_profile_runs_the_full_seal_and_release_lifecycle() -> None:
    bridge = NoInteractiveCancellationBridgeV1.activate_v1(
        selection_reason="capability_absent"
    )

    assert bridge.observed_at_monotonic_ns() is None
    assert bridge.try_begin_work_v1() is True
    assert bridge.try_answer_id_cutover_v1() is True
    with pytest.raises(RuntimeError, match="cutover"):
        bridge.try_answer_id_cutover_v1()
    assert bridge.snapshot_v1() == CancellationSnapshotV1(
        phase="accepting",
        generation=0,
        observed_monotonic_ns=None,
        accepted_in_flight=0,
        publication_ready=False,
        sealed_candidate_token=0,
    )
    assert bridge.conditional_seal_v1(
        expected_generation=0,
        candidate_token=1,
    )
    bridge.release_v1()
    assert bridge.snapshot_v1() == CancellationSnapshotV1(
        phase="released",
        generation=0,
        observed_monotonic_ns=None,
        accepted_in_flight=0,
        publication_ready=False,
        sealed_candidate_token=1,
    )


def test_no_source_profile_rejects_reused_or_zero_candidate_tokens() -> None:
    bridge = NoInteractiveCancellationBridgeV1.activate_v1(
        selection_reason="debugger_present"
    )

    with pytest.raises(ValueError, match="candidate token"):
        bridge.conditional_seal_v1(
            expected_generation=0,
            candidate_token=0,
        )
    assert bridge.conditional_seal_v1(
        expected_generation=0,
        candidate_token=7,
    )
    with pytest.raises(RuntimeError, match="phase"):
        bridge.conditional_seal_v1(
            expected_generation=0,
            candidate_token=8,
        )
