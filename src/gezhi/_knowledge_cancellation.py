from __future__ import annotations

import ctypes
import hashlib
import struct
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, TypeAlias

CancellationPhaseV1: TypeAlias = Literal[
    "outside",
    "armed",
    "accepting",
    "sealed",
    "released",
]
CancellationSelectionReasonV1: TypeAlias = Literal[
    "capability_absent",
    "debugger_present",
]
ConsoleCancellationCapabilityV1: TypeAlias = Literal[
    "capability_absent",
    "interactive_candidate",
]

_ENABLE_PROCESSED_INPUT = 0x0001
_GENERIC_READ = 0x80000000
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_OPEN_EXISTING = 3
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_MAX_CANDIDATE_TOKEN = 0xFFFFFFFF
_NATIVE_DLL_SHA256 = "27d9fad527ea1525f212aad3974ecbd7bc26026713f38583d055525be72c0d8d"
_NATIVE_DLL_MAX_BYTES = 262_144
_NATIVE_DLL_PATH = Path(__file__).with_name("_native") / "gezhi_cancel_v1.dll"
_NATIVE_PHASES: dict[int, CancellationPhaseV1] = {
    0: "outside",
    1: "armed",
    2: "accepting",
    3: "sealed",
    4: "released",
    5: "accepting",
}
_PINNED_NATIVE_DLL: ctypes.WinDLL | None = None


class KnowledgeCancellationBridgeErrorV1(RuntimeError):
    """The cancellation adapter cannot prove its frozen lifecycle."""


@dataclass(frozen=True, slots=True)
class CancellationSnapshotV1:
    phase: CancellationPhaseV1
    generation: int
    observed_monotonic_ns: int | None
    accepted_in_flight: int
    publication_ready: bool
    sealed_candidate_token: int


class KnowledgeCancellationBridgeV1(Protocol):
    def observed_at_monotonic_ns(self) -> int | None: ...

    def try_begin_work_v1(self) -> bool: ...

    def try_answer_id_cutover_v1(self) -> bool: ...

    def snapshot_v1(self) -> CancellationSnapshotV1: ...

    def conditional_seal_v1(
        self,
        *,
        expected_generation: int,
        candidate_token: int,
    ) -> bool: ...

    def release_v1(self) -> None: ...


class _ConsoleCapabilityApiV1(Protocol):
    def open_console_input_v1(self) -> int | None: ...

    def get_console_mode_v1(self, handle: int) -> tuple[bool, int]: ...

    def close_handle_v1(self, handle: int) -> bool: ...


class _WindowsConsoleCapabilityApiV1:
    def __init__(self) -> None:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32 = kernel32
        self._create_file = kernel32.CreateFileW
        self._create_file.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_void_p,
        ]
        self._create_file.restype = ctypes.c_void_p
        self._get_console_mode = kernel32.GetConsoleMode
        self._get_console_mode.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_ulong),
        ]
        self._get_console_mode.restype = ctypes.c_int
        self._close_handle = kernel32.CloseHandle
        self._close_handle.argtypes = [ctypes.c_void_p]
        self._close_handle.restype = ctypes.c_int

    def open_console_input_v1(self) -> int | None:
        raw = self._create_file(
            "CONIN$",
            _GENERIC_READ,
            _FILE_SHARE_READ | _FILE_SHARE_WRITE,
            None,
            _OPEN_EXISTING,
            0,
            None,
        )
        value = None if raw is None else int(raw)
        return None if value in {None, _INVALID_HANDLE_VALUE} else value

    def get_console_mode_v1(self, handle: int) -> tuple[bool, int]:
        mode = ctypes.c_ulong()
        succeeded = bool(self._get_console_mode(handle, ctypes.byref(mode)))
        return succeeded, int(mode.value) if succeeded else 0

    def close_handle_v1(self, handle: int) -> bool:
        return bool(self._close_handle(handle))


