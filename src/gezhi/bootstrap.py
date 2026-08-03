from __future__ import annotations

import msvcrt
import os
import sys

from gezhi._raw_argv import RawArgvPreflightV1, RawArgvPreflightVerdictV1

_RESOURCE_LIMIT_STDERR = b"gezhi: error: command-line input exceeds safety limits\r\n"


def _present_resource_limit_exceeded() -> None:
    try:
        msvcrt.setmode(2, os.O_BINARY)
    except OSError:
        return

    payload = memoryview(_RESOURCE_LIMIT_STDERR)
    offset = 0
    while offset < len(payload):
        requested = len(payload) - offset
        try:
            count = os.write(2, payload[offset:])
        except OSError:
            return
        if type(count) is not int or not 1 <= count <= requested:
            return
        offset += count


def main() -> int:
    argv_snapshot = tuple(sys.argv)
    verdict = RawArgvPreflightV1.evaluate(argv_snapshot)
    if verdict is RawArgvPreflightVerdictV1.RESOURCE_LIMIT_EXCEEDED:
        _present_resource_limit_exceeded()
        return 2

    from gezhi._cli import run_cli

    return run_cli(argv_snapshot[1:])
