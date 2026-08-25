"""Normalization helpers."""
from __future__ import annotations
import re
import unicodedata

def _normalize(s: str) -> str:
    """Strip accents/diacritics, lowercase, remove spaces/hyphens/underscores."""
    if not isinstance(s, str):
        s = str(s) if s is not None else ""
    norm = unicodedata.normalize("NFD", s)
    norm = "".join(c for c in norm if unicodedata.category(c) != "Mn")
    norm = norm.lower()
    norm = re.sub(r"[\s\-_]+", "", norm)
    return norm
