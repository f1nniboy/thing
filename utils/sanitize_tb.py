from __future__ import annotations

import re
from pathlib import Path

from utils.paths import PROJECT_ROOT

_MAX_TB = 3900


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
    if len(result) > _MAX_TB:
        result = "[... truncated]\n" + result[-_MAX_TB:]
    return result
