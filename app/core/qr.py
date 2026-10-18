"""Prescription QR code: build, strictly parse, and decode from images (Spec Section 10.1).

Format : PRM2.<rx_id>.<key_id>.<payload_hash_hex>.<signature_b64url>      (about 210 characters)
Purpose: the QR carries only identifiers plus the hash and signature, not the prescription. A
         verifier looks the prescription up on the server, so the QR on its own never reveals
         medical details if it is photographed.
Parsing: deliberately strict. Anything that is not exactly this shape is rejected before any
         database lookup happens (no surprises from odd whitespace, case, or extra parts).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

import numpy as np

from app.core.crypto import SIGNATURE_LEN, b64u_decode, b64u_encode

PREFIX = "PRM2"

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
_KEY_ID_RE = re.compile(r"^[0-9a-f]{16}$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_SIG_RE = re.compile(r"^[A-Za-z0-9_-]{86}$")


class QRFormatError(ValueError):
    """The text is not a well-formed Pramaan prescription code."""


@dataclass(frozen=True)
class ParsedQR:
    rx_id: str
    key_id: str
    payload_hash: str
    signature: bytes  # 64 raw bytes

    @property
    def signature_b64(self) -> str:
        return b64u_encode(self.signature)


def build_qr(rx_id: str, key_id: str, payload_hash: str, signature: bytes) -> str:
    """Assemble the QR text. Inputs are validated so a malformed code can never be issued."""
    text = ".".join([PREFIX, rx_id, key_id, payload_hash, b64u_encode(signature)])
    parse_qr(text)  # round-trip check: what we issue must parse
    return text


def parse_qr(text: str) -> ParsedQR:
    if not isinstance(text, str) or len(text) > 300:
        raise QRFormatError("not a Pramaan code")
    parts = text.split(".")
    if len(parts) != 5 or parts[0] != PREFIX:
        raise QRFormatError("not a Pramaan code")
    _, rx_id, key_id, payload_hash, sig_b64 = parts
    if not _UUID_RE.match(rx_id):
        raise QRFormatError("bad prescription id")
    if not _KEY_ID_RE.match(key_id):
        raise QRFormatError("bad key id")
    if not _HASH_RE.match(payload_hash):
        raise QRFormatError("bad hash")
    if not _SIG_RE.match(sig_b64):
        raise QRFormatError("bad signature")
    try:
        signature = b64u_decode(sig_b64)
    except ValueError as exc:
        raise QRFormatError("bad signature") from exc
    if len(signature) != SIGNATURE_LEN:
        raise QRFormatError("bad signature")
    return ParsedQR(rx_id=rx_id, key_id=key_id, payload_hash=payload_hash, signature=signature)


def new_rx_id() -> str:
    return str(uuid.uuid4())


# --- rendering -------------------------------------------------------------------------------


def qr_matrix(text: str) -> list[list[bool]]:
    """Module matrix (True = dark) at error-correction level M, with no quiet zone."""
    import qrcode
    from qrcode.constants import ERROR_CORRECT_M

    code = qrcode.QRCode(error_correction=ERROR_CORRECT_M, border=0)
    code.add_data(text)
    code.make(fit=True)
    return code.get_matrix()


def render_png(text: str, box_size: int = 8, border: int = 4) -> bytes:
    """A PNG of the QR (used for tests and previews; the PDF draws the matrix as vectors)."""
    import io

    import qrcode
    from qrcode.constants import ERROR_CORRECT_M

    code = qrcode.QRCode(error_correction=ERROR_CORRECT_M, box_size=box_size, border=border)
    code.add_data(text)
    code.make(fit=True)
    buffer = io.BytesIO()
    code.make_image(fill_color="black", back_color="white").save(buffer, format="PNG")
    return buffer.getvalue()


# --- decoding --------------------------------------------------------------------------------


def decode_qr(image: np.ndarray) -> str | None:
    """Find and decode a QR code in an image (BGR/gray array). Returns the text or None.

    Tries OpenCV's ArUco-based detector first (more robust), then the classic detector, on the
    original, an upscaled copy and a thresholded copy, so slightly blurry photos still work."""
    import cv2

    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    candidates = [gray]
    candidates.append(cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC))
    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    candidates.append(otsu)

    detectors = []
    if hasattr(cv2, "QRCodeDetectorAruco"):
        detectors.append(cv2.QRCodeDetectorAruco())
    detectors.append(cv2.QRCodeDetector())

    for candidate in candidates:
        for detector in detectors:
            try:
                text, _points, _ = detector.detectAndDecode(candidate)
            except cv2.error:
                continue
            if text:
                return text
    return None
