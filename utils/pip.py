from __future__ import annotations

import asyncio
import logging
import shutil
import sys

logger = logging.getLogger(__name__)


def _installers() -> list[list[str]]:
    cmds: list[list[str]] = []
    if shutil.which("uv"):
        cmds.append(["uv", "pip", "install"])
    if shutil.which("pip") or shutil.which("pip3"):
        cmds.append([sys.executable, "-m", "pip", "install"])
    return cmds


def check_pip():
    if not _installers():
        logger.error(
            "no package installer found; will fail to install additional dependencies"
        )


async def _try_install(cmd: list[str], packages: list[str]) -> bool:
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
    if not _installers():
        raise RuntimeError(
            f"no package manager available, cannot install {packages}. rewrite without external dependencies or fail()."
        )
    for cmd in _installers():
        try:
            if await _try_install(cmd, packages):
                logger.info("installed %s via %s", packages, cmd[0])
                return
        except RuntimeError as e:
            logger.warning("installer %s failed: %s", cmd[0], e)
    raise RuntimeError(
        f"cannot install {packages}: all installers failed. rewrite without external dependencies or fail()."
    )
