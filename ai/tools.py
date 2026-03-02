from __future__ import annotations

import re
from typing import Any, ClassVar, final, override
from urllib.parse import urlparse

import aiohttp

from ai.types import AgentState
from config import FETCH_MAX_CHARS, OLLAMA_API_KEY
from utils.replace import replace


class Tool:
    name: ClassVar[str]
    description: ClassVar[str]
    params: ClassVar[dict[str, str]] = {}

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        k: {"type": "string", "description": v}
                        for k, v in self.params.items()
                    },
                    "required": list(self.params.keys()),
                },
            },
        }

    async def execute(self, _args: dict[str, Any], _state: AgentState) -> str:
        raise NotImplementedError

    def format_progress(
        self, _args: dict[str, Any], _result: str, _state: AgentState
    ) -> str | None:
        return f"⚙️ `{self.name}`"


@final
class WriteFileTool(Tool):
    name: ClassVar[str] = "write_file"
    description: ClassVar[str] = (
        "Write the full file content. Use for the initial draft or a complete rewrite."
    )
    params: ClassVar[dict[str, str]] = {
        "content": "Complete Python source code for the Thing."
    }

    @override
    async def execute(self, args: dict[str, Any], state: AgentState) -> str:
        state.content = args["content"]
        state.deploy = None
        return "file written"

    @override
    def format_progress(
        self, args: dict[str, Any], result: str, state: AgentState
    ) -> str | None:
        lines = args.get("content", "").count("\n") + 1
        return f"⚙️ `write_file` ({lines} lines)"


@final
class PatchFileTool(Tool):
    name: ClassVar[str] = "patch_file"
    description: ClassVar[str] = (
        "Replace an exact block of lines in the current file. "
        "If it fails, use read_file to check the current content and fix your search block."
    )
    params: ClassVar[dict[str, str]] = {
        "search": "Exact lines to find.",
        "replace": "Lines to replace the matched block with.",
    }

    @override
    async def execute(self, args: dict[str, Any], state: AgentState) -> str:
        if state.content is None:
            return "error: no file written yet - call write_file first"
        search = args.get("search", "")
        replace_text = args.get("replace", "")
        result = replace(state.content, search, replace_text)
        if result is not None:
            state.content = result
            state.deploy = None
            return "patch applied"
        return "patch failed: search block not found. Use read_file to check the current content."


@final
class ReadFileTool(Tool):
    name: ClassVar[str] = "read_file"
    description: ClassVar[str] = (
        "Read the current file content back. Review every line, decorators, class name, imports, method signatures."
    )
    params: ClassVar[dict[str, str]] = {}

    @override
    async def execute(self, args: dict[str, Any], state: AgentState) -> str:
        if state.content is None:
            return "no file written yet"
        return f"```python\n{state.content}\n```"


@final
class FetchTool(Tool):
    name: ClassVar[str] = "fetch"
    description: ClassVar[str] = (
        "Fetch a URL and return its raw text. Use to read raw GitHub or plain text files."
    )
    params: ClassVar[dict[str, str]] = {"url": "The URL to fetch."}

    _HEADERS = {
        # https://www.useragents.me
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.3"
    }

    @override
    async def execute(self, args: dict[str, Any], state: AgentState) -> str:
        url = args.get("url", "").strip()
        if not url:
            return "error: url is required"
        try:
            async with aiohttp.ClientSession(headers=self._HEADERS) as session:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    raw = await resp.read()
                    text = raw[: FETCH_MAX_CHARS + 1].decode("utf-8", errors="replace")
                    if len(text) > FETCH_MAX_CHARS:
                        return (
                            text[:FETCH_MAX_CHARS]
                            + f"\n\n[truncated at {FETCH_MAX_CHARS} chars]"
                        )
                    return text
        except Exception as e:
            return f"error fetching {url}: {e}"

    @override
    def format_progress(
        self, args: dict[str, Any], result: str, state: AgentState
    ) -> str | None:
        url = args.get("url", "")
        domain = urlparse(url).netloc or url
        return f"🌐 `fetch` ([{domain}]({url}))"


@final
class GrepTool(Tool):
    name: ClassVar[str] = "grep"
    description: ClassVar[str] = (
        "Search the current file content with a regex pattern. "
        "Returns matching lines with line numbers and surrounding context. "
        "Useful for locating methods, variables, or any text before calling patch_file."
    )
    params: ClassVar[dict[str, str]] = {
        "pattern": "Python regex pattern to search for.",
        "context": "Number of lines of context to show before and after each match (default 3).",
    }

    @override
    async def execute(self, args: dict[str, Any], state: AgentState) -> str:
        if state.content is None:
            return "error: no file written yet"
        pattern = args.get("pattern", "")
        if not pattern:
            return "error: pattern is required"
        try:
            ctx = int(args.get("context") or 3)
        except ValueError:
            ctx = 3
        try:
            rx = re.compile(pattern)
        except re.error as e:
            return f"error: invalid regex: {e}"
        lines = state.content.splitlines()
        match_indices = {i for i, line in enumerate(lines) if rx.search(line)}
        if not match_indices:
            return "no matches"

        # Build contiguous groups of lines to show
        shown: set[int] = set()
        for mi in match_indices:
            for j in range(max(0, mi - ctx), min(len(lines), mi + ctx + 1)):
                shown.add(j)

        output: list[str] = []
        prev: int | None = None
        for i in sorted(shown):
            if prev is not None and i > prev + 1:
                output.append("---")
            marker = ">" if i in match_indices else " "
            output.append(f"{marker}{i + 1}: {lines[i]}")
            prev = i
        return "\n".join(output)


