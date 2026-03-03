from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from ai.api import API
from ai.prompt import build_system_prompt
from ai.tools import TOOL_MAP, TOOL_SCHEMAS
from ai.types import AgentResult, AgentState, DeployResult
from config import MAX_TOOL_CALLS
from thing.manager import ThingEntry
from utils.common import clean_for_display

if TYPE_CHECKING:
    from thing.manager import ThingManager

logger = logging.getLogger(__name__)


class AgentRunner:
    _manager: ThingManager
    _ai: API

    def __init__(self, manager: ThingManager, ai: API):
        self._manager = manager
        self._ai = ai

    async def run(
        self,
        prompt: str,
        deploy_cb: Callable[[str], Awaitable[DeployResult]],
        progress_cb: Callable[[str], None],
        existing_entry: ThingEntry | None = None,
    ) -> AgentResult:
        parts = []
        if existing_entry:
            existing_code = existing_entry.info.source

            parts.append(
                f"Modify the existing Thing below. Change requested:\n{prompt}"
            )

            errors = list(existing_entry.errors)
            if errors:
                error_lines = ["Recent unhandled errors:"]
                error_lines += [f"{e.kind} ({e.name}): {e.error}" for e in errors]
                parts.append("\n".join(error_lines))

            parts.append(f"Existing code:\n```python\n{existing_code}\n```")
            parts.append(
                "Prefer patch_file for targeted changes. Only use write_file if the change is too broad to patch cleanly."
            )

        else:
            all_names = self._manager.names()
            parts = [f"Create a new Thing for: {prompt}"]
            if all_names:
                parts.append(
                    f"Existing Thing NAMEs already in use (do NOT reuse): {', '.join(all_names)}"
                )

        user_msg = "\n\n".join(parts)

        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": build_system_prompt(self._manager),
            },
            {"role": "user", "content": user_msg},
        ]
        state = AgentState(
            content=existing_entry.info.source if existing_entry else None,
            deploy_cb=deploy_cb,
            api=self._ai,
        )

        while not state.done:
            if state.tool_call_count >= MAX_TOOL_CALLS:
                raise RuntimeError(
                    f"agent exceeded {MAX_TOOL_CALLS} tool calls without completing"
                )

            msg = await self._ai.chat(messages, tools=TOOL_SCHEMAS, think=True)

            thinking = msg.thinking
            content = msg.content
            tool_calls = msg.tool_calls

            if thinking:
                logger.debug("thinking:\n%s", thinking)
                progress_cb(f"💭 {clean_for_display(thinking)}")

            messages.append(
                {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": [
                        {
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            }
                        }
                        for tc in tool_calls
                    ],
                }
            )

            if not tool_calls:
                state.no_tool_call_count += 1
                if state.no_tool_call_count >= 3:
                    raise RuntimeError(
                        "agent returned text without tool calls 3 times in a row"
                    )
                logger.warning("agent returned text without tool call")
                messages.append(
                    {
                        "role": "user",
                        "content": "Continue using the tools to complete the task.",
                    }
                )
                continue

            for tc in tool_calls:
                tool_name = tc.function.name
                tool_args = (
                    tc.function.arguments
                    if isinstance(tc.function.arguments, dict)
                    else {}
                )
                tool = TOOL_MAP.get(tool_name)
                state.tool_call_count += 1
                state.no_tool_call_count = 0

                if tool is None:
                    messages.append(
                        {
                            "role": "tool",
                            "content": f"error: unknown tool '{tool_name}'",
                        }
                    )
                    continue
                logger.debug("tool call: %s -> %s", tool_name, tool_args)
                result = await tool.execute(tool_args, state)
                logger.debug("tool result: %s -> %s", tool_name, result)

                line = tool.format_progress(tool_args, result, state)
                if line:
                    progress_cb(line)

                messages.append({"role": "tool", "content": result})

                if state.done:
                    break

        return AgentResult(
            summary=state.summary,
            name=state.deploy.name if state.deploy else None,
        )
