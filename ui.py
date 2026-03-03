from __future__ import annotations

import asyncio
from typing import Any, ClassVar

import discord

from ai.types import AgentResult
from dispatch.commands import CommandHandler
from dispatch.events import EventBroker
from thing.config import ConfigOption
from utils.sanitize_tb import sanitize_tb


class ProgressLog:
    INTERVAL: ClassVar[float] = 5.0
    MAX_DISPLAY: ClassVar[int] = 5

    def __init__(self, msg: discord.Message, embed: discord.Embed):
        self._msg: discord.Message = msg
        self._embed: discord.Embed = embed
        self._lines: list[str] = []
        self._dirty: bool = False
        self._task: asyncio.Task[None] = asyncio.create_task(self._ticker())

    def _render(self) -> str:
        if not self._lines:
            return ""
        visible = (
            self._lines
            if len(self._lines) <= self.MAX_DISPLAY
            else ["..."] + self._lines[-(self.MAX_DISPLAY - 1) :]
        )
        return "\n".join(f"> {l}" for l in visible)

    async def _ticker(self):
        try:
            while True:
                await asyncio.sleep(self.INTERVAL)
                if self._dirty:
                    self._embed.description = self._render()
                    await self._msg.edit(embed=self._embed)
                    self._dirty = False
        except asyncio.CancelledError:
            pass

    def update(self, text: str):
        self._lines.append(text)
        self._dirty = True

    async def stop(self):
        self._task.cancel()
        await self._task


def agent_progress(name: str | None) -> discord.Embed:
    return discord.Embed(
        color=discord.Color.dark_embed(),
        title=f"⏳ {f'working on `{name}`' if name else 'creating'}...",
    )


def agent_failed(name: str | None, exc: BaseException) -> discord.Embed:
    return discord.Embed(
        color=discord.Color.brand_red(),
        title=f"❌ failed to {f'work on `{name}`' if name else 'create'}",
        description=f"`{type(exc).__name__}: {sanitize_tb(str(exc))}`",
    )


def thing_removed(name: str) -> discord.Embed:
    return discord.Embed(
        color=discord.Color.dark_embed(), description=f"🗑️ removed `{name}`"
    )


def thing_reloaded(name: str) -> discord.Embed:
    return discord.Embed(
        color=discord.Color.dark_embed(), description=f"🔄 reloaded `{name}`"
    )


def reload_failed(name: str, exc: BaseException) -> discord.Embed:
    return discord.Embed(
        color=discord.Color.brand_red(),
        title=f"⚠️ failed to reload `{name}`",
        description=f"```\n{exc}\n```",
    )


def command_not_found() -> discord.Embed:
    return discord.Embed(
        color=discord.Color.brand_red(), description="that command doesn't exist 😔"
    )


def help_list() -> discord.Embed:
    return discord.Embed(color=discord.Color.dark_embed(), title="commands")


def command_timed_out() -> discord.Embed:
    return discord.Embed(
        color=discord.Color.brand_red(), description="command timed out 😮"
    )


def command_error(tb: str) -> discord.Embed:
    return discord.Embed(
        color=discord.Color.brand_red(),
        title="something went wrong 😔",
        description=f"```\n{tb}\n```",
    )


def access_denied() -> discord.Embed:
    return discord.Embed(
        color=discord.Color.brand_red(), description="you don't have access ❌"
    )


def not_found(name: str) -> discord.Embed:
    return discord.Embed(
        color=discord.Color.brand_red(), description=f"thing `{name}` not found ❌"
    )


def overview_list_embed(names: list[str]) -> discord.Embed:
    if not names:
        return discord.Embed(
            color=discord.Color.dark_embed(), description="no things loaded 😔"
        )
    lines = [f"* `{n}`" for n in names]
    return discord.Embed(
        color=discord.Color.dark_embed(),
        title="🔧 things",
        description="\n".join(lines),
    )


def thing_fields(
    embed: discord.Embed,
    name: str,
    command_handler: CommandHandler,
    event_broker: EventBroker,
):
    commands = [e for e in command_handler.get_all() if e.owner == name]
    events = event_broker.get_for_owner(name)
    if commands:
        embed.add_field(
            name="📟 commands",
            value="\n".join(f"`{e.full_name}` → {e.description}" for e in commands),
            inline=False,
        )
    if events:
        embed.add_field(
            name="📡 events",
            value="\n".join(f"`{h.func_name}` → `{h.event_name}`" for h in events),
            inline=False,
        )


def thing_summary_embed(
    result: AgentResult,
    command_handler: CommandHandler,
    event_broker: EventBroker,
) -> discord.Embed:
    embed = discord.Embed(
        color=discord.Color.brand_green(),
        title=f"✅ `{result.name}`",
        description=result.summary or None,
    )
    thing_fields(embed, result.name, command_handler, event_broker)
    return embed


def thing_detail_embed(
    name: str,
    command_handler: CommandHandler,
    event_broker: EventBroker,
) -> discord.Embed:
    embed = discord.Embed(color=discord.Color.dark_embed(), title=f"🔧 `{name}`")
    thing_fields(embed, name, command_handler, event_broker)
    return embed


def settings_error(message: str) -> discord.Embed:
    return discord.Embed(color=discord.Color.brand_red(), description=f"{message} ❌")


def settings_updated(
    thing_name: str, key: str, humanized: str, reset: bool
) -> discord.Embed:
    if reset:
        color = discord.Color.blurple()
        desc = f"🔄 **{thing_name}.{key}** reset to {humanized}"
    else:
        color = discord.Color.brand_green()
        desc = f"✅ **{thing_name}.{key}** set to {humanized}"
    return discord.Embed(color=color, description=desc)


def settings_show_embed(entries: list[tuple[str, ConfigOption, Any]]) -> discord.Embed:
    if not entries:
        return discord.Embed(
            color=discord.Color.dark_embed(),
            description="no configurable options 😔",
        )

    embed = discord.Embed(color=discord.Color.dark_embed(), title="⚙️ settings")

    # Group by thing name
    by_thing: dict[str, list[tuple[ConfigOption, Any]]] = {}
    for thing_name, option, current in entries:
        by_thing.setdefault(thing_name, []).append((option, current))

    for thing_name, opts in by_thing.items():
        lines = []
        for option, current in opts:
            lines.append(f"> **{option.description}**: {option.type.humanize(current)}")
        embed.add_field(name=f"**{thing_name}**", value="\n".join(lines), inline=False)

    return embed
