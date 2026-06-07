# agent/core/constants.py
from enum import StrEnum


class SecurityLevel(StrEnum):
    SAFE = "safe"
    MODERATE = "moderate"
    DANGEROUS = "dangerous"
    BLOCKED = "blocked"


class StopReason(StrEnum):
    STOP = "stop"
    TOOL_USE = "tool_calls"
    MAX_TOKENS = "length"
    MAX_ITER = "max_iter"
    ERROR = "error"


class SkillStatus(StrEnum):
    MATCHED = "matched"
    NO_MATCH = "no_match"
    DISABLED = "disabled"