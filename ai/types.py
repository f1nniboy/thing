from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai.api import API


@dataclass
class DeployResult:
    name: str | None = None
    error: str | None = None


@dataclass
class AgentState:
    deploy_cb: Callable[[str], Awaitable[DeployResult]]
    api: API
    content: str | None = None
    deploy: DeployResult | None = None
    tool_call_count: int = 0
    no_tool_call_count: int = 0
    done: bool = False
    summary: str = ""


@dataclass
class AgentResult:
    summary: str
    name: str
