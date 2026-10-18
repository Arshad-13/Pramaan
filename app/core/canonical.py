"""Canonical JSON and hashing (Spec Section 7.1).

Purpose: turn a payload dict into one exact byte string, so that signing and verifying
         always see identical input.
Inputs : dicts/lists of str, int, bool, None (floats are rejected on purpose).
Outputs: `canonical_bytes()` (UTF-8 JSON, sorted keys, no whitespace), `sha256_hex()`.

Security reasons for each rule:
- Sorted keys + compact separators: the same data always gives the same bytes.
- NFC normalisation: "e" + combining acute and the single character "é" look identical but
  are different bytes; normalising stops look-alike text from changing the signed bytes.
- Reject control and format characters (including bidi overrides such as U+202E and zero-width
  characters): they let text display differently from what was signed ("Trojan Source").
  Newlines are allowed only inside `notes`.
- Reject floats: float formatting is not stable across platforms. Doses are integer mg.
- Reject keys that collide after normalisation: otherwise one of two values silently wins.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any

# Keys whose string values may contain a newline (free text written by a doctor).
MULTILINE_KEYS = frozenset({"notes"})
# Unicode categories we never allow in signed text: Cc control, Cf format (bidi, zero-width),
# Cs surrogate, Co private use, Cn unassigned.
_FORBIDDEN_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn"})


class CanonicalError(ValueError):
    """The payload cannot be represented canonically (and must not be signed)."""


def _clean_string(value: str, *, allow_newline: bool) -> str:
    text = unicodedata.normalize("NFC", value)
    for ch in text:
        if ch == "\n" and allow_newline:
            continue
        if unicodedata.category(ch) in _FORBIDDEN_CATEGORIES:
            raise CanonicalError(f"forbidden character U+{ord(ch):04X} in text")
    return text


def normalise(obj: Any, *, _allow_newline: bool = False) -> Any:
    """Return a cleaned deep copy of `obj`, or raise CanonicalError."""
    if isinstance(obj, bool) or obj is None:
        return obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        raise CanonicalError("floats are not allowed in signed payloads")
    if isinstance(obj, str):
        return _clean_string(obj, allow_newline=_allow_newline)
    if isinstance(obj, list | tuple):
        return [normalise(item, _allow_newline=_allow_newline) for item in obj]
    if isinstance(obj, dict):
        cleaned: dict[str, Any] = {}
        for key, value in obj.items():
            if not isinstance(key, str):
                raise CanonicalError("object keys must be strings")
            clean_key = _clean_string(key, allow_newline=False)
            if clean_key in cleaned:
                raise CanonicalError("duplicate key after normalisation")
            cleaned[clean_key] = normalise(value, _allow_newline=clean_key in MULTILINE_KEYS)
        return cleaned
    raise CanonicalError(f"unsupported type: {type(obj).__name__}")


def canonical_bytes(obj: dict[str, Any]) -> bytes:
    """The exact bytes that get hashed and signed."""
    return json.dumps(
        normalise(obj),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    """Lowercase hex SHA-256."""
    return hashlib.sha256(data).hexdigest()
