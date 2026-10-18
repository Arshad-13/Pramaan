"""P1: canonical JSON + SHA-256."""

from __future__ import annotations

import json

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.core.canonical import CanonicalError, canonical_bytes, normalise, sha256_hex

SAMPLE = {
    "version": 2,
    "rx_id": "3f0c1b2e-0000-4000-8000-000000000001",
    "medicines": [{"name": "Amoxicillin", "dose_mg": 500, "frequency": "TDS", "duration_days": 5}],
    "notes": "After food",
}


def test_output_is_compact_sorted_utf8():
    out = canonical_bytes({"b": 1, "a": [True, None, "x"]})
    assert out == b'{"a":[true,null,"x"],"b":1}'


def test_key_order_does_not_change_bytes():
    reordered = dict(reversed(list(SAMPLE.items())))
    assert canonical_bytes(SAMPLE) == canonical_bytes(reordered)


def test_non_ascii_is_kept_as_utf8_not_escaped():
    assert canonical_bytes({"n": "Ravi P\u00e2tel"}) == '{"n":"Ravi P\u00e2tel"}'.encode()


def test_nfc_normalisation_makes_lookalikes_identical():
    composed = {"name": "caf\u00e9"}  # single code point
    decomposed = {"name": "cafe\u0301"}  # e + combining acute accent
    assert canonical_bytes(composed) == canonical_bytes(decomposed)


def test_sha256_known_vector():
    assert sha256_hex(b"abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


@pytest.mark.parametrize(
    "bad",
    [
        "evil\u202etxt",  # bidi right-to-left override
        "zero\u200bwidth",  # zero-width space
        "tab\there",
        "nul\x00byte",
        "carriage\rreturn",
        "line\nbreak",  # newline outside notes
        "\ud800",  # lone surrogate
        "private\ue000use",
    ],
)
def test_forbidden_characters_are_rejected(bad):
    with pytest.raises(CanonicalError):
        canonical_bytes({"name": bad})


def test_newline_allowed_only_in_notes():
    assert canonical_bytes({"notes": "a\nb"}) == b'{"notes":"a\\nb"}'
    with pytest.raises(CanonicalError):
        canonical_bytes({"medicines": [{"name": "a\nb"}]})


def test_control_characters_rejected_even_in_notes():
    with pytest.raises(CanonicalError):
        canonical_bytes({"notes": "a\tb"})


@pytest.mark.parametrize("bad", [1.5, float("nan"), float("inf")])
def test_floats_are_rejected(bad):
    with pytest.raises(CanonicalError):
        canonical_bytes({"dose": bad})


def test_non_string_keys_rejected():
    with pytest.raises(CanonicalError):
        canonical_bytes({1: "x"})


def test_keys_colliding_after_normalisation_are_rejected():
    with pytest.raises(CanonicalError):
        canonical_bytes({"caf\u00e9": 1, "cafe\u0301": 2})


def test_unsupported_types_rejected():
    with pytest.raises(CanonicalError):
        canonical_bytes({"x": object()})
    with pytest.raises(CanonicalError):
        canonical_bytes({"x": b"bytes"})


def test_normalise_does_not_mutate_input():
    original = {"name": "cafe\u0301", "list": ["a"]}
    snapshot = json.dumps(original)
    normalise(original)
    assert json.dumps(original) == snapshot


# --- property tests ------------------------------------------------------------------------

_text = st.text(
    alphabet=st.characters(
        blacklist_categories=("Cc", "Cf", "Cs", "Co", "Cn"), blacklist_characters="\n"
    ),
    max_size=20,
)
_json_value = st.recursive(
    st.none() | st.booleans() | st.integers(-(2**53), 2**53) | _text,
    lambda children: st.lists(children, max_size=4) | st.dictionaries(_text, children, max_size=4),
    max_leaves=12,
)


@given(st.dictionaries(_text, _json_value, max_size=6))
def test_canonical_is_stable_under_reordering_and_roundtrips(obj):
    try:
        first = canonical_bytes(obj)
    except CanonicalError:
        return  # e.g. keys that collide after NFC: correctly refused
    shuffled = dict(reversed(list(obj.items())))
    assert canonical_bytes(shuffled) == first
    # Re-canonicalising the parsed output is a fixed point.
    assert canonical_bytes(json.loads(first)) == first
    assert json.loads(first) == normalise(obj)
