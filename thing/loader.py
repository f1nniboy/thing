from __future__ import annotations

import ast
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
        has_thing_base = any(
            (isinstance(b, ast.Name) and b.id == "Thing")
            or (isinstance(b, ast.Attribute) and b.attr == "Thing")
            for b in node.bases
        )
        if not has_thing_base:
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
                    except Exception:
                        logger.warning("failed to parse REQUIREMENTS", exc_info=True)
        if info.name is not None:
            break  # found the Thing class, no need to keep walking
    return info


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
