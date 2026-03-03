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
from thing.base import CommandOption, CommandType
from utils.sanitize_tb import sanitize_tb

if TYPE_CHECKING:
    from thing.manager import ThingManager

logger = logging.getLogger(__name__)


@dataclass
class CommandEntry:
    name: str
    callback: Callable[..., Any]
    schema: list[CommandOption]
    description: str
    owner: str
    of: str | None = None

    @property
    def full_name(self) -> str:
        return f"{self.of} {self.name}" if self.of else self.name


def format_signature(entry: CommandEntry) -> str:
    parts = [entry.full_name]
    pos_opt = next((o for o in entry.schema if o.positional), None)
    if pos_opt:
        parts.append(f"<{pos_opt.key}>" if pos_opt.required else f"[<{pos_opt.key}>]")
    for opt in entry.schema:
        if opt.positional:
            continue
        typ_str = f"=<{opt.type.label}>" if opt.type is not CommandType.Boolean else ""
        parts.append(
            f"--{opt.key}{typ_str}" if opt.required else f"[--{opt.key}{typ_str}]"
        )
    return " ".join(parts)


def parse_args(
    tokens: list[str], schema: list[CommandOption]
) -> tuple[dict[str, Any] | None, str | None]:
    args: dict[str, Any] = {}
    named = {o.key: o for o in schema if not o.positional}
    pos_opt = next((o for o in schema if o.positional), None)

    # Phase 1: greedily consume leading --flags
    i = 0
    while i < len(tokens) and tokens[i].startswith("--"):
        part = tokens[i][2:]
        if "=" in part:
            key, val = part.split("=", 1)
        else:
            key, val = part, True  # bare flag
        if key not in named:
            return None, f"unknown option --{key}"
        if val is True and named[key].type is not CommandType.Boolean:
            return None, f"--{key} is a flag but expects {named[key].type.label}"
        args[key] = val
        i += 1

    # Phase 2: remainder is positional content
    remaining = tokens[i:]
    if remaining:
        if pos_opt is None:
            return None, f"unexpected argument '{remaining[0]}'"
        args[pos_opt.key] = " ".join(remaining)
    elif pos_opt is not None:
        args[pos_opt.key] = ""

    # Phase 3: validate required positional, fill named defaults, type-cast named args
    if pos_opt is not None and pos_opt.required and not args[pos_opt.key].strip():
        return None, f"<{pos_opt.key}> is required"

    for key, opt in named.items():
        if key in args:
            continue
        if opt.required:
            return None, f"--{key}=<value> is required"
        args[key] = opt.default

    for key, val in list(args.items()):
        if val is True:
            continue  # already validated as Boolean in phase 1
        opt = named.get(key)
        if opt is None or opt.positional:
            continue
        try:
            args[key] = opt.type.cast(val)
        except (ValueError, TypeError):
            return None, f"--{key} expects {opt.type.label}"

    return args, None


def build_help(entry: CommandEntry) -> str:
    schema = entry.schema
    pos_opt = next((o for o in schema if o.positional), None)
    pos_part = f" <{pos_opt.key}>" if pos_opt else ""
    lines = [
        f"usage: {COMMAND_PREFIX}{entry.full_name}{pos_part} [options]",
        entry.description,
        "",
    ]

    def _fmt_default(opt: CommandOption) -> str:
        if opt.required:
            return ""
        val = opt.default
        return f" (default: {val if val != '' and val is not None else '<empty>'})"

    def _fmt_required(opt: CommandOption) -> str:
        return " (required)" if opt.required else ""

    def _flag_sig(opt: CommandOption) -> str:
        typ_str = f"=<{opt.type.label}>" if opt.type is not CommandType.Boolean else ""
        return f"--{opt.key}{typ_str}"

    rows: list[tuple[str, str]] = []
    if pos_opt:
        rows.append(
            (
                f"<{pos_opt.key}>",
                f"{pos_opt.description}{_fmt_default(pos_opt)}{_fmt_required(pos_opt)}",
            )
        )
    for opt in schema:
        if opt.positional:
            continue
        rows.append(
            (
                _flag_sig(opt),
                f"{opt.description}{_fmt_default(opt)}{_fmt_required(opt)}",
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
            embed = ui.help_list()
            for e in self.get_all():
                embed.add_field(
                    name=format_signature(e), value=e.description, inline=False
                )
            await ctx.message.reply(embed=embed)

        self._commands["help"] = CommandEntry(
            name="help",
            callback=help_cmd,
            schema=[
                CommandOption(
                    key="command",
                    positional=True,
                    default="",
                    description="command to look up",
                )
            ],
            description="show all commands, or help for a specific command",
            owner="system",
        )

    def register(
        self,
        name: str,
        callback: Callable[..., Any],
        schema: list[CommandOption],
        description: str,
        owner: str,
        of: str | None = None,
    ):
        entry = CommandEntry(name, callback, schema, description, owner, of)
        if entry.full_name in self._commands:
            raise ValueError(
                f"command '{entry.full_name}' is already registered by '{self._commands[entry.full_name].owner}'"
            )
        self._commands[entry.full_name] = entry
        logger.info("registered command '%s' for '%s'", entry.full_name, owner)

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
        rest = tokens[1:]

        sub_key = f"{name} {rest[0].lower()}" if rest else None
        if sub_key and sub_key in self._commands:
            entry = self._commands[sub_key]
            rest = rest[1:]
        elif name in self._commands:
            entry = self._commands[name]
        else:
            return False

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
