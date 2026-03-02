# mostly copied from https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/tool/edit.ts
from __future__ import annotations

import re
from collections.abc import Callable, Generator

type Replacer = Callable[[str, str], Generator[str, None, None]]


def _levenshtein(a: str, b: str) -> int:
    m, n = len(a), len(b)
    dp = list(range(n + 1))
    for i in range(1, m + 1):
        prev = dp[0]
        dp[0] = i
        for j in range(1, n + 1):
            temp = dp[j]
            dp[j] = prev if a[i - 1] == b[j - 1] else 1 + min(prev, dp[j], dp[j - 1])
            prev = temp
    return dp[n]


def _simple_replacer(_content: str, search: str) -> Generator[str, None, None]:
    yield search


def _line_trimmed_replacer(content: str, search: str) -> Generator[str, None, None]:
    search_lines = search.splitlines()
    if not search_lines:
        return
    n = len(search_lines)
    stripped_search = [l.strip() for l in search_lines]
    content_lines = content.splitlines()
    for i in range(len(content_lines) - n + 1):
        window = content_lines[i : i + n]
        if [l.strip() for l in window] == stripped_search:
            yield "\n".join(window)


def _block_anchor_replacer(content: str, search: str) -> Generator[str, None, None]:
    search_lines = search.splitlines()
    if len(search_lines) < 3:
        return
    n = len(search_lines)
    first_s = search_lines[0].strip()
    last_s = search_lines[-1].strip()
    middle_s = "\n".join(search_lines[1:-1])
    content_lines = content.splitlines()
    candidates: list[tuple[int, float]] = []
    for i in range(len(content_lines) - n + 1):
        window = content_lines[i : i + n]
        if window[0].strip() == first_s and window[-1].strip() == last_s:
            middle_w = "\n".join(window[1:-1])
            dist = _levenshtein(middle_s, middle_w)
            max_len = max(len(middle_s), len(middle_w), 1)
            ratio = 1.0 - dist / max_len
            candidates.append((i, ratio))
    threshold = 0.0 if len(candidates) == 1 else 0.3
    for i, ratio in candidates:
        if ratio >= threshold:
            yield "\n".join(content_lines[i : i + n])


def _whitespace_normalized_replacer(
    content: str, search: str
) -> Generator[str, None, None]:
    search_lines = search.splitlines()
    if not search_lines:
        return
    n = len(search_lines)
    normalized_search = re.sub(r"\s+", " ", search).strip()
    content_lines = content.splitlines()
    for i in range(len(content_lines) - n + 1):
        window = content_lines[i : i + n]
        window_text = "\n".join(window)
        if re.sub(r"\s+", " ", window_text).strip() == normalized_search:
            yield window_text


def _indentation_flexible_replacer(
    content: str, search: str
) -> Generator[str, None, None]:
    search_lines = search.splitlines()
    if not search_lines:
        return
    n = len(search_lines)

    def strip_min_indent(lines: list[str]) -> list[str]:
        non_empty = [l for l in lines if l.strip()]
        if not non_empty:
            return lines
        min_indent = min(len(l) - len(l.lstrip()) for l in non_empty)
        return [l[min_indent:] if l.strip() else l for l in lines]

    stripped_search = strip_min_indent(search_lines)
    content_lines = content.splitlines()
    for i in range(len(content_lines) - n + 1):
        window = content_lines[i : i + n]
        if strip_min_indent(window) == stripped_search:
            yield "\n".join(window)


def replace(content: str, search: str, replacement: str) -> str | None:
    for replacer in [
        _simple_replacer,
        _line_trimmed_replacer,
        _block_anchor_replacer,
        _whitespace_normalized_replacer,
        _indentation_flexible_replacer,
    ]:
        for candidate in replacer(content, search):
            idx = content.find(candidate)
            if idx == -1:
                continue
            if content.find(candidate, idx + 1) != -1:
                continue  # ambiguous, skip
            if replacement and not replacement.endswith("\n"):
                replacement += "\n"
            return content[:idx] + replacement + content[idx + len(candidate) :]
    return None
