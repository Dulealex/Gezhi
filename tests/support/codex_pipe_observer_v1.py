from __future__ import annotations

import ctypes


def measure_same_pipe_capacities_v1(
    stdin_read_handle: int,
    stdout_read_handle: int,
) -> tuple[int, int]:
    """Measure the two exact anonymous pipes supplied by the test seam."""

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_named_pipe_info = kernel32.GetNamedPipeInfo
    get_named_pipe_info.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.c_ulong),
    ]
    get_named_pipe_info.restype = ctypes.c_int
    capacities: list[int] = []
    for handle in (stdin_read_handle, stdout_read_handle):
        flags = ctypes.c_ulong()
        inbound = ctypes.c_ulong()
        if not get_named_pipe_info(
            handle,
            ctypes.byref(flags),
            None,
            ctypes.byref(inbound),
            None,
        ):
            raise OSError(
                ctypes.get_last_error(),
                "GetNamedPipeInfo(test observer) failed",
            )
        if flags.value not in {0, 1} or inbound.value <= 0:
            raise AssertionError("test observer did not measure a byte pipe")
        capacities.append(int(inbound.value))
    return capacities[0], capacities[1]
