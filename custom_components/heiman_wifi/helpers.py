"""Small normalization helpers shared by config flow and entity model."""

from __future__ import annotations

from typing import Any


def normalize_identifier(value: Any) -> str:
    raw = str(value or "").strip().lower()
    chars = [ch if ch.isalnum() else "_" for ch in raw]
    normalized = "_".join(part for part in "".join(chars).split("_") if part)
    return normalized or "device"


def normalize_mac(value: Any) -> str | None:
    raw = str(value or "").strip().lower()
    compact = "".join(ch for ch in raw if ch.isalnum())
    if len(compact) >= 12 and all(ch in "0123456789abcdef" for ch in compact[:12]):
        return compact[:12]
    return None


def info_value(info: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = info.get(key)
        if value not in (None, ""):
            return value
    return None
