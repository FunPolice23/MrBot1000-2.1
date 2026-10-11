"""Shared text and serialization helpers without package side effects."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import List


def truncate(text: str, max_chars: int, ellipsis: str = "…") -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars - len(ellipsis)] + ellipsis


def fingerprint(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()[:8]


def ts_now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def extract_code_blocks(text: str) -> List[str]:
    return re.findall(r"```(?:\w+)?\n(.*?)```", text, re.DOTALL)


def strip_code_fences(text: str) -> str:
    return re.sub(r"```(?:\w+)?\n?", "", text).strip()


def safe_json_loads(text: str, default=None):
    try:
        return json.loads(strip_code_fences(text))
    except Exception:
        return default


__all__ = [
    "extract_code_blocks",
    "fingerprint",
    "safe_json_loads",
    "strip_code_fences",
    "truncate",
    "ts_now",
    "word_count",
]
