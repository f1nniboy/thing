from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

import aiofiles

from config import DB_DIR

logger = logging.getLogger(__name__)


class DB:
    """Persistent async key-value store for a Thing.

    Only use self.db when you need data to survive bot restarts. For in-memory
    state, use plain instance attributes instead.

    All methods are async and must be awaited. Keys support dot-notation to
    address nested values - e.g. "stats.guild_id.user_id.messages".

    Simple example:

        @command(name="count", description="Increment and show a counter", schema={})
        async def count(self, ctx):
            n = await self.db.get("count", 0)
            await self.db.set("count", n + 1)
            await ctx.message.reply(content=f"count: {n + 1}")

    Nested example - per-guild, per-user stats:

        guild_id = str(ctx.guild.id)
        user_id = str(ctx.author.id)

        # Initialise defaults, then increment:
        n = await self.db.get(f"stats.{guild_id}.{user_id}.messages", 0)
        await self.db.set(f"stats.{guild_id}.{user_id}.messages", n + 1)

        # Read back an entire user subtree:
        user = await self.db.get(f"stats.{guild_id}.{user_id}", {})

        # Delete a user entry:
        await self.db.delete(f"stats.{guild_id}.{user_id}")
    """

    _path: str
    _lock: asyncio.Lock
    _cache: dict[str, Any] | None

    def __init__(self, thing_name: str):
        self._path = os.path.join(DB_DIR, f"{thing_name}.json")
        self._lock = asyncio.Lock()
        self._cache = None

    async def _read(self) -> dict[str, Any]:
        if self._cache is not None:
            return self._cache
        if not os.path.exists(self._path):
            return {}
        async with aiofiles.open(self._path, encoding="utf-8") as f:
            try:
                data: dict[str, Any] = json.loads(await f.read())
            except json.JSONDecodeError:
                logger.error("corrupt JSON in %s, resetting", self._path)
                data = {}
        self._cache = data
        return data

    async def _write(self, data: dict[str, Any]):
        os.makedirs(DB_DIR, exist_ok=True)
        tmp = self._path + ".tmp"
        async with aiofiles.open(tmp, "w", encoding="utf-8") as f:
            await f.write(json.dumps(data, indent=2))
        os.replace(tmp, self._path)
        self._cache = data

    async def get(self, key: str, default: Any = None) -> Any:
        """Return the value at key (dot-notation supported), or default if not set."""
        async with self._lock:
            node = await self._read()
            try:
                for k in key.split("."):
                    node = node[k]
                return node
            except (KeyError, TypeError):
                return default

    async def set(self, key: str, value: Any) -> None:
        """Store value at key (dot-notation supported). Intermediate dicts are created automatically."""
        async with self._lock:
            data = await self._read()
            keys = key.split(".")
            node = data
            for k in keys[:-1]:
                if k not in node or not isinstance(node[k], dict):
                    node[k] = {}
                node = node[k]
            node[keys[-1]] = value
            await self._write(data)

    async def delete(self, key: str):
        """Remove key (dot-notation supported). No-op if not set."""
        async with self._lock:
            data = await self._read()
            keys = key.split(".")
            try:
                node = data
                for k in keys[:-1]:
                    node = node[k]
                node.pop(keys[-1], None)
            except (KeyError, TypeError):
                pass
            await self._write(data)

    async def all(self) -> dict[str, Any]:
        """Return a copy of all stored entries."""
        async with self._lock:
            return await self._read()

    async def clear(self):
        """Delete all stored entries."""
        async with self._lock:
            await self._write({})
