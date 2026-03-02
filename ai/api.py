from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import ollama

from config import OLLAMA_API_KEY, OLLAMA_HOST, OLLAMA_MODEL, OLLAMA_OPTIONS, OLLAMA_TIMEOUT


@dataclass
class GenerateOptions:
    """Optional overrides for a generate call."""

    temperature: float | None = None


@dataclass
class ChatMessage:
    content: str
    tool_calls: list[Any]
    thinking: str | None = None


@dataclass
class WebSearchResult:
    title: str | None
    url: str | None
    content: str | None


@dataclass
class WebFetchResult:
    title: str | None
    content: str | None
    links: list[str] = field(default_factory=list)


class API:
    _client: ollama.AsyncClient

    def __init__(self):
        headers = (
            {"Authorization": f"Bearer {OLLAMA_API_KEY}"} if OLLAMA_API_KEY else {}
        )
        self._client = ollama.AsyncClient(host=OLLAMA_HOST, headers=headers)

    async def generate(
        self,
        messages: list[tuple[str, str]],
        options: GenerateOptions | None = None,
    ) -> str:
        """Generate a text response. Only use when the request explicitly asks for AI.

        Example:
            @command(
                name="ask",
                description="Ask the AI a question",
                schema={"question": {"positional": True, "required": True, "description": "your question"}},
            )
            async def ask(self, ctx, args: dict):
                answer = await self.ai.generate([
                    ("system", "You are a helpful assistant. Be concise."),
                    ("user", args["question"]),
                ])
                await ctx.message.reply(content=answer)

            # With custom temperature:
            # answer = await self.ai.generate([...], options=GenerateOptions(temperature=0.2))
        """
        opts = dict(OLLAMA_OPTIONS)
        if options is not None:
            if options.temperature is not None:
                opts["temperature"] = options.temperature
        response = await asyncio.wait_for(
            self._client.chat(
                model=OLLAMA_MODEL,
                messages=[{"role": r, "content": c} for r, c in messages],
                options=opts,
            ),
            timeout=OLLAMA_TIMEOUT,
        )
        return response.message.content or ""

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        think: bool = False,
    ) -> ChatMessage:
        kwargs: dict[str, Any] = {
            "model": OLLAMA_MODEL,
            "messages": messages,
            "options": OLLAMA_OPTIONS,
            "think": think,
        }
        if tools is not None:
            kwargs["tools"] = tools
        response = await asyncio.wait_for(
            self._client.chat(**kwargs),
            timeout=OLLAMA_TIMEOUT,
        )
        msg = response.message
        return ChatMessage(
            content=getattr(msg, "content", None) or "",
            tool_calls=list(getattr(msg, "tool_calls", None) or []),
            thinking=getattr(msg, "thinking", None) or None,
        )

    async def web_search(
        self, query: str, max_results: int = 5
    ) -> list[WebSearchResult]:
        """Search the web. Only use when the request explicitly asks for web search.

        Example:
            @command(
                name="search",
                description="Search the web",
                schema={"query": {"positional": True, "required": True, "description": "search query"}},
            )
            async def search(self, ctx, args: dict):
                results: list[WebSearchResult] = await self.ai.web_search(args["query"])
                if not results:
                    return await ctx.message.reply(content="No results found.")
                lines = [f"**{r.title}** - <{r.url}>\n{r.content}" for r in results[:3] if r.title]
                await ctx.channel.send("\n\n".join(lines))
        """
        if not OLLAMA_API_KEY:
            raise RuntimeError(
                "requires OLLAMA_API_KEY to be set; tell user to set API key"
            )
        response = await asyncio.wait_for(
            self._client.web_search(query, max_results),
            timeout=OLLAMA_TIMEOUT,
        )
        return [
            WebSearchResult(title=r.title, url=r.url, content=r.content)
            for r in (response.results or [])[:max_results]
        ]

    async def web_fetch(self, url: str) -> WebFetchResult:
        """Fetch and extract content from a URL.

        Example:
            result: WebFetchResult = await self.ai.web_fetch("https://example.com")
            result.title    # page title
            result.content  # extracted text
            result.links    # list of URLs found on the page
        """
        if not OLLAMA_API_KEY:
            raise RuntimeError(
                "requires OLLAMA_API_KEY to be set; tell user to set API key"
            )
        result = await asyncio.wait_for(
            self._client.web_fetch(url),
            timeout=OLLAMA_TIMEOUT,
        )
        links: list[str] = []
        raw_links = getattr(result, "links", None)
        if isinstance(raw_links, list):
            links = [str(lnk) for lnk in raw_links]
        return WebFetchResult(
            title=getattr(result, "title", None),
            content=getattr(result, "content", None),
            links=links,
        )
