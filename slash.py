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


def _make_deploy_cb(
    manager: ThingManager,
    existing_entry: ThingEntry | None,
):
    original_name = existing_entry.name if existing_entry is not None else None

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
            assert original_name is not None
            try:
                await manager.unload(original_name)
            except Exception:
                logger.warning(
                    "unload failed for '%s' before redeploy",
                    original_name,
                    exc_info=True,
                )

        try:
            await manager.load(info)
            return DeployResult(name=name)
        except Exception as e:
            if existing_entry is not None:
                try:
                    assert original_name is not None
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

    def allowed(interaction: discord.Interaction) -> bool:
        return interaction.user.id in ALLOWED_USERS

    async def deny(interaction: discord.Interaction):
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
            final_embed = ui.thing_summary_embed(result, command_handler, event_broker)
        finally:
            await log.stop()
        await msg.edit(embed=final_embed)

    @group.command(name="create", description="generate and load a new thing")
    @app_commands.describe(prompt="what this thing should do")
    async def thing_create(interaction: discord.Interaction, prompt: str):  # pyright: ignore[reportUnusedFunction]
        if not allowed(interaction):
            return await deny(interaction)
        await _run_agent_command(
            interaction,
            prompt,
        )

    @group.command(name="change", description="modify an existing thing")
    @app_commands.describe(name="thing to change", prompt="what to change")
    @app_commands.autocomplete(name=name_autocomplete)
    async def thing_change(interaction: discord.Interaction, name: str, prompt: str):  # pyright: ignore[reportUnusedFunction]
        if not allowed(interaction):
            return await deny(interaction)
        entry = manager.get(name)
        if not entry:
            await interaction.response.send_message(
                embed=ui.not_found(name), ephemeral=True
            )
            return
        await _run_agent_command(
            interaction,
            prompt,
            existing_entry=entry,
        )

    @group.command(name="remove", description="unload and delete a thing")
    @app_commands.describe(name="thing to remove")
    @app_commands.autocomplete(name=name_autocomplete)
    async def thing_remove(interaction: discord.Interaction, name: str):  # pyright: ignore[reportUnusedFunction]
        if not allowed(interaction):
            return await deny(interaction)
        if not manager.get(name):
            await interaction.response.send_message(
                embed=ui.not_found(name), ephemeral=True
            )
            return

        await manager.remove(name)
        await interaction.response.send_message(embed=ui.thing_removed(name))

    @group.command(name="reload", description="reload a thing from disk")
    @app_commands.describe(name="thing to reload")
    @app_commands.autocomplete(name=name_autocomplete)
    async def thing_reload(interaction: discord.Interaction, name: str):  # pyright: ignore[reportUnusedFunction]
        if not allowed(interaction):
            return await deny(interaction)
        entry = manager.get(name)
        if not entry:
            await interaction.response.send_message(
                embed=ui.not_found(name), ephemeral=True
            )
            return
        try:
            await manager.reload(name)
            await interaction.response.send_message(embed=ui.thing_reloaded(name))
        except Exception as e:
            await interaction.response.send_message(embed=ui.reload_failed(name, e))

    @group.command(name="overview", description="list things, or inspect one")
    @app_commands.describe(name="thing to inspect")
    @app_commands.autocomplete(name=name_autocomplete)
    async def thing_overview(  # pyright: ignore[reportUnusedFunction]
        interaction: discord.Interaction, name: str | None = None
    ):
        if not allowed(interaction):
            return await deny(interaction)

        if name:
            entry = manager.get(name)
            if not entry:
                await interaction.response.send_message(
                    embed=ui.not_found(name), ephemeral=True
                )
                return
            await interaction.response.send_message(
                embed=ui.thing_detail_embed(name, command_handler, event_broker),
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                embed=ui.overview_list_embed(manager.names()),
                ephemeral=True,
            )

    return group