def _classify_console_cancellation_capability_v1(
    api: _ConsoleCapabilityApiV1,
) -> ConsoleCancellationCapabilityV1:
    handle = api.open_console_input_v1()
    if handle is None:
        return "capability_absent"
    try:
        succeeded, mode = api.get_console_mode_v1(handle)
    finally:
        if not api.close_handle_v1(handle):
            raise KnowledgeCancellationBridgeErrorV1(
                "Console capability close proof failed"
            )
    if type(succeeded) is not bool or type(mode) is not int or mode < 0:
        raise KnowledgeCancellationBridgeErrorV1("Console capability result is invalid")
    return (
        "interactive_candidate"
        if succeeded and mode & _ENABLE_PROCESSED_INPUT
        else "capability_absent"
    )


class NoInteractiveCancellationBridgeV1:
    """Logical no-source profile with the same one-shot lifecycle."""

    def __init__(self, selection_reason: CancellationSelectionReasonV1) -> None:
        if selection_reason not in {"capability_absent", "debugger_present"}:
            raise ValueError("Cancellation selection reason is invalid")
        self._selection_reason = selection_reason
        self._phase: CancellationPhaseV1 = "outside"
        self._sealed_candidate_token = 0
        self._answer_id_cutover = False

    @classmethod
    def activate_v1(
        cls,
        *,
        selection_reason: CancellationSelectionReasonV1,
    ) -> NoInteractiveCancellationBridgeV1:
        bridge = cls(selection_reason)
        bridge._phase = "armed"
        bridge._phase = "accepting"
        return bridge

    def observed_at_monotonic_ns(self) -> None:
        return None

    def _require_accepting_v1(self) -> None:
        if self._phase != "accepting":
            raise KnowledgeCancellationBridgeErrorV1(
                "Cancellation profile phase is not accepting"
            )

    def try_begin_work_v1(self) -> bool:
        self._require_accepting_v1()
        return True

    def try_answer_id_cutover_v1(self) -> bool:
        self._require_accepting_v1()
        if self._answer_id_cutover:
            raise KnowledgeCancellationBridgeErrorV1(
                "Answer identity cutover was already completed"
            )
        self._answer_id_cutover = True
        return True

    def snapshot_v1(self) -> CancellationSnapshotV1:
        return CancellationSnapshotV1(
            phase=self._phase,
            generation=0,
            observed_monotonic_ns=None,
            accepted_in_flight=0,
            publication_ready=False,
            sealed_candidate_token=self._sealed_candidate_token,
        )

    def conditional_seal_v1(
        self,
        *,
        expected_generation: int,
        candidate_token: int,
    ) -> bool:
        self._require_accepting_v1()
        if type(expected_generation) is not int or expected_generation != 0:
            raise ValueError("Cancellation expected generation is invalid")
        if (
            type(candidate_token) is not int
            or not 1 <= candidate_token <= _MAX_CANDIDATE_TOKEN
        ):
            raise ValueError("Cancellation candidate token is invalid")
        if self._sealed_candidate_token != 0:
            raise KnowledgeCancellationBridgeErrorV1(
                "Cancellation candidate token was already sealed"
            )
        self._sealed_candidate_token = candidate_token
        self._phase = "sealed"
        return True

    def release_v1(self) -> None:
        if self._phase != "sealed":
            raise KnowledgeCancellationBridgeErrorV1(
                "Cancellation profile phase cannot be released"
            )
        if self._sealed_candidate_token == 0:
            raise KnowledgeCancellationBridgeErrorV1(
                "Cancellation sealed candidate proof is absent"
            )
        self._phase = "released"


