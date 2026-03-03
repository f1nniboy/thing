from __future__ import annotations

import logging

import discord
from discord import app_commands

import ui
from ai.agent import AgentRunner
from ai.types import DeployResult
from config import ALLOWED_USERS
from thing.loader import extract_thing_info
from thing.manager import ThingEntry, ThingManager
from ui import ProgressLog

logger = logging.getLogger(__name__)


def _allowed(interaction: discord.Interaction) -> bool:
    return interaction.user.id in ALLOWED_USERS


async def _require_thing(
    interaction: discord.Interaction, manager: ThingManager, name: str
) -> ThingEntry | None:
    entry = manager.get(name)
    if not entry:
        await interaction.response.send_message(
            embed=ui.not_found(name), ephemeral=True
        )
    return entry


def _make_deploy_cb(
    manager: ThingManager,
    existing_entry: ThingEntry | None,
):
    async def deploy_cb(content: str) -> DeployResult:
        info = extract_thing_info(content)
        name = info.name
        if not name:
            return DeployResult(error="could not determine Thing.NAME from code")

        if existing_entry is None:
            if name in manager.names():
                return DeployResult(
                    error=f"Thing NAME '{name}' is already loaded - choose a different NAME",
                )
        else:
            try:
                await manager.unload(existing_entry.name)
            except Exception:
                logger.warning(
                    "unload failed for '%s' before redeploy",
                    existing_entry.name,
                    exc_info=True,
                )

        try:
            await manager.load(info)
            return DeployResult(name=name)
        except Exception as e:
            if existing_entry is not None:
                try:
                    await manager.load(existing_entry.info)
                except Exception as restore_err:
                    logger.error(
                        "failed to restore after deploy error: %s", restore_err
                    )
            return DeployResult(error=str(e))

    return deploy_cb


def build_thing_group(manager: ThingManager) -> app_commands.Group:
    group = app_commands.Group(name="thing", description="...")
    command_handler = manager.command_handler
    event_broker = manager.event_broker
    runner = AgentRunner(manager, manager.ai)

    @group.error
    async def _on_error(  # pyright: ignore[reportUnusedFunction]
        interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        if isinstance(error, app_commands.CheckFailure):
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    embed=ui.access_denied(), ephemeral=True
                )

    async def name_autocomplete(_interaction: discord.Interaction, current: str):
        return [
            app_commands.Choice(name=n, value=n)
            for n in manager.names()
            if current.lower() in n.lower()
        ][:25]

    async def _run_agent_command(
        interaction: discord.Interaction,
        prompt: str,
        existing_entry: ThingEntry | None = None,
    ):
        name = existing_entry.name if existing_entry else None
        embed = ui.agent_progress(name)
        await interaction.response.send_message(embed=embed)
        msg = await interaction.original_response()
        log = ProgressLog(msg, embed)

        try:
            result = await runner.run(
                prompt,
                deploy_cb=_make_deploy_cb(manager, existing_entry),
                progress_cb=log.update,
                existing_entry=existing_entry,
            )
        except Exception as e:
            logger.error("failed to run agent", exc_info=True)
            final_embed = ui.agent_failed(name, e)
        else:
            if result.name is None:
                final_embed = ui.agent_refused(name, result.summary)
            else:
                entry = manager.get(result.name)
                assert entry is not None
                final_embed = ui.thing_summary_embed(
                    result, entry, command_handler, event_broker
                )
        finally:
            await log.stop()
        await msg.edit(embed=final_embed)

    @group.command(name="create", description="generate and load a new thing")
    @app_commands.describe(prompt="what this thing should do")
    @app_commands.check(_allowed)
    async def thing_create(interaction: discord.Interaction, prompt: str):  # pyright: ignore[reportUnusedFunction]
        await _run_agent_command(interaction, prompt)

    @group.command(name="change", description="modify an existing thing")
    @app_commands.describe(name="thing to change", prompt="what to change")
    @app_commands.autocomplete(name=name_autocomplete)
    @app_commands.check(_allowed)
    async def thing_change(interaction: discord.Interaction, name: str, prompt: str):  # pyright: ignore[reportUnusedFunction]
        entry = await _require_thing(interaction, manager, name)
        if entry is None:
            return
        await _run_agent_command(interaction, prompt, existing_entry=entry)

    @group.command(name="remove", description="unload and delete a thing")
    @app_commands.describe(name="thing to remove")
    @app_commands.autocomplete(name=name_autocomplete)
    @app_commands.check(_allowed)
    async def thing_remove(interaction: discord.Interaction, name: str):  # pyright: ignore[reportUnusedFunction]
        if await _require_thing(interaction, manager, name) is None:
            return
        await manager.remove(name)
        await interaction.response.send_message(embed=ui.thing_removed(name))

    @group.command(name="reload", description="reload a thing from disk")
    @app_commands.describe(name="thing to reload")
    @app_commands.autocomplete(name=name_autocomplete)
    @app_commands.check(_allowed)
    async def thing_reload(interaction: discord.Interaction, name: str):  # pyright: ignore[reportUnusedFunction]
        if await _require_thing(interaction, manager, name) is None:
            return
        try:
            await manager.reload(name)
            await interaction.response.send_message(embed=ui.thing_reloaded(name))
        except Exception as e:
            await interaction.response.send_message(embed=ui.reload_failed(name, e))

    @group.command(name="show", description="list things, or inspect one")
    @app_commands.describe(name="thing to inspect")
    @app_commands.autocomplete(name=name_autocomplete)
    @app_commands.check(_allowed)
    async def thing_show(  # pyright: ignore[reportUnusedFunction]
        interaction: discord.Interaction, name: str | None = None
    ):
        if name:
            entry = await _require_thing(interaction, manager, name)
            if entry is None:
                return
            await interaction.response.send_message(
                embed=ui.thing_detail_embed(entry, command_handler, event_broker),
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                embed=ui.overview_list_embed(manager.names()),
                ephemeral=True,
            )

    return group


