from __future__ import annotations

import asyncio
import logging
from typing import override

import discord
from discord import app_commands

from ai.api import API
from config import ALLOWED_USERS, DISCORD_TOKEN
from dispatch.context import ThingContext
from slash import build_thing_group
from thing.manager import ThingManager

logger = logging.getLogger("bot")


class Bot(discord.Client):
    tree: app_commands.CommandTree
    manager: ThingManager
    ai: API

    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)

        self.tree = app_commands.CommandTree(self)
        self.ai = API()
        self.manager = ThingManager(self, self.ai)

    @override
    async def setup_hook(self):
        await self.manager.load_all()
        self.tree.add_command(build_thing_group(self.manager))

    async def on_ready(self):
        logger.info("online as %s", self.user)
        asyncio.create_task(self._sync())
        await self.manager.event_broker.emit("on_ready")

    async def _sync(self):
        try:
            await self.tree.sync()
            logger.info("slash commands synced")
        except Exception:
            logger.error("command sync failed", exc_info=True)

    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        ctx = ThingContext(
            message=message,
            channel=message.channel,
            author=message.author,
            guild=message.guild,
        )
        if not await self.manager.command_handler.dispatch(ctx):
            await self.manager.event_broker.emit("on_message", ctx)


if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise ValueError("DISCORD_TOKEN not set")
    if len(ALLOWED_USERS) == 0:
        raise ValueError("ALLOWED_USERS not set")
    discord.utils.setup_logging()
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("ai.agent").setLevel(logging.DEBUG)
    Bot().run(DISCORD_TOKEN, log_handler=None)