def _verified_native_dll_path_v1() -> Path:
    try:
        size = _NATIVE_DLL_PATH.stat().st_size
        if not 0 < size <= _NATIVE_DLL_MAX_BYTES:
            raise ValueError("Native cancellation DLL size is invalid")
        payload = _NATIVE_DLL_PATH.read_bytes()
    except OSError as error:
        raise KnowledgeCancellationBridgeErrorV1(
            "Native cancellation DLL is unavailable"
        ) from error
    if (
        len(payload) != size
        or hashlib.sha256(payload).hexdigest() != _NATIVE_DLL_SHA256
    ):
        raise KnowledgeCancellationBridgeErrorV1(
            "Native cancellation DLL identity differs"
        )
    try:
        if payload[:2] != b"MZ":
            raise ValueError("DOS identity differs")
        pe_offset = struct.unpack_from("<I", payload, 0x3C)[0]
        if payload[pe_offset : pe_offset + 4] != b"PE\0\0":
            raise ValueError("PE identity differs")
        machine = struct.unpack_from("<H", payload, pe_offset + 4)[0]
    except (IndexError, struct.error, ValueError) as error:
        raise KnowledgeCancellationBridgeErrorV1(
            "Native cancellation DLL format is invalid"
        ) from error
    if machine != 0x8664:
        raise KnowledgeCancellationBridgeErrorV1(
            "Native cancellation DLL is not Windows x64"
        )
    return _NATIVE_DLL_PATH


def _validated_native_snapshot_v1(
    *,
    phase: CancellationPhaseV1,
    generation: int,
    latched: int,
    observed_ns: int,
    accepted_in_flight: int,
    publication_ready: int,
    sealed_candidate_token: int,
) -> CancellationSnapshotV1:
    valid_phase = phase in {"outside", "armed", "accepting", "sealed", "released"}
    scalar_fields_are_valid = (
        type(generation) is int
        and 0 <= generation <= 0x0FFFFFFF
        and latched in {0, 1}
        and type(observed_ns) is int
        and type(accepted_in_flight) is int
        and 0 <= accepted_in_flight <= 0xFFFFFFFF
        and publication_ready in {0, 1}
        and type(sealed_candidate_token) is int
        and 0 <= sealed_candidate_token <= _MAX_CANDIDATE_TOKEN
    )
    observation_is_coherent = (
        latched == publication_ready == 0 and generation == 0 and observed_ns == 0
    ) or (latched == publication_ready == 1 and generation > 0 and observed_ns >= 0)
    phase_is_coherent = (phase not in {"outside", "armed"} or latched == 0) and (
        phase == "accepting" or accepted_in_flight == 0
    )
    token_is_coherent = (
        phase in {"sealed", "released"} and sealed_candidate_token > 0
    ) or (phase in {"outside", "armed", "accepting"} and sealed_candidate_token == 0)
    if not (
        valid_phase
        and scalar_fields_are_valid
        and observation_is_coherent
        and phase_is_coherent
        and token_is_coherent
    ):
        raise KnowledgeCancellationBridgeErrorV1(
            "Native cancellation snapshot fields are invalid"
        )
    return CancellationSnapshotV1(
        phase=phase,
        generation=generation,
        observed_monotonic_ns=observed_ns if latched == 1 else None,
        accepted_in_flight=accepted_in_flight,
        publication_ready=bool(publication_ready),
        sealed_candidate_token=sealed_candidate_token,
    )