def build_settings_group(manager: ThingManager) -> app_commands.Group:
    group = app_commands.Group(name="settings", description="...")

    @group.error
    async def _on_error(  # pyright: ignore[reportUnusedFunction]
        interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        if isinstance(error, app_commands.CheckFailure):
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    embed=ui.access_denied(), ephemeral=True
                )

    async def key_autocomplete(_interaction: discord.Interaction, current: str):
        choices = []
        for name in manager.names():
            entry = manager.get(name)
            if entry is None:
                continue
            for option in entry.instance.config.options.values():
                full_key = f"{name}.{option.key}"
                if current.lower() in full_key.lower():
                    choices.append(
                        app_commands.Choice(
                            name=f"{name} → {option.description}",
                            value=full_key,
                        )
                    )
        return choices[:25]

    @group.command(name="set", description="set or reset a config value")
    @app_commands.describe(key="config key", value="new value, omit to reset")
    @app_commands.autocomplete(key=key_autocomplete)
    @app_commands.check(_allowed)
    async def settings_set(  # pyright: ignore[reportUnusedFunction]
        interaction: discord.Interaction, key: str, value: str | None = None
    ):
        parts = key.split(".", 1)
        if len(parts) != 2:
            await interaction.response.send_message(
                embed=ui.settings_error("select a valid config option"),
                ephemeral=True,
            )
            return

        thing_name, option_key = parts
        cfg = manager.get_config(thing_name)
        if cfg is None or option_key not in cfg.options:
            await interaction.response.send_message(
                embed=ui.settings_error(f"unknown config option `{key}`"),
                ephemeral=True,
            )
            return

        option = cfg.options[option_key]

        typed_value = None
        if value is not None:
            try:
                typed_value = option.type.validate(value)
            except ValueError as e:
                await interaction.response.send_message(
                    embed=ui.settings_error(str(e)),
                    ephemeral=True,
                )
                return

        await cfg.set(option_key, typed_value)
        humanized = option.type.humanize(
            option.default if typed_value is None else typed_value
        )
        await interaction.response.send_message(
            embed=ui.settings_updated(
                thing_name, option_key, humanized, reset=typed_value is None
            ),
            ephemeral=True,
        )

    @group.command(name="show", description="show all settings and current values")
    @app_commands.check(_allowed)
    async def settings_show(interaction: discord.Interaction):  # pyright: ignore[reportUnusedFunction]
        entries = []
        for name in manager.names():
            entry = manager.get(name)
            if entry is None:
                continue
            cfg = entry.instance.config
            if not cfg.options:
                continue
            for option in cfg.options.values():
                current = cfg.get(option.key)
                entries.append((name, option, current))

        await interaction.response.send_message(
            embed=ui.settings_show_embed(entries),
            ephemeral=True,
        )

    return group
