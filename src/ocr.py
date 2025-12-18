"""OCR utilities for extracting overlay text from Snapchat media overlays.

Uses EasyOCR with GPU acceleration when available.
"""

import io
import importlib
from functools import lru_cache
from typing import Optional

import numpy as np
from PIL import Image, ImageOps
import easyocr


@lru_cache(maxsize=1)
def _get_easyocr_reader():
    """Return a cached EasyOCR Reader, using GPU if CUDA is available.

    On Apple MPS, fall back to CPU to avoid pin_memory warnings.
    """
    use_gpu = False
    try:
        torch = importlib.import_module("torch")
        if getattr(torch, "cuda", None) and torch.cuda.is_available():
            use_gpu = True
        elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            use_gpu = False
    except Exception:
        use_gpu = False
    return easyocr.Reader(["en"], gpu=use_gpu)


def extract_overlay_text_easy(overlay_bytes: bytes) -> Optional[str]:
    """Run OCR using EasyOCR on overlay image bytes (WebP/PNG).

    Light preprocessing: grayscale + autocontrast.
    Returns cleaned text or None if OCR fails or finds nothing.
    """
    try:
        img = Image.open(io.BytesIO(overlay_bytes))
        gray = ImageOps.autocontrast(img.convert("L"))
        reader = _get_easyocr_reader()
        arr = np.array(gray)
        results = reader.readtext(arr, detail=0)
        cleaned = "\n".join(line.strip() for line in results if str(line).strip())
        return cleaned or None
    except Exception:
        return None
