"""P4: QR format (strict parsing), rendering, and decoding from images."""

from __future__ import annotations

import uuid

import cv2
import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.core.crypto import b64u_encode
from app.core.qr import (
    PREFIX,
    QRFormatError,
    build_qr,
    decode_qr,
    new_rx_id,
    parse_qr,
    render_png,
)

RX = "3f0c1b2e-7d4a-4c1b-9e2f-0a1b2c3d4e5f"
KEY = "9a1c0e77b2d4f605"
HASH = "ab" * 32
SIG = bytes(range(64))
VALID = build_qr(RX, KEY, HASH, SIG)


def test_build_and_parse_round_trip():
    parsed = parse_qr(VALID)
    assert (parsed.rx_id, parsed.key_id, parsed.payload_hash, parsed.signature) == (
        RX,
        KEY,
        HASH,
        SIG,
    )
    assert parsed.signature_b64 == b64u_encode(SIG)


def test_format_and_length():
    assert VALID.startswith(PREFIX + ".")
    assert len(VALID) == 5 + 36 + 1 + 16 + 1 + 64 + 1 + 86  # 210 characters
    assert VALID.count(".") == 4


def test_generated_ids_are_valid_v4_and_parseable():
    for _ in range(20):
        rx = new_rx_id()
        assert uuid.UUID(rx).version == 4
        parse_qr(build_qr(rx, KEY, HASH, SIG))


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "hello",
        VALID.replace("PRM2", "PRM1", 1),
        VALID.replace("PRM2", "prm2", 1),
        VALID + ".extra",
        VALID.rsplit(".", 1)[0],  # missing signature
        " " + VALID,
        VALID + " ",
        VALID + "\n",
        VALID.replace(RX, RX.upper()),
        VALID.replace(RX, str(uuid.UUID(int=1, version=1))),  # not a v4 id
        VALID.replace(KEY, KEY.upper()),
        VALID.replace(KEY, KEY[:-1]),
        VALID.replace(HASH, HASH.upper()),
        VALID.replace(HASH, HASH[:-1]),
        VALID.replace(HASH, "g" + HASH[1:]),
        VALID[:-1],  # signature one char short
        VALID + "A",  # signature one char long
        VALID[:-1] + "=",  # padding is not allowed
        VALID[:-1] + "+",  # standard-base64 alphabet is not allowed
        VALID.replace(RX, "../../etc/passwd"),
        "x" * 301,
    ],
)
def test_malformed_codes_are_rejected(bad):
    with pytest.raises(QRFormatError):
        parse_qr(bad)


def test_non_string_input_is_rejected():
    for bad in (None, 123, b"PRM2.x", ["PRM2"]):
        with pytest.raises(QRFormatError):
            parse_qr(bad)  # type: ignore[arg-type]


def test_non_canonical_signature_encoding_is_rejected():
    # 86 base64url chars whose trailing bits are not zero decode to the same bytes as the canonical
    # form, which would give one signature two spellings. Only the canonical one is accepted.
    tampered = VALID[:-1] + ("B" if VALID[-1] != "B" else "C")
    if tampered != VALID:
        try:
            parse_qr(tampered)
        except QRFormatError:
            return
        # If it parsed, it must at least be a different signature (a normal flipped bit).
        assert parse_qr(tampered).signature != SIG


def test_build_refuses_bad_components():
    with pytest.raises(QRFormatError):
        build_qr("not-a-uuid", KEY, HASH, SIG)
    with pytest.raises(QRFormatError):
        build_qr(RX, KEY, HASH, SIG[:-1])


# --- fuzzing ---------------------------------------------------------------------------------


@given(st.text(max_size=400))
def test_parser_only_ever_raises_qr_format_error(text):
    try:
        parse_qr(text)
    except QRFormatError:
        pass


@given(
    st.uuids(version=4),
    st.binary(min_size=8, max_size=8).map(lambda b: b.hex()),
    st.binary(min_size=32, max_size=32).map(lambda b: b.hex()),
    st.binary(min_size=64, max_size=64),
)
def test_well_formed_codes_always_round_trip(rx, key_id, payload_hash, signature):
    parsed = parse_qr(build_qr(str(rx), key_id, payload_hash, signature))
    assert parsed.rx_id == str(rx) and parsed.signature == signature


@given(
    st.integers(min_value=0, max_value=len(VALID) - 1),
    st.characters(min_codepoint=33, max_codepoint=126),
)
def test_single_character_corruption_never_yields_the_original(index, ch):
    corrupted = VALID[:index] + ch + VALID[index + 1 :]
    if corrupted == VALID:
        return
    try:
        parsed = parse_qr(corrupted)
    except QRFormatError:
        return
    original = parse_qr(VALID)
    assert (parsed.rx_id, parsed.key_id, parsed.payload_hash, parsed.signature) != (
        original.rx_id,
        original.key_id,
        original.payload_hash,
        original.signature,
    )


# --- image round trips -----------------------------------------------------------------------


def _png_to_array(png: bytes) -> np.ndarray:
    return cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)


def test_rendered_qr_decodes_back_to_the_same_text():
    assert decode_qr(_png_to_array(render_png(VALID))) == VALID


def test_decode_survives_downscaling_and_jpeg_compression():
    image = _png_to_array(render_png(VALID, box_size=10))
    small = cv2.resize(image, None, fx=0.6, fy=0.6, interpolation=cv2.INTER_AREA)
    ok, jpeg = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 60])
    assert ok
    assert decode_qr(cv2.imdecode(jpeg, cv2.IMREAD_COLOR)) == VALID


def test_decode_finds_a_qr_inside_a_larger_page():
    qr = _png_to_array(render_png(VALID, box_size=6))
    page = np.full((1000, 900, 3), 255, np.uint8)
    h, w = qr.shape[:2]
    page[500 : 500 + h, 450 : 450 + w] = qr
    assert decode_qr(page) == VALID


def test_decode_returns_none_when_there_is_no_qr():
    assert decode_qr(np.full((300, 300, 3), 255, np.uint8)) is None
    assert decode_qr(np.random.default_rng(1).integers(0, 255, (300, 300), dtype=np.uint8)) is None
