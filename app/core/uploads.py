"""Safe handling of uploaded prescription images and PDFs (Spec Section 7.5).

Purpose: decide what an upload really is (by its first bytes, never its name), refuse anything
         oversized or odd, and turn it into one image the verifier can work with.
Limits : 5 MB, at most 40 megapixels, PDFs of at most 3 pages with no attachments and no
         password. Nothing in the file is executed; PDFs are only rendered.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Literal

import cv2
import numpy as np
import pymupdf
from PIL import Image, UnidentifiedImageError

MAX_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 40_000_000
MAX_PDF_PAGES = 3
PDF_DPI = 200

Kind = Literal["pdf", "png", "jpeg", "webp"]


class UploadError(ValueError):
    """The upload is not acceptable. `status` is the HTTP code to answer with."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class LoadedUpload:
    kind: Kind
    image: np.ndarray  # BGR raster of the (first) page
    has_text_layer: bool = False
    pdf_page: pymupdf.Page | None = None


def sniff(data: bytes) -> Kind:
    """Identify the file type from its magic bytes."""
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    raise UploadError("Upload a photo (JPEG, PNG) or a PDF of the prescription.", 400)


def _check_image_size(data: bytes) -> None:
    try:
        with Image.open(io.BytesIO(data)) as img:
            width, height = img.size
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise UploadError("That image could not be read.") from exc
    if width < 200 or height < 200:
        raise UploadError("The image is too small to read.")
    if width * height > MAX_PIXELS:
        raise UploadError("The image is too large. Use a photo under 40 megapixels.")


def load_upload(data: bytes) -> LoadedUpload:
    if not data:
        raise UploadError("The file is empty.")
    if len(data) > MAX_BYTES:
        raise UploadError("The file is larger than 5 MB.", 413)
    kind = sniff(data)

    if kind == "pdf":
        try:
            doc = pymupdf.open(stream=data, filetype="pdf")
        except Exception as exc:  # noqa: BLE001 - any parser failure means "not a usable PDF"
            raise UploadError("That PDF could not be read.") from exc
        if doc.needs_pass or doc.is_encrypted:
            raise UploadError("Password-protected PDFs are not accepted.")
        if doc.page_count < 1 or doc.page_count > MAX_PDF_PAGES:
            raise UploadError(f"The PDF must have between 1 and {MAX_PDF_PAGES} pages.")
        if doc.embfile_count() > 0:
            raise UploadError("PDFs with attached files are not accepted.")
        page = doc[0]
        rect = page.rect
        if not (100 <= rect.width <= 2000 and 100 <= rect.height <= 2000):
            raise UploadError("The PDF page size is not supported.")
        zoom = PDF_DPI / 72.0
        pix = page.get_pixmap(
            matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csRGB, alpha=False
        )
        if pix.width * pix.height > MAX_PIXELS:
            raise UploadError("The PDF page is too large.")
        arr = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3)
        image = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        has_text = bool(page.get_text("words"))
        return LoadedUpload(kind="pdf", image=image, has_text_layer=has_text, pdf_page=page)

    _check_image_size(data)
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise UploadError("That image could not be read.")
    return LoadedUpload(kind=kind, image=image)
