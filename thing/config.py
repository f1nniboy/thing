from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from enum import Enum
from typing import Any, final, override

import aiofiles
import discord

from config import CONFIG_DIR

logger = logging.getLogger(__name__)


class _Handler:
    @classmethod
    def validate(cls, value_str: str, _bot: discord.Client) -> Any:
        return value_str

    @classmethod
    def humanize(cls, value: Any) -> str:
        return str(value)

    @classmethod
    def serialize(cls, value: Any) -> Any:
        return value

    @classmethod
    def deserialize(cls, raw: Any) -> Any:
        return raw


@final
class _IntegerHandler(_Handler):
    @classmethod
    @override
    def validate(cls, value_str: str, bot: discord.Client) -> Any:
        try:
            return int(value_str)
        except ValueError:
            raise ValueError(f"`{value_str}` is not a valid number")

    @classmethod
    @override
    def deserialize(cls, raw: Any) -> Any:
        return int(raw)


@final
class _FloatHandler(_Handler):
    @classmethod
    @override
    def validate(cls, value_str: str, bot: discord.Client) -> Any:
        try:
            return float(value_str)
        except ValueError:
            raise ValueError(f"`{value_str}` is not a valid number")

    @classmethod
    @override
    def deserialize(cls, raw: Any) -> Any:
        return float(raw)


@final
class _BooleanHandler(_Handler):
    @classmethod
    @override
    def validate(cls, value_str: str, bot: discord.Client) -> bool:
        if value_str.lower() in ("yes", "true", "1"):
            return True
        if value_str.lower() in ("no", "false", "0"):
            return False
        raise ValueError(f"invalid boolean value: {value_str!r}")

    @classmethod
    @override
    def humanize(cls, value: Any) -> str:
        return "✅" if value else "❌"

    @classmethod
    @override
    def serialize(cls, value: Any) -> Any:
        return bool(value)

    @classmethod
    @override
    def deserialize(cls, raw: Any) -> Any:
        return bool(raw)


@final
class _DiscordChannelHandler(_Handler):
    @classmethod
    @override
    def validate(cls, value_str: str, bot: discord.Client) -> int:
        try:
            channel_id = int(value_str.strip("<#>"))
        except ValueError:
            raise ValueError(f"`{value_str}` is not a valid channel ID")
        if bot.get_channel(channel_id) is None:
            raise ValueError(
                f"channel `{channel_id}` not found - make sure the bot can see it"
            )
        return channel_id

    @classmethod
    @override
    def humanize(cls, value: Any) -> str:
        return f"<#{value}>"

    @classmethod
    @override
    def serialize(cls, value: Any) -> Any:
        return int(value)

    @classmethod
    @override
    def deserialize(cls, raw: Any) -> Any:
        return int(raw)


class ConfigType(Enum):
    String = _Handler
    Integer = _IntegerHandler
    Float = _FloatHandler
    Boolean = _BooleanHandler
    DiscordChannel = _DiscordChannelHandler

    def validate(self, value_str: str, bot: discord.Client) -> Any:
        return self.value.validate(value_str, bot)

    def humanize(self, value: Any) -> str:
        return self.value.humanize(value) if value is not None else "*(empty)*"

    def serialize(self, value: Any) -> Any:
        return self.value.serialize(value)

    def deserialize(self, raw: Any) -> Any:
        return self.value.deserialize(raw)


@dataclass
class ConfigOption:
    """Declares a user-configurable value for a Thing. Set via `/settings set` by the user.

    Example:
        CONFIG = [
            ConfigOption(key="api_key", type=ConfigType.String, default=None, description="External API key"),
            ConfigOption(key="log_channel", type=ConfigType.DiscordChannel, default=None, description="Channel to log to"),
        ]

        async def setup(self):
            api_key = self.config.get("api_key")  # None until set by the user
    """

    key: str
    type: ConfigType
    default: Any
    description: str


@final
class ThingConfig:
    _options: dict[str, ConfigOption]
    _path: str
    _lock: asyncio.Lock
    _data: dict[str, Any]

    def __init__(self, name: str, options: list[ConfigOption]):
        self._options = {o.key: o for o in options}
        self._path = os.path.join(CONFIG_DIR, f"{name}.json")
        self._lock = asyncio.Lock()
        self._data = {}

    async def load(self):
        if not os.path.exists(self._path):
            return
        async with aiofiles.open(self._path, encoding="utf-8") as f:
            try:
                raw: dict[str, Any] = json.loads(await f.read())
            except json.JSONDecodeError:
                logger.error("corrupt config JSON in %s, resetting", self._path)
                return
        for key, raw_val in raw.items():
            if key in self._options:
                try:
                    self._data[key] = self._options[key].type.deserialize(raw_val)
                except Exception:
                    logger.warning(
                        "failed to deserialize config key '%s', skipping", key
                    )

    def get(self, key: str) -> Any:
        """Return the current value for key (override if set, else option default, else None)."""
        if key in self._data:
            return self._data[key]
        option = self._options.get(key)
        if option is not None:
            return option.default
        return None

    async def set(self, key: str, value: Any):
        """Store a typed value and persist to disk."""
        async with self._lock:
            self._data[key] = value
            await self._write()

    async def reset(self, key: str):
        """Remove override for key and persist to disk."""
        async with self._lock:
            self._data.pop(key, None)
            await self._write()

    async def _write(self):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        serialized = {
            key: self._options[key].type.serialize(value)
            for key, value in self._data.items()
        }
        tmp = self._path + ".tmp"
        async with aiofiles.open(tmp, "w", encoding="utf-8") as f:
            await f.write(json.dumps(serialized, indent=2))
        os.replace(tmp, self._path)

    @property
    def options(self) -> dict[str, ConfigOption]:
        return self._options
