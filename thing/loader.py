from __future__ import annotations

import ast
import asyncio
import logging
import sys
import types
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ThingInfo:
    source: str
    name: str | None = None
    requirements: list[str] = field(default_factory=list)


def extract_thing_info(code: str) -> ThingInfo:
    """Parse source once via AST and extract NAME and REQUIREMENTS from the Thing class body."""
    info = ThingInfo(source=code)
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return info
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            if isinstance(item, ast.Assign):
                targets = [t for t in item.targets if isinstance(t, ast.Name)]
                value_node = item.value
            elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                targets = [item.target]
                value_node = item.value
            else:
                continue
            if value_node is None:
                continue
            for target in targets:
                if target.id == "NAME" and isinstance(value_node, ast.Constant):
                    info.name = str(value_node.value)
                elif target.id == "REQUIREMENTS":
                    try:
                        value = ast.literal_eval(value_node)
                        if isinstance(value, list):
                            info.requirements = [
                                s for s in value if isinstance(s, str) and s.strip()
                            ]
                    except Exception as e:
                        logger.warning("failed to parse REQUIREMENTS: %s", e)
        if info.name is not None:
            break  # found the Thing class, no need to keep walking
    return info


async def _try_install(cmd: list[str], packages: list[str]) -> bool:
    """Run an install command. Returns True on success, False if the tool is unavailable."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            *packages,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return False
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise RuntimeError(f"package install timed out: {packages}")
    if proc.returncode != 0:
        raise RuntimeError(f"package install failed:\n{stderr.decode()}")
    return True


async def pip_install(packages: list[str]):
    for cmd in (
        ["uv", "pip", "install"],
        [sys.executable, "-m", "pip", "install"],
    ):
        if await _try_install(cmd, packages):
            logger.info("installed %s via %s", packages, cmd[0])
            return
    raise RuntimeError(
        f"cannot install packages {packages}: no package manager available. rewrite without external dependencies."
    )


def load_module(source: str, injected: dict[str, Any], name: str) -> types.ModuleType:
    code = compile(source, f"things/{name}.py", "exec")
    module = types.ModuleType(f"thing_{name}")
    module.__dict__.update(injected)
    try:
        exec(code, module.__dict__)
    except Exception as e:
        raise RuntimeError(f"failed to exec module: {e}") from e
    return module


def register_module(module: types.ModuleType, name: str):
    module.__name__ = f"thing_{name}"
    sys.modules[f"thing_{name}"] = module


def unregister_module(name: str):
    sys.modules.pop(f"thing_{name}")
