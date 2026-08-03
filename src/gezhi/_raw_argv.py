from __future__ import annotations

from enum import Enum, auto


class RawArgvPreflightVerdictV1(Enum):
    PASS = auto()
    RESOURCE_LIMIT_EXCEEDED = auto()


class RawArgvPreflightV1:
    MAX_ARGUMENT_COUNT = 128
    MAX_ARGUMENT_SIZE = 8192
    MAX_TOTAL_SIZE = 16384

    @classmethod
    def evaluate(cls, argv_snapshot: tuple[str, ...]) -> RawArgvPreflightVerdictV1:
        if type(argv_snapshot) is not tuple:
            raise TypeError("argv snapshot must be a tuple")
        if not argv_snapshot:
            raise ValueError("argv snapshot must contain argv0")
        for argument in argv_snapshot:
            if not isinstance(argument, str):
                raise TypeError("argv snapshot items must be strings")

        if len(argv_snapshot) - 1 > cls.MAX_ARGUMENT_COUNT:
            return RawArgvPreflightVerdictV1.RESOURCE_LIMIT_EXCEEDED

        total_size = 0
        for index in range(1, len(argv_snapshot)):
            argument_size = len(argv_snapshot[index])
            if argument_size > cls.MAX_ARGUMENT_SIZE:
                return RawArgvPreflightVerdictV1.RESOURCE_LIMIT_EXCEEDED
            total_size += argument_size
            if total_size > cls.MAX_TOTAL_SIZE:
                return RawArgvPreflightVerdictV1.RESOURCE_LIMIT_EXCEEDED

        return RawArgvPreflightVerdictV1.PASS
