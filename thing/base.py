from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import discord

from ai.api import API
from thing.db import DB


def command(
    schema: dict[str, Any] | None = None,
    description: str = "",
    name: str | None = None,
):
    r"""
    Decorator to register a method as a prefix command.

    The command name defaults to the method name. Override with name="...".

    schema format:
    {
        "text":    {"positional": True, "required": True,  "description": "the input"},
        "to":      {"type": str,  "required": True,  "description": "target lang"},
        "from":    {"type": str,  "default": "auto", "required": False, "description": "source lang"},
        "verbose": {"type": bool, "default": False,  "required": False, "description": "verbose mode"},
    }
    Flags use --key=value format. Bool flags are bare: --verbose.
    One arg may have "positional": True - it captures all non-flag tokens.

    Example:
        @command(
            name="roll",
            description="Roll dice, e.g. 2d6",
            schema={"dice": {"positional": True, "required": True, "description": "dice notation e.g. 2d6"}},
        )
        async def roll(self, ctx, args: dict):
            import random, re
            m = re.match(r'(\d+)d(\d+)', args["dice"])
            if not m:
                return await ctx.message.reply(content="usage: 2d6")
            n, sides = int(m.group(1)), int(m.group(2))
            results = [random.randint(1, sides) for _ in range(n)]
            await ctx.message.reply(content=f"🎲 {results} = **{sum(results)}**")
    """

    def decorator(fn: Any) -> Any:
        fn._thing_type = "command"
        fn._cmd_name = name
        fn._cmd_schema = schema or {}
        fn._cmd_desc = description
        return fn

    return decorator


def event(event_name: str):
    """
    Decorator to register a method as a discord event handler.

    Examples:
        @event("message")
        async def watch_channel(self, message: discord.Message):
            if message.channel.id == 123456789:
                await message.reply(content=message.content)

        @event("ready")
        async def on_ready(self):
            print("bot is ready")
    """

    def decorator(fn: Any) -> Any:
        fn._thing_type = "event"
        fn._event_name = event_name
        return fn

    return decorator


@dataclass
class ThingServices:
    bot: discord.Client
    db: DB
    ai: API


class Thing:
    """
    Base class for all generated Things.

    Decorate methods with @command(...) or @event(...) to register them.
    Do NOT override __init__ - use setup() for async initialisation and unload() for cleanup.
    Do NOT import Thing, DB, command, event, ThingContext, or discord -
    they are all pre-injected into the module namespace.

    Available instance attributes (set by __init__, do NOT redefine):
        self.bot    - discord.Client instance
        self.db     - DB persistent key-value store
        self.ai     - AI API instance
        self.logger - logging.Logger for this Thing
    """

    NAME: str = "unnamed"
    REQUIREMENTS: list[str] = []

    def __init__(self, services: ThingServices):
        self.bot: discord.Client = services.bot
        self.db: DB = services.db
        self.ai: API = services.ai
        self.logger: logging.Logger = logging.getLogger(f"thing.{self.NAME}")
        self.logger.setLevel(logging.DEBUG)

    async def setup(self):
        """Override for async initialisation after registration. Called once on load."""
        pass

    async def unload(self):
        """Override for async cleanup before unload."""
        pass