class _NativeCancellationApiV1:
    def __init__(self) -> None:
        global _PINNED_NATIVE_DLL

        path = _verified_native_dll_path_v1()
        if _PINNED_NATIVE_DLL is None:
            try:
                _PINNED_NATIVE_DLL = ctypes.WinDLL(
                    str(path),
                    use_last_error=True,
                    winmode=0x00000100 | 0x00000800,
                )
            except OSError as error:
                raise KnowledgeCancellationBridgeErrorV1(
                    "Native cancellation DLL could not be loaded"
                ) from error
        dll = _PINNED_NATIVE_DLL
        self._arm = dll.gezhi_cancel_v1_arm
        self._arm.argtypes = []
        self._arm.restype = ctypes.c_int
        self._activate = dll.gezhi_cancel_v1_activate
        self._activate.argtypes = []
        self._activate.restype = ctypes.c_int
        self._try_begin_work = dll.gezhi_cancel_v1_try_begin_work
        self._try_begin_work.argtypes = []
        self._try_begin_work.restype = ctypes.c_int
        self._try_answer_id_cutover = dll.gezhi_cancel_v1_try_answer_id_cutover
        self._try_answer_id_cutover.argtypes = []
        self._try_answer_id_cutover.restype = ctypes.c_int
        self._snapshot = dll.gezhi_cancel_v1_snapshot
        self._snapshot.argtypes = [
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int64),
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_uint32),
        ]
        self._snapshot.restype = ctypes.c_int
        self._conditional_seal = dll.gezhi_cancel_v1_conditional_seal
        self._conditional_seal.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
        self._conditional_seal.restype = ctypes.c_int
        self._release = dll.gezhi_cancel_v1_release
        self._release.argtypes = []
        self._release.restype = ctypes.c_int

    def arm_v1(self) -> bool:
        return self._arm() == 1

    def activate_v1(self) -> bool:
        return self._activate() == 1

    def try_begin_work_v1(self) -> bool:
        return self._try_begin_work() == 1

    def try_answer_id_cutover_v1(self) -> bool:
        return self._try_answer_id_cutover() == 1

    def snapshot_v1(self) -> CancellationSnapshotV1:
        phase = ctypes.c_uint32()
        generation = ctypes.c_uint32()
        latched = ctypes.c_int()
        observed_ns = ctypes.c_int64()
        in_flight = ctypes.c_uint32()
        publication_ready = ctypes.c_int()
        sealed_token = ctypes.c_uint32()
        result = self._snapshot(
            ctypes.byref(phase),
            ctypes.byref(generation),
            ctypes.byref(latched),
            ctypes.byref(observed_ns),
            ctypes.byref(in_flight),
            ctypes.byref(publication_ready),
            ctypes.byref(sealed_token),
        )
        mapped_phase = _NATIVE_PHASES.get(int(phase.value))
        if result != 1 or mapped_phase is None:
            raise KnowledgeCancellationBridgeErrorV1(
                "Native cancellation snapshot is incoherent"
            )
        return _validated_native_snapshot_v1(
            phase=mapped_phase,
            generation=int(generation.value),
            latched=int(latched.value),
            observed_ns=int(observed_ns.value),
            accepted_in_flight=int(in_flight.value),
            publication_ready=int(publication_ready.value),
            sealed_candidate_token=int(sealed_token.value),
        )

    def conditional_seal_v1(
        self,
        *,
        expected_generation: int,
        candidate_token: int,
    ) -> bool:
        result = self._conditional_seal(expected_generation, candidate_token)
        if result not in {0, 1}:
            raise KnowledgeCancellationBridgeErrorV1(
                "Native cancellation seal proof failed"
            )
        return result == 1

    def release_v1(self) -> bool:
        return self._release() == 1


def _normalize_inherited_ctrl_c_ignore_v1() -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    set_console_ctrl_handler = kernel32.SetConsoleCtrlHandler
    set_console_ctrl_handler.argtypes = [ctypes.c_void_p, ctypes.c_int]
    set_console_ctrl_handler.restype = ctypes.c_int
    if not set_console_ctrl_handler(None, False):
        raise KnowledgeCancellationBridgeErrorV1(
            "Inherited Ctrl+C ignore normalization failed"
        )


