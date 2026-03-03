from __future__ import annotations

import asyncio
from typing import Any

import discord

from ai.types import AgentResult
from config import PROGRESS_INTERVAL, PROGRESS_MAX_DISPLAY
from dispatch.commands import CommandHandler
from dispatch.events import EventBroker
from thing.manager import ThingEntry
from utils.common import sanitize_tb
from utils.option import ConfigOption


class ProgressLog:
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
            if len(self._lines) <= PROGRESS_MAX_DISPLAY
            else ["..."] + self._lines[-(PROGRESS_MAX_DISPLAY - 1) :]
        )
        return "\n".join(f"> {l}" for l in visible)

    async def _ticker(self):
        try:
            while True:
                await asyncio.sleep(PROGRESS_INTERVAL)
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


def agent_refused(name: str | None, reason: str) -> discord.Embed:
    return discord.Embed(
        color=discord.Color.brand_red(),
        title=f"😔 refused to {f'work on `{name}`' if name else 'create'}",
        description=reason,
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


def help_list_embeds(commands: list[tuple[str, str]]) -> list[discord.Embed]:
    """Split commands into multiple embeds (max 25 fields per embed, max 10 embeds)."""
    if not commands:
        return [
            discord.Embed(
                color=discord.Color.dark_embed(), description="no commands available"
            )
        ]

    embeds = []
    MAX_FIELDS = 25

    for i in range(0, len(commands), MAX_FIELDS):
        chunk = commands[i : i + MAX_FIELDS]
        # First embed gets title, others don't
        title = "commands" if i == 0 else None
        embed = discord.Embed(color=discord.Color.dark_embed(), title=title)

        for sig, desc in chunk:
            embed.add_field(name=sig, value=desc, inline=False)

        embeds.append(embed)

    return embeds[:10]  # Discord limit: max 10 embeds per message


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
    entry: ThingEntry,
    command_handler: CommandHandler,
    event_broker: EventBroker,
):
    commands = [e for e in command_handler.get_all() if e.owner == entry.name]
    events = event_broker.get_for_owner(entry.name)
    config_options = entry.instance.config.options
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
    if config_options:
        embed.add_field(
            name="⚙️ settings",
            value="\n".join(
                f"`{o.key}` → {o.description}" for o in config_options.values()
            ),
            inline=False,
        )


def thing_summary_embed(
    result: AgentResult,
    entry: ThingEntry,
    command_handler: CommandHandler,
    event_broker: EventBroker,
) -> discord.Embed:
    embed = discord.Embed(
        color=discord.Color.brand_green(),
        title=f"✅ `{entry.name}`",
        description=result.summary or None,
    )
    thing_fields(embed, entry, command_handler, event_broker)
    return embed


def thing_detail_embed(
    entry: ThingEntry,
    command_handler: CommandHandler,
    event_broker: EventBroker,
) -> discord.Embed:
    embed = discord.Embed(color=discord.Color.dark_embed(), title=f"🔧 `{entry.name}`")
    thing_fields(embed, entry, command_handler, event_broker)
    return embed


def settings_error(message: str) -> discord.Embed:
    return discord.Embed(color=discord.Color.brand_red(), description=f"{message} ❌")


def settings_updated(
    thing_name: str, key: str, humanized: str | None, reset: bool
) -> discord.Embed:
    if reset:
        color = discord.Color.blurple()
        desc = (
            f"🔄 **{thing_name}.{key}** reset"
            if humanized is None
            else f"🔄 **{thing_name}.{key}** reset to {humanized}"
        )
    else:
        color = discord.Color.brand_green()
        desc = (
            f"✅ **{thing_name}.{key}** set"
            if humanized is None
            else f"✅ **{thing_name}.{key}** set to {humanized}"
        )
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
            humanized = option.type.humanize(current)
            lines.append(
                f"> **{option.description}**: {humanized if humanized is not None else '*(none)*'}"
            )
        embed.add_field(name=f"**{thing_name}**", value="\n".join(lines), inline=False)

    return embed
