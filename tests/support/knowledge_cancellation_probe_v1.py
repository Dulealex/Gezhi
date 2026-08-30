from __future__ import annotations

import ctypes
import json
import sys
import threading
from pathlib import Path


def _bind_native_test_dll(path: Path) -> ctypes.WinDLL:
    dll = ctypes.WinDLL(str(path), use_last_error=True)
    dll.gezhi_cancel_v1_arm.argtypes = []
    dll.gezhi_cancel_v1_arm.restype = ctypes.c_int
    dll.gezhi_cancel_v1_activate.argtypes = []
    dll.gezhi_cancel_v1_activate.restype = ctypes.c_int
    dll.gezhi_cancel_v1_try_begin_work.argtypes = []
    dll.gezhi_cancel_v1_try_begin_work.restype = ctypes.c_int
    dll.gezhi_cancel_v1_try_answer_id_cutover.argtypes = []
    dll.gezhi_cancel_v1_try_answer_id_cutover.restype = ctypes.c_int
    dll.gezhi_cancel_v1_snapshot.argtypes = [
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int64),
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_uint32),
    ]
    dll.gezhi_cancel_v1_snapshot.restype = ctypes.c_int
    dll.gezhi_cancel_v1_conditional_seal.argtypes = [
        ctypes.c_uint32,
        ctypes.c_uint32,
    ]
    dll.gezhi_cancel_v1_conditional_seal.restype = ctypes.c_int
    dll.gezhi_cancel_v1_release.argtypes = []
    dll.gezhi_cancel_v1_release.restype = ctypes.c_int
    dll.gezhi_cancel_v1_test_dispatch.argtypes = [ctypes.c_uint32]
    dll.gezhi_cancel_v1_test_dispatch.restype = ctypes.c_int
    dll.gezhi_cancel_v1_test_begin_poison_publication.argtypes = []
    dll.gezhi_cancel_v1_test_begin_poison_publication.restype = ctypes.c_int
    dll.gezhi_cancel_v1_test_finish_poison_publication.argtypes = []
    dll.gezhi_cancel_v1_test_finish_poison_publication.restype = ctypes.c_int
    dll.gezhi_cancel_v1_test_poison_before_next_seal_gate.argtypes = []
    dll.gezhi_cancel_v1_test_poison_before_next_seal_gate.restype = ctypes.c_int
    dll.gezhi_cancel_v1_test_poison_before_next_seal_commit.argtypes = []
    dll.gezhi_cancel_v1_test_poison_before_next_seal_commit.restype = ctypes.c_int
    return dll


def _snapshot(dll: ctypes.WinDLL) -> tuple[int, int, int, int, int, int, int]:
    phase = ctypes.c_uint32()
    generation = ctypes.c_uint32()
    latched = ctypes.c_int()
    observed_ns = ctypes.c_int64()
    in_flight = ctypes.c_uint32()
    publication_ready = ctypes.c_int()
    sealed_token = ctypes.c_uint32()
    assert (
        dll.gezhi_cancel_v1_snapshot(
            ctypes.byref(phase),
            ctypes.byref(generation),
            ctypes.byref(latched),
            ctypes.byref(observed_ns),
            ctypes.byref(in_flight),
            ctypes.byref(publication_ready),
            ctypes.byref(sealed_token),
        )
        == 1
    )
    return (
        phase.value,
        generation.value,
        latched.value,
        observed_ns.value,
        in_flight.value,
        publication_ready.value,
        sealed_token.value,
    )


def _normalize_ctrl_c_ignore_v1() -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    setter = kernel32.SetConsoleCtrlHandler
    setter.argtypes = [ctypes.c_void_p, ctypes.c_int]
    setter.restype = ctypes.c_int
    assert setter(None, False) != 0


def _activate_test_dll_v1(path: Path) -> ctypes.WinDLL:
    dll = _bind_native_test_dll(path)
    assert dll.gezhi_cancel_v1_arm() == 1
    _normalize_ctrl_c_ignore_v1()
    assert dll.gezhi_cancel_v1_activate() == 1
    assert _snapshot(dll) == (2, 0, 0, 0, 0, 0, 0)
    return dll


def _dispatch_first_v1(path: Path) -> dict[str, object]:
    dll = _activate_test_dll_v1(path)
    assert dll.gezhi_cancel_v1_try_begin_work() == 1
    assert dll.gezhi_cancel_v1_test_dispatch(1) == 0
    assert dll.gezhi_cancel_v1_test_dispatch(0) == 1
    phase, generation, latched, observed_ns, in_flight, ready, token = _snapshot(dll)
    assert (phase, generation, latched, in_flight, ready, token) == (
        2,
        1,
        1,
        0,
        1,
        0,
    )
    assert observed_ns > 0
    assert dll.gezhi_cancel_v1_try_begin_work() == 0
    assert dll.gezhi_cancel_v1_try_answer_id_cutover() == 0
    assert dll.gezhi_cancel_v1_conditional_seal(0, 8) == 0
    assert dll.gezhi_cancel_v1_conditional_seal(1, 9) == 1
    assert dll.gezhi_cancel_v1_test_dispatch(0) == 0
    assert dll.gezhi_cancel_v1_release() == 1
    assert _snapshot(dll) == (4, 1, 1, observed_ns, 0, 1, 9)
    return {"mode": "dispatch-first", "observed_ns": observed_ns}