class WindowsConsoleCancellationBridgeV1:
    def __init__(self, api: _NativeCancellationApiV1) -> None:
        self._api = api
        self._owner_thread = threading.get_ident()
        self._sealed_candidate_token = 0

    @classmethod
    def activate_v1(cls) -> WindowsConsoleCancellationBridgeV1:
        api = _NativeCancellationApiV1()
        bridge = cls(api)
        if not api.arm_v1():
            raise KnowledgeCancellationBridgeErrorV1(
                "Native cancellation registration failed"
            )
        _normalize_inherited_ctrl_c_ignore_v1()
        if not api.activate_v1():
            raise KnowledgeCancellationBridgeErrorV1(
                "Native cancellation activation failed"
            )
        snapshot = api.snapshot_v1()
        if snapshot != CancellationSnapshotV1(
            phase="accepting",
            generation=0,
            observed_monotonic_ns=None,
            accepted_in_flight=0,
            publication_ready=False,
            sealed_candidate_token=0,
        ):
            raise KnowledgeCancellationBridgeErrorV1(
                "Native cancellation activation proof differs"
            )
        return bridge

    def _require_owner_thread_v1(self) -> None:
        if threading.get_ident() != self._owner_thread:
            raise KnowledgeCancellationBridgeErrorV1(
                "Native cancellation API left its main thread"
            )

    def observed_at_monotonic_ns(self) -> int | None:
        self._require_owner_thread_v1()
        return self._api.snapshot_v1().observed_monotonic_ns

    def try_begin_work_v1(self) -> bool:
        self._require_owner_thread_v1()
        return self._api.try_begin_work_v1()

    def try_answer_id_cutover_v1(self) -> bool:
        self._require_owner_thread_v1()
        return self._api.try_answer_id_cutover_v1()

    def snapshot_v1(self) -> CancellationSnapshotV1:
        self._require_owner_thread_v1()
        return self._api.snapshot_v1()

    def conditional_seal_v1(
        self,
        *,
        expected_generation: int,
        candidate_token: int,
    ) -> bool:
        self._require_owner_thread_v1()
        if (
            type(expected_generation) is not int
            or not 0 <= expected_generation <= 0x0FFFFFFF
            or type(candidate_token) is not int
            or not 1 <= candidate_token <= _MAX_CANDIDATE_TOKEN
        ):
            raise ValueError("Native cancellation seal input is invalid")
        sealed = self._api.conditional_seal_v1(
            expected_generation=expected_generation,
            candidate_token=candidate_token,
        )
        if sealed:
            snapshot = self._api.snapshot_v1()
            if (
                snapshot.phase != "sealed"
                or snapshot.sealed_candidate_token != candidate_token
            ):
                raise KnowledgeCancellationBridgeErrorV1(
                    "Native cancellation sealed token differs"
                )
            self._sealed_candidate_token = candidate_token
        return sealed

    def release_v1(self) -> None:
        self._require_owner_thread_v1()
        if self._sealed_candidate_token == 0 or not self._api.release_v1():
            raise KnowledgeCancellationBridgeErrorV1(
                "Native cancellation matching removal failed"
            )
        snapshot = self._api.snapshot_v1()
        if (
            snapshot.phase != "released"
            or snapshot.accepted_in_flight != 0
            or snapshot.sealed_candidate_token != self._sealed_candidate_token
        ):
            raise KnowledgeCancellationBridgeErrorV1(
                "Native cancellation release proof differs"
            )


def _current_process_debugger_present_v1() -> bool:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    is_debugger_present = kernel32.IsDebuggerPresent
    is_debugger_present.argtypes = []
    is_debugger_present.restype = ctypes.c_int
    return bool(is_debugger_present())


def activate_knowledge_ask_cancellation_v1() -> KnowledgeCancellationBridgeV1:
    capability = _classify_console_cancellation_capability_v1(
        _WindowsConsoleCapabilityApiV1()
    )
    if capability == "capability_absent":
        return NoInteractiveCancellationBridgeV1.activate_v1(
            selection_reason="capability_absent"
        )
    if _current_process_debugger_present_v1():
        return NoInteractiveCancellationBridgeV1.activate_v1(
            selection_reason="debugger_present"
        )
    return WindowsConsoleCancellationBridgeV1.activate_v1()


__all__ = [
    "CancellationSnapshotV1",
    "KnowledgeCancellationBridgeErrorV1",
    "KnowledgeCancellationBridgeV1",
    "NoInteractiveCancellationBridgeV1",
    "WindowsConsoleCancellationBridgeV1",
    "activate_knowledge_ask_cancellation_v1",
]
