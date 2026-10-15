"""Spec comparison for RFQ lines.

A required spec is {"op": ">=" | "<=" | "==" | "in", "value": ...}. Spec keys carry
their unit (flash_mb, iout_ma, temp_max_c) so comparison is plain code, never
LLM interpretation. Missing data fails, it never silently passes.
"""
from typing import Any

OPS = (">=", "<=", "==", "in")


def check_spec(key: str, actual: dict[str, Any], required: dict[str, Any]) -> str | None:
    """Return a failure reason, or None if the requirement is met."""
    op, want = required.get("op"), required.get("value")
    if op not in OPS:
        return f"{key}: unknown comparison '{op}'"
    if key not in actual or actual[key] is None:
        return f"{key}: not specified by supplier (required {op} {want})"
    have = actual[key]
    try:
        if op == ">=":
            ok = have >= want
        elif op == "<=":
            ok = have <= want
        elif op == "==":
            ok = have == want
        else:
            ok = have in want
    except TypeError:
        return f"{key}: cannot compare {have!r} with {want!r}"
    return None if ok else f"{key}: offered {have}, required {op} {want}"


def check_specs(actual: dict[str, Any], required: dict[str, dict[str, Any]]) -> list[str]:
    return [r for k, req in required.items() if (r := check_spec(k, actual, req))]