def _cutover_first_v1(path: Path) -> dict[str, object]:
    dll = _activate_test_dll_v1(path)
    assert dll.gezhi_cancel_v1_try_answer_id_cutover() == 1
    assert _snapshot(dll) == (5, 0, 0, 0, 0, 0, 0)
    assert dll.gezhi_cancel_v1_test_dispatch(0) == 1
    phase, generation, latched, observed_ns, in_flight, ready, token = _snapshot(dll)
    assert (phase, generation, latched, in_flight, ready, token) == (
        5,
        1,
        1,
        0,
        1,
        0,
    )
    assert observed_ns > 0
    assert dll.gezhi_cancel_v1_conditional_seal(1, 17) == 1
    assert dll.gezhi_cancel_v1_release() == 1
    assert _snapshot(dll) == (4, 1, 1, observed_ns, 0, 1, 17)
    return {"mode": "cutover-first", "observed_ns": observed_ns}


def _concurrent_callbacks_v1(path: Path) -> dict[str, object]:
    dll = _activate_test_dll_v1(path)
    results: list[int] = []
    workers = [
        threading.Thread(
            target=lambda: results.append(dll.gezhi_cancel_v1_test_dispatch(0))
        )
        for _index in range(8)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=5)
        assert not worker.is_alive()
    assert results == [1] * 8
    phase, generation, latched, observed_ns, in_flight, ready, token = _snapshot(dll)
    assert (phase, generation, latched, in_flight, ready, token) == (
        2,
        8,
        1,
        0,
        1,
        0,
    )
    assert observed_ns > 0
    assert dll.gezhi_cancel_v1_conditional_seal(8, 29) == 1
    assert dll.gezhi_cancel_v1_release() == 1
    return {"generation": generation, "mode": "concurrent-callbacks"}


def _poisoned_publication_v1(path: Path) -> dict[str, object]:
    dll = _activate_test_dll_v1(path)
    assert dll.gezhi_cancel_v1_test_begin_poison_publication() == 1
    assert dll.gezhi_cancel_v1_try_answer_id_cutover() == 0
    assert dll.gezhi_cancel_v1_test_finish_poison_publication() == 1
    assert dll.gezhi_cancel_v1_try_begin_work() == -1
    assert dll.gezhi_cancel_v1_try_answer_id_cutover() == -1
    return {"mode": "poisoned-publication", "proof": "rejected"}


def _seal_poison_race_v1(path: Path) -> dict[str, object]:
    dll = _activate_test_dll_v1(path)
    assert dll.gezhi_cancel_v1_test_poison_before_next_seal_gate() == 1
    assert dll.gezhi_cancel_v1_conditional_seal(0, 37) == -1
    assert dll.gezhi_cancel_v1_try_begin_work() == -1
    return {"mode": "seal-poison-race", "proof": "rejected"}


def _seal_poison_after_gate_v1(path: Path) -> dict[str, object]:
    dll = _activate_test_dll_v1(path)
    assert dll.gezhi_cancel_v1_test_poison_before_next_seal_commit() == 1
    assert dll.gezhi_cancel_v1_conditional_seal(0, 41) == -1
    assert dll.gezhi_cancel_v1_try_begin_work() == -1
    return {"mode": "seal-poison-after-gate", "proof": "rejected"}


def _interactive_profile_v1() -> dict[str, object]:
    from gezhi._knowledge_cancellation import (
        WindowsConsoleCancellationBridgeV1,
        activate_knowledge_ask_cancellation_v1,
    )

    bridge = activate_knowledge_ask_cancellation_v1()
    assert type(bridge) is WindowsConsoleCancellationBridgeV1
    assert bridge.try_answer_id_cutover_v1() is True
    snapshot = bridge.snapshot_v1()
    assert snapshot.phase == "accepting"
    assert snapshot.generation == 0
    assert snapshot.observed_monotonic_ns is None
    assert bridge.conditional_seal_v1(
        expected_generation=0,
        candidate_token=23,
    )
    bridge.release_v1()
    released = bridge.snapshot_v1()
    assert released.phase == "released"
    return {"mode": "interactive-profile", "source": "native"}


def main() -> int:
    if len(sys.argv) not in {2, 3}:
        raise SystemExit("usage: probe MODE [DLL]")
    mode = sys.argv[1]
    if mode == "interactive-profile":
        receipt = _interactive_profile_v1()
    else:
        if len(sys.argv) != 3:
            raise SystemExit("test-DLL mode requires a DLL path")
        path = Path(sys.argv[2])
        if mode == "dispatch-first":
            receipt = _dispatch_first_v1(path)
        elif mode == "cutover-first":
            receipt = _cutover_first_v1(path)
        elif mode == "concurrent-callbacks":
            receipt = _concurrent_callbacks_v1(path)
        elif mode == "poisoned-publication":
            receipt = _poisoned_publication_v1(path)
        elif mode == "seal-poison-race":
            receipt = _seal_poison_race_v1(path)
        elif mode == "seal-poison-after-gate":
            receipt = _seal_poison_after_gate_v1(path)
        else:
            raise SystemExit("unknown probe mode")
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
