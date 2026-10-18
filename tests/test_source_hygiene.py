"""Source hygiene: no invisible or bidirectional-control characters in our code.

These characters (Unicode categories Cf/Cc, e.g. U+202E right-to-left override, U+200B
zero-width space) can make code read differently from how it runs ("Trojan Source").
The canonicaliser rejects them in signed data; this test keeps them out of the codebase too.
Tests that need such characters must spell them as visible escapes.
"""

from __future__ import annotations

import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWED_CONTROL = {"\n", "\r", "\t"}


def _python_and_script_files():
    for folder in ("app", "tests", "scripts"):
        yield from (ROOT / folder).rglob("*.py")


def test_no_invisible_or_control_characters_in_source():
    offenders = []
    for path in _python_and_script_files():
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for ch in line:
                if ch in ALLOWED_CONTROL:
                    continue
                if unicodedata.category(ch) in {"Cc", "Cf"}:
                    offenders.append(f"{path.relative_to(ROOT)}:{lineno} U+{ord(ch):04X}")
    assert not offenders, "invisible characters found:\n" + "\n".join(offenders)
