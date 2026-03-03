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
from utils.common import sanitize_tb
from utils.option import CommandOption, OptionType

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
        typ_str = f"=<{opt.type.label}>" if opt.type is not OptionType.Boolean else ""
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

    # parse tokens
    i = 0
    while i < len(tokens):
        if tokens[i].startswith("--"):
            part = tokens[i][2:]
            if "=" in part:
                key, val = part.split("=", 1)
            else:
                key, val = part, True
            if key not in named:
                return None, f"unknown option --{key}"
            args[key] = val
            i += 1
        elif pos_opt:
            args[pos_opt.key] = " ".join(tokens[i:])
            break
        else:
            return None, f"unexpected argument '{tokens[i]}'"

    # validate and fill defaults
    for opt in schema:
        if opt.key not in args:
            if opt.required and opt.default is None:
                label = f"<{opt.key}>" if opt.positional else f"--{opt.key}"
                return None, f"{label} is required"
            args[opt.key] = opt.default
            continue

        val = args[opt.key]
        if val is True and opt.type is not OptionType.Boolean:
            return None, f"--{opt.key} expects {opt.type.label}"

        if not isinstance(val, bool):
            try:
                args[opt.key] = opt.type.validate(str(val))
            except (ValueError, TypeError):
                label = f"<{opt.key}>" if opt.positional else f"--{opt.key}"
                return None, f"{label} expects {opt.type.label}"

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
        typ_str = f"=<{opt.type.label}>" if opt.type is not OptionType.Boolean else ""
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
            cmd_name = args.get("command")
            if cmd_name:
                entry = self._commands.get(cmd_name)
                if entry is None or entry.owner == "system":
                    await ctx.message.reply(embed=ui.command_not_found())
                else:
                    await ctx.message.reply(content=f"```\n{build_help(entry)}\n```")
                return
            commands = [(format_signature(e), e.description) for e in self.get_all()]
            embeds = ui.help_list_embeds(commands)
            await ctx.message.reply(embeds=embeds)

        self._commands["help"] = CommandEntry(
            name="help",
            callback=help_cmd,
            schema=[
                CommandOption(
                    key="command",
                    description="command to look up",
                    type=OptionType.String,
                    positional=True,
                    required=False,
                )
            ],
            description="show all commands, or options for a specific command",
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
