from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, final

import aiofiles

from config import CONFIG_DIR
from utils.option import ConfigOption

logger = logging.getLogger(__name__)


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
        """Return the current value for key (override if set, else option default, else None).
        This will return the default set in ConfigOption item, so you CAN'T include the fallback here."""
        if key in self._data:
            return self._data[key]
        option = self._options.get(key)
        if option is not None:
            return option.default
        return None

    async def set(self, key: str, value: Any):
        """Store a typed value and persist to disk. Pass None to reset/remove the key."""
        async with self._lock:
            if value is None:
                self._data.pop(key, None)
            else:
                self._data[key] = value
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
