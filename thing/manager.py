from __future__ import annotations

import logging
import os
import traceback
import types
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import aiofiles
import discord

from ai.api import API, GenerateOptions, WebFetchResult, WebSearchResult
from config import DB_DIR, THING_ERROR_HISTORY, THINGS_DIR
from dispatch.commands import CommandHandler
from dispatch.context import ThingContext
from dispatch.events import EventBroker
from thing.base import Thing, ThingServices, command, event
from thing.db import DB
from thing.loader import (
    ThingInfo,
    extract_thing_info,
    load_module,
    pip_install,
    register_module,
    unregister_module,
)
from utils.sanitize_tb import sanitize_tb

logger = logging.getLogger(__name__)


@dataclass
class ThingError:
    kind: str
    name: str
    error: str


@dataclass
class ThingEntry:
    name: str
    info: ThingInfo
    instance: Thing
    module: types.ModuleType
    errors: deque[ThingError] = field(
        default_factory=lambda: deque(maxlen=THING_ERROR_HISTORY)
    )


class ThingManager:
    bot: discord.Client
    command_handler: CommandHandler
    event_broker: EventBroker
    ai: API

    def __init__(self, bot: discord.Client, ai: API):
        self.bot = bot
        self.ai = ai
        self._INJECTED: dict[str, Any] = {
            "Thing": Thing,
            "DB": DB,
            "command": command,
            "event": event,
            "ThingContext": ThingContext,
            "GenerateOptions": GenerateOptions,
            "WebSearchResult": WebSearchResult,
            "WebFetchResult": WebFetchResult,
            "API": API,
            "discord": discord,
        }
        self.command_handler = CommandHandler(self)
        self.event_broker = EventBroker(self)
        self._things: dict[str, ThingEntry] = {}

    def _cleanup(self, name: str):
        self.command_handler.unregister_owner(name)
        self.event_broker.unregister_owner(name)
        unregister_module(name)

    async def load(self, info: ThingInfo) -> Thing:
        if not info.name:
            raise RuntimeError("could not determine Thing.NAME from source")
        if info.name == "unnamed":
            raise ValueError("thing NAME is still 'unnamed', set a unique name")
        if info.name in self._things:
            raise ValueError(f"thing '{info.name}' is already loaded")

        if info.requirements:
            await pip_install(info.requirements)

        module = load_module(info.source, self._INJECTED, info.name)
        thing_class = self._find_thing_class(module)

        if thing_class is None:
            raise RuntimeError(
                "no Thing subclass found in file, make sure it inherits from base class"
            )

        name = info.name
        register_module(module, name)
        try:
            instance = thing_class(ThingServices(bot=self.bot, db=DB(name), ai=self.ai))
            self._register_handlers(instance, name)
            await instance.setup()
            self._things[name] = ThingEntry(
                name=name, info=info, instance=instance, module=module
            )
        except Exception:
            self._cleanup(name)
            raise
        path = os.path.join(THINGS_DIR, f"{name}.py")
        async with aiofiles.open(path, "w", encoding="utf-8") as f:
            await f.write(info.source)
        logger.info("loaded thing '%s'", name)
        return instance

    def _register_handlers(self, instance: Thing, name: str):
        for attr_name, fn in type(instance).__dict__.items():
            kind = getattr(fn, "_thing_type", None)
            if kind == "command":
                self.command_handler.register(
                    fn._cmd_name or attr_name,
                    getattr(instance, attr_name),
                    fn._cmd_schema,
                    fn._cmd_desc,
                    owner=name,
                )
            elif kind == "event":
                self.event_broker.register(
                    fn._event_name, attr_name, getattr(instance, attr_name), owner=name
                )

    async def unload(self, name: str):
        entry = self._things.get(name)
        if not entry:
            raise KeyError(f"thing '{name}' is not loaded")
        try:
            await entry.instance.unload()
        except Exception:
            logger.warning("error in unload() for '%s'", name, exc_info=True)
        self._cleanup(name)
        del self._things[name]
        logger.info("unloaded thing '%s'", name)

    async def remove(self, name: str):
        await self.unload(name)
        for path in [
            os.path.join(THINGS_DIR, f"{name}.py"),
            os.path.join(DB_DIR, f"{name}.json"),
        ]:
            if os.path.exists(path):
                os.remove(path)

    async def reload(self, name: str) -> Thing:
        path = os.path.join(THINGS_DIR, f"{name}.py")
        await self.unload(name)
        async with aiofiles.open(path, encoding="utf-8") as f:
            src = await f.read()
        return await self.load(extract_thing_info(src))

    async def load_all(self):
        os.makedirs(THINGS_DIR, exist_ok=True)
        for filename in sorted(
            f
            for f in os.listdir(THINGS_DIR)
            if f.endswith(".py") and not f.startswith(".")
        ):
            path = os.path.join(THINGS_DIR, filename)
            try:
                async with aiofiles.open(path, encoding="utf-8") as f:
                    src = await f.read()
                await self.load(extract_thing_info(src))
            except Exception:
                logger.error("failed to load '%s'", filename, exc_info=True)

    def get(self, name: str) -> ThingEntry | None:
        return self._things.get(name)

    def names(self) -> list[str]:
        return list(self._things.keys())

    def record_error(self, name: str, kind: str, handler_name: str):
        thing = self._things.get(name)
        if thing:
            thing.errors.append(
                ThingError(
                    kind=kind,
                    name=handler_name,
                    error=sanitize_tb(traceback.format_exc()),
                )
            )

    @staticmethod
    def _find_thing_class(module: Any) -> type[Thing] | None:
        candidates = []
        for attr in vars(module).values():
            try:
                if (
                    isinstance(attr, type)
                    and issubclass(attr, Thing)
                    and attr is not Thing
                ):
                    candidates.append(attr)
            except TypeError:
                continue
        if not candidates:
            return None
        direct = [c for c in candidates if c.__mro__[1] is Thing]
        return direct[0] if direct else candidates[0]
