import asyncio
import shutil
import sys

import httpx

from bot.utils.logger import logger
from config.settings import settings


def _resolve_opencode_command() -> tuple[str, ...]:
    """Resolve executable name for OpenCode across platforms."""
    # Windows usually installs opencode.cmd, while Unix-like uses opencode.
    candidates = (
        ("opencode.cmd", "opencode")
        if sys.platform == "win32"
        else ("opencode", "opencode.cmd")
    )
    for cmd in candidates:
        if shutil.which(cmd):
            return (cmd, "serve")
    raise FileNotFoundError(
        "OpenCode executable not found. Install OpenCode and ensure "
        "'opencode' is available in PATH, or switch AI_CLIENT to "
        "'openrouter'/'ollama'."
    )


async def is_running() -> bool:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{settings.opencode_url}/global/health")
            return resp.status_code == 200
    except Exception:
        return False


async def start_serve() -> asyncio.subprocess.Process:
    logger.info("Starting opencode serve...")
    command = _resolve_opencode_command()
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    logger.info(
        "opencode serve started with '{}' (pid={})",
        command[0],
        process.pid,
    )
    return process


async def wait_for_ready(max_retries: int = 10, interval: float = 2.0) -> bool:
    for attempt in range(1, max_retries + 1):
        if await is_running():
            logger.info(
                "OpenCode serve is ready (attempt {}/{})",
                attempt,
                max_retries,
            )
            return True
        logger.info(
            "Waiting for OpenCode serve... ({}/{})",
            attempt,
            max_retries,
        )
        await asyncio.sleep(interval)
    return False


async def ensure_opencode_running() -> None:
    if await is_running():
        logger.info(
            "OpenCode serve already running at {}",
            settings.opencode_url,
        )
        return

    try:
        await start_serve()
    except FileNotFoundError as err:
        logger.critical("{}", err)
        sys.exit(1)

    if not await wait_for_ready():
        logger.critical(
            "Failed to start OpenCode serve at {}",
            settings.opencode_url,
        )
        sys.exit(1)
