from __future__ import annotations

import re
from pathlib import Path

from config import TRACEBACK_MAX_LEN

PROJECT_ROOT = Path(__file__).parent.parent


def sanitize_tb(text: str) -> str:
    """Sanitize a traceback for display: shorten paths, truncate if too long."""

    def shorten(m: re.Match[str]) -> str:
        raw = m.group(1)
        if not Path(raw).is_absolute():
            return m.group(0)
        try:
            rel = Path(raw).relative_to(PROJECT_ROOT)
            return f'File "{rel}"'
        except ValueError:
            parts = Path(raw).parts
            return f'File "<...>/{"/".join(parts[-2:])}"'

    result = re.sub(r'File "([^"]+)"', shorten, text).strip()
    if len(result) > TRACEBACK_MAX_LEN:
        result = "[... truncated]\n" + result[-TRACEBACK_MAX_LEN:]
    return result


def clean_for_display(text: str, max_len: int = 120) -> str:
    """Strip formatting, collapse whitespace, and truncate for display."""
    text = " ".join(text.replace("`", "").replace("*", "").split())
    return text if len(text) <= max_len else text[:max_len].rstrip() + "…"
