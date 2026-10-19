"""OCR behind a small interface (Spec 11.1).

Purpose: read text from a straightened page. OCR is the *second opinion* in upload verification:
         the image comparison decides "does this look like what was signed?", and OCR says what
         a differing field actually reads so the pharmacist sees "Signed 500 mg / Document reads
         800 mg". Nothing here is used to trust a document.
Engine : RapidOCR (ONNX). Its models ship inside the pip package, so there is no download at run
         time. Other engines can be added behind the same `OCREngine` protocol.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

import numpy as np


@dataclass(frozen=True)
class OCRLine:
    text: str
    confidence: float
    box: tuple[tuple[float, float], ...]  # four corner points, in image pixels

    @property
    def centre(self) -> tuple[float, float]:
        xs = [p[0] for p in self.box]
        ys = [p[1] for p in self.box]
        return sum(xs) / len(xs), sum(ys) / len(ys)

    @property
    def height(self) -> float:
        ys = [p[1] for p in self.box]
        return max(ys) - min(ys)


class OCREngine(Protocol):
    def read(self, image: np.ndarray) -> list[OCRLine]: ...


class RapidOCREngine:
    """Lazy-loading RapidOCR wrapper. The model session is created once and guarded by a lock."""

    def __init__(self) -> None:
        self._engine = None
        self._lock = threading.Lock()

    def read(self, image: np.ndarray) -> list[OCRLine]:
        with self._lock:
            if self._engine is None:
                from rapidocr_onnxruntime import RapidOCR

                self._engine = RapidOCR()
            result, _elapsed = self._engine(image)
        lines: list[OCRLine] = []
        for box, text, confidence in result or []:
            lines.append(
                OCRLine(
                    text=str(text),
                    confidence=float(confidence),
                    box=tuple((float(x), float(y)) for x, y in box),
                )
            )
        return lines


@lru_cache
def get_engine() -> OCREngine:
    return RapidOCREngine()
