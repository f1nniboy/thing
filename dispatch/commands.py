from __future__ import annotations

import asyncio
import logging
import shlex
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import ui
from config import COMMAND_PREFIX, HANDLER_TIMEOUT
from dispatch.context import ThingContext
from utils.sanitize_tb import sanitize_tb

if TYPE_CHECKING:
    from thing.manager import ThingManager

logger = logging.getLogger(__name__)


@dataclass
class CommandEntry:
    name: str
    callback: Callable[..., Any]
    schema: dict[str, Any]
    description: str
    owner: str


def _positional_key(schema: dict[str, Any]) -> str | None:
    for key, spec in schema.items():
        if spec.get("positional"):
            return key
    return None


def format_signature(entry: CommandEntry) -> str:
    parts = [entry.name]
    pos_key = _positional_key(entry.schema)
    if pos_key:
        spec = entry.schema[pos_key]
        parts.append(f"<{pos_key}>" if spec.get("required") else f"[<{pos_key}>]")
    for key, spec in entry.schema.items():
        if spec.get("positional"):
            continue
        typ = spec.get("type", bool)
        typ_str = f"=<{typ.__name__}>" if typ is not bool else ""
        parts.append(
            f"--{key}{typ_str}" if spec.get("required") else f"[--{key}{typ_str}]"
        )
    return " ".join(parts)


def parse_args(
    tokens: list[str], schema: dict[str, Any]
) -> tuple[dict[str, Any] | None, str | None]:
    content_parts: list[str] = []
    args: dict[str, Any] = {}
    pos_key = _positional_key(schema)

    for tok in tokens:
        if tok.startswith("--"):
            part = tok[2:]
            if "=" in part:
                key, val = part.split("=", 1)
            else:
                key, val = part, True  # bare flag - bool
            args[key] = val
        else:
            content_parts.append(tok)

    if pos_key is not None:
        positional = " ".join(content_parts)
        if schema[pos_key].get("required") and not positional.strip():
            return None, f"<{pos_key}> is required"
        args[pos_key] = positional
    # non-flag, non-positional tokens are silently ignored (unknown input)

    for key, spec in schema.items():
        if spec.get("positional") or key in args:
            continue
        if spec.get("required"):
            return None, f"--{key}=<value> is required"
        if "default" in spec:
            args[key] = spec["default"]

    for key, val in list(args.items()):
        spec = schema.get(key, {})
        if spec.get("positional") or val is True:
            continue
        typ = spec.get("type")
        if typ and typ is not bool and not isinstance(val, typ):
            try:
                args[key] = typ(val)
            except (ValueError, TypeError):
                return None, f"--{key} expects {typ.__name__}"

    return args, None


def build_help(entry: CommandEntry) -> str:
    schema = entry.schema
    pos_key = _positional_key(schema)
    pos_part = f" <{pos_key}>" if pos_key else ""
    lines = [
        f"usage: {COMMAND_PREFIX}{entry.name}{pos_part} [options]",
        entry.description,
        "",
    ]

    def _fmt_default(spec: dict[str, Any]) -> str:
        if "default" not in spec:
            return ""
        val = spec["default"]
        return f" (default: {val if val != '' else '<empty>'})"

    def _flag_sig(key: str, spec: dict[str, Any]) -> str:
        typ = spec.get("type", bool)
        typ_str = f"=<{typ.__name__}>" if typ is not bool else ""
        return f"--{key}{typ_str}"

    rows: list[tuple[str, str]] = []
    if pos_key:
        spec = schema[pos_key]
        req = " (required)" if spec.get("required") else ""
        rows.append(
            (f"<{pos_key}>", f"{spec.get('description', '')}{_fmt_default(spec)}{req}")
        )

    flag_specs = {k: v for k, v in schema.items() if not v.get("positional")}
    for key, spec in flag_specs.items():
        req = " (required)" if spec.get("required") else ""
        rows.append(
            (
                _flag_sig(key, spec),
                f"{spec.get('description', '')}{_fmt_default(spec)}{req}",
            )
        )

    if rows:
        col_width = max(len(sig) for sig, _ in rows)
        lines.append("options:")
        for sig, desc in rows:
            lines.append(f"  {sig.ljust(col_width)}    {desc}")

    return "\n".join(lines)


class CommandHandler:
    _manager: ThingManager

    def __init__(self, manager: ThingManager):
        self._manager = manager
        self._commands: dict[str, CommandEntry] = {}
        self._register_help()

    def _register_help(self):
        async def help_cmd(ctx: ThingContext, args: dict[str, Any]):
            cmd_name = (args.get("command") or "").strip()
            if cmd_name:
                entry = self._commands.get(cmd_name)
                if entry is None or entry.owner == "system":
                    await ctx.message.reply(embed=ui.command_not_found())
                else:
                    await ctx.message.reply(content=f"```\n{build_help(entry)}\n```")
                return
            entries = [e for e in self._commands.values() if e.owner != "system"]
            embed = ui.help_list()
            for e in entries:
                embed.add_field(
                    name=format_signature(e), value=e.description, inline=False
                )
            await ctx.message.reply(embed=embed)

        self._commands["help"] = CommandEntry(
            name="help",
            callback=help_cmd,
            schema={
                "command": {
                    "positional": True,
                    "required": False,
                    "description": "command to look up",
                }
            },
            description="show all commands, or help for a specific command",
            owner="system",
        )

    def register(
        self,
        name: str,
        callback: Callable[..., Any],
        schema: dict[str, Any],
        description: str,
        owner: str,
    ):
        if name in self._commands:
            raise ValueError(
                f"command '{name}' is already registered by '{self._commands[name].owner}'"
            )
        self._commands[name] = CommandEntry(name, callback, schema, description, owner)
        logger.info("registered command '%s' for '%s'", name, owner)

    def unregister_owner(self, owner: str):
        gone = [n for n, e in self._commands.items() if e.owner == owner]
        for n in gone:
            del self._commands[n]
        if gone:
            logger.info("unregistered commands for '%s': %s", owner, gone)

    def get_all(self) -> list[CommandEntry]:
        return [e for e in self._commands.values() if e.owner != "system"]

    async def dispatch(self, ctx: ThingContext) -> bool:
        """Dispatch a message to the matching command. Returns True if consumed."""
        if not ctx.message.content.startswith(COMMAND_PREFIX):
            return False
        raw = ctx.message.content[len(COMMAND_PREFIX) :].strip()
        if not raw:
            return False
        try:
            tokens = shlex.split(raw)
        except ValueError:
            tokens = raw.split()

        name = tokens[0].lower()
        if name not in self._commands:
            return False

        entry = self._commands[name]
        rest = tokens[1:]

        if "--help" in rest:
            await ctx.message.reply(content=f"```\n{build_help(entry)}\n```")
            return True

        parsed, error = parse_args(rest, entry.schema)
        if error is not None:
            await ctx.message.reply(
                content=f"```\nerror: {error}\n\n{build_help(entry)}\n```"
            )
            return True

        call = entry.callback(ctx, parsed)
        try:
            await asyncio.wait_for(call, timeout=HANDLER_TIMEOUT)
        except asyncio.TimeoutError:
            await ctx.message.reply(embed=ui.command_timed_out())
        except Exception:
            logger.error(
                "error in command '%s' (owner '%s')",
                name,
                entry.owner,
                exc_info=True,
            )
            self._manager.record_error(entry.owner, "command", name)
            await ctx.message.reply(
                embed=ui.command_error(sanitize_tb(traceback.format_exc()))
            )
        return True
