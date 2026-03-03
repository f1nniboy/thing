from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, override

import discord

from ai.api import API
from thing.config import ConfigOption, ThingConfig
from thing.db import DB


class _CmdHandler:
    @classmethod
    def cast(cls, value_str: str) -> Any:
        return value_str


class _CmdIntegerHandler(_CmdHandler):
    @override
    @classmethod
    def cast(cls, value_str: str) -> Any:
        return int(value_str)


class _CmdFloatHandler(_CmdHandler):
    @override
    @classmethod
    def cast(cls, value_str: str) -> Any:
        return float(value_str)


class _CmdBooleanHandler(_CmdHandler):
    @override
    @classmethod
    def cast(cls, value_str: str) -> Any:
        if value_str.lower() in ("yes", "true", "1"):
            return True
        if value_str.lower() in ("no", "false", "0"):
            return False
        raise ValueError(f"invalid boolean value: {value_str!r}")


class CommandType(Enum):
    String = _CmdHandler
    Integer = _CmdIntegerHandler
    Float = _CmdFloatHandler
    Boolean = _CmdBooleanHandler

    def cast(self, value_str: str) -> Any:
        return self.value.cast(value_str)

    @property
    def label(self) -> str:
        return self.name.lower()


@dataclass
class CommandOption:
    key: str
    type: CommandType = CommandType.String
    required: bool = True
    default: Any = None
    positional: bool = False
    description: str = ""

    def __post_init__(self) -> None:
        if self.default is not None:
            self.required = False


def command(
    schema: list[CommandOption] | None = None,
    description: str = "",
    name: str | None = None,
    of: str | None = None,
):
    r"""
    Decorator to register a method as a prefix command.

    The command name defaults to the method name. Override with name="...".
    Use of="parent" to register as a subcommand. Don't add a handler for the
    base command if you use subcommands.

    schema is a list of CommandOption. Positional captures all non-flag tokens.
    Named args use --key=value. Boolean flags may be bare: --verbose.
    Required options have no default. Types: String, Integer, Float, Boolean.

    Example:
        @command(of="soko", name="play", description="Start a new game")
        async def soko_play(self, ctx, args): ...     # $soko play

        @command(
            name="download",
            description="Download a YouTube video",
            schema=[
                CommandOption(key="url", positional=True, description="YouTube URL"),
                CommandOption(key="fmt", type=CommandType.String, default="mp3", description="mp3 or mp4"),
                CommandOption(key="verbose", type=CommandType.Boolean, default=False, description="verbose output"),
            ],
        )
        async def download(self, ctx, args: dict):
            url = args["url"]       # required positional string
            fmt = args["fmt"]       # "mp3" if omitted
            count = args["count"]   # 1 if omitted (already cast to int)
            verbose = args["verbose"]  # False if omitted, True if --verbose bare flag
    """

    def decorator(fn: Any) -> Any:
        fn._thing_type = "command"
        fn._cmd_name = name
        fn._cmd_schema = schema or []
        fn._cmd_desc = description
        fn._cmd_of = of
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
    config: ThingConfig


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
        self.config - ThingConfig for reading declared CONFIG options
        self.logger - logging.Logger for this Thing
    """

    NAME: str = "unnamed"
    REQUIREMENTS: list[str] = []
    CONFIG: list[ConfigOption] = []

    def __init__(self, services: ThingServices):
        self.bot: discord.Client = services.bot
        self.db: DB = services.db
        self.ai: API = services.ai
        self.config: ThingConfig = services.config
        self.logger: logging.Logger = logging.getLogger(f"thing.{self.NAME}")
        self.logger.setLevel(logging.DEBUG)

    async def setup(self):
        """Override for async initialisation after registration. Called once on load."""
        pass

    async def unload(self):
        """Override for async cleanup before unload."""
        pass
