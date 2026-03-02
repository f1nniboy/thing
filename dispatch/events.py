from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from config import HANDLER_TIMEOUT

if TYPE_CHECKING:
    from thing.manager import ThingManager

logger = logging.getLogger(__name__)

SUPPORTED_EVENTS: dict[str, str] = {
    "on_message": "self, ctx: ThingContext",
    "on_ready": "self",
}


@dataclass
class HandlerEntry:
    event_name: str
    func_name: str
    callback: Callable[..., Any]
    owner: str


class EventBroker:
    _manager: ThingManager

    def __init__(self, manager: ThingManager):
        self._manager = manager
        self._handlers: dict[str, list[HandlerEntry]] = {}

    def register(
        self, event_name: str, func_name: str, callback: Callable[..., Any], owner: str
    ):
        if event_name not in SUPPORTED_EVENTS:
            raise ValueError(
                f"unsupported event '{event_name}'. supported: {', '.join(SUPPORTED_EVENTS)}"
            )
        self._handlers.setdefault(event_name, []).append(
            HandlerEntry(event_name, func_name, callback, owner)
        )
        logger.info("registered event '%s' (%s) for '%s'", event_name, func_name, owner)

    def unregister_owner(self, owner: str):
        removed = 0
        for event_name in list(self._handlers):
            before = len(self._handlers[event_name])
            self._handlers[event_name] = [
                h for h in self._handlers[event_name] if h.owner != owner
            ]
            removed += before - len(self._handlers[event_name])
            if not self._handlers[event_name]:
                del self._handlers[event_name]
        if removed:
            logger.info("unregistered %d event handler(s) for '%s'", removed, owner)

    def get_for_owner(self, owner: str) -> list[HandlerEntry]:
        return [
            h
            for handlers in self._handlers.values()
            for h in handlers
            if h.owner == owner
        ]

    async def emit(self, event_name: str, *args: Any, **kwargs: Any):
        for handler in self._handlers.get(event_name, []):
            try:
                await asyncio.wait_for(
                    handler.callback(*args, **kwargs), timeout=HANDLER_TIMEOUT
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "'%s' handler for '%s' timed out",
                    event_name,
                    handler.owner,
                )
            except Exception as e:
                logger.error(
                    "error in '%s' handler for '%s': %s",
                    event_name,
                    handler.owner,
                    e,
                    exc_info=True,
                )
                self._manager.record_error(handler.owner, "event", handler.func_name)
