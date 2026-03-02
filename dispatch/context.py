from __future__ import annotations

from dataclasses import dataclass

import discord


@dataclass
class ThingContext:
    """Context passed to every command and event handler."""

    message: discord.Message
    channel: discord.abc.Messageable
    author: discord.abc.User
    guild: discord.Guild | None