@final
class WebSearchTool(Tool):
    name: ClassVar[str] = "web_search"
    description: ClassVar[str] = "Search the web using a search engine."
    params: ClassVar[dict[str, str]] = {
        "query": "The search query.",
        "max_results": "Maximum number of results to return (1-10, default 5).",
    }

    @override
    async def execute(self, args: dict[str, Any], state: AgentState) -> str:
        query = args.get("query", "").strip()
        if not query:
            return "error: query is required"
        try:
            max_results = max(1, min(10, int(args.get("max_results") or 5)))
        except ValueError:
            max_results = 5
        try:
            results = await state.api.web_search(query, max_results)
            lines = []
            for r in results:
                lines.append(f"title: {r.title}\nurl: {r.url}\n{r.content}")
            return "\n\n".join(lines) or "no results"
        except Exception as e:
            return f"error: {e}"

    @override
    def format_progress(
        self, args: dict[str, Any], result: str, state: AgentState
    ) -> str | None:
        return f"🔍 `web_search` {args.get('query', '')!r}"


@final
class WebFetchTool(Tool):
    name: ClassVar[str] = "web_fetch"
    description: ClassVar[str] = (
        "Fetch the formatted content of a webpage. Use for generic HTML web pages."
    )
    params: ClassVar[dict[str, str]] = {"url": "The URL to fetch."}

    @override
    async def execute(self, args: dict[str, Any], state: AgentState) -> str:
        url = args.get("url", "").strip()
        if not url:
            return "error: url is required"
        try:
            result = await state.api.web_fetch(url)
            parts = []
            if result.title:
                parts.append(f"title: {result.title}")
            if result.content:
                parts.append(result.content)
            if result.links:
                parts.append("links:\n" + "\n".join(result.links))
            return "\n\n".join(parts) or "no content"
        except Exception as e:
            return f"error: {e}"

    @override
    def format_progress(
        self, args: dict[str, Any], result: str, state: AgentState
    ) -> str | None:
        url = args.get("url", "")
        domain = urlparse(url).netloc or url
        return f"🌐 `web_fetch` ([{domain}]({url}))"


@final
class DeployTool(Tool):
    name: ClassVar[str] = "deploy"
    description: ClassVar[str] = (
        "Attempt to load the current file as a Thing. "
        "On success, immediately call done(summary='...'). "
        "On failure, read the exact error and traceback, fix the issue, and deploy again."
    )
    params: ClassVar[dict[str, str]] = {}

    @override
    async def execute(self, args: dict[str, Any], state: AgentState) -> str:
        if state.content is None:
            return "error: no file written yet - call write_file first"
        result = await state.deploy_cb(state.content)
        if result.name:
            state.deploy = result
            return f"deployed successfully as '{result.name}'"
        state.deploy = None
        return result.error or "deploy failed"

    @override
    def format_progress(
        self, args: dict[str, Any], result: str, state: AgentState
    ) -> str | None:
        if state.deploy:
            return f"✅ `{state.deploy.name}`"
        return "❌ deploy failed"


@final
class DoneTool(Tool):
    name: ClassVar[str] = "done"
    description: ClassVar[str] = (
        "Signal completion. MUST be called immediately after a successful deploy."
    )
    params: ClassVar[dict[str, str]] = {
        "summary": "Clear description of what was built or changed."
    }

    @override
    async def execute(self, args: dict[str, Any], state: AgentState) -> str:
        if not state.deploy:
            return "error: you must successfully deploy before calling done"
        state.done = True
        state.summary = args.get("summary", "")
        return "done"

    @override
    def format_progress(
        self, _args: dict[str, Any], _result: str, _state: AgentState
    ) -> str | None:
        return None


TOOLS: list[Tool] = [
    WriteFileTool(),
    PatchFileTool(),
    ReadFileTool(),
    GrepTool(),
    FetchTool(),
    DeployTool(),
    DoneTool(),
    *(([WebSearchTool(), WebFetchTool()]) if OLLAMA_API_KEY else []),
]

TOOL_MAP: dict[str, Tool] = {t.name: t for t in TOOLS}
TOOL_SCHEMAS: list[dict[str, Any]] = [t.schema() for t in TOOLS]
