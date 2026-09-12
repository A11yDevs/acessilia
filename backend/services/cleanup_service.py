import shutil
import asyncio
import time
from pathlib import Path

from backend.i18n import t
from backend.log_messages import (
    LOG_CLEANUP_ITEM_FAILED,
    LOG_CLEANUP_OUTPUT_FAILED,
    LOG_CLEANUP_PERIODIC_ERROR,
    LOG_OUTPUT_DIR_REMOVED,
    LOG_TEMP_DIR_REMOVED,
    LOG_TEMP_FILE_REMOVED,
)
from backend.tools.logger import logger
from backend.agents.state_manager import state_manager
from backend.config.settings import settings
from backend.services.queue_service import unified_queue
from backend.services.download_token_service import (
    TOKEN_EXPIRY_DAYS,
    limpar_tokens_expirados,
)


CLEANUP_INTERVAL = 3600
FILE_MAX_AGE = 7200
OUTPUT_MAX_AGE = TOKEN_EXPIRY_DAYS * 24 * 60 * 60
IN_MEMORY_STATUS_MAX_AGE = FILE_MAX_AGE


async def periodic_cleanup() -> None:
    while True:
        try:
            _clean_temp_directory()
            _clean_output_directory()
            _clean_in_memory_statuses()
            await limpar_tokens_expirados()
        except Exception:
            logger.exception(t(LOG_CLEANUP_PERIODIC_ERROR))
        await asyncio.sleep(CLEANUP_INTERVAL)


def _is_stale(path: Path, now: float, max_age: int) -> bool:
    """Check whether the file/directory has been inactive for longer than max_age.

    Args:
        path (Path): File or directory path whose freshness is tested.
        now (float): Current epoch timestamp the age is computed against.
        max_age (int): Maximum acceptable idle age in seconds before the path counts as stale.

    Returns:
        bool: True when the path has been idle for longer than max_age with no recent children inside it (for directories), False otherwise.
    """
    try:
        if path.is_file():
            return (now - path.stat().st_mtime) > max_age
        if path.is_dir():
            dir_age = now - path.stat().st_mtime
            if dir_age <= max_age:
                return False
            # Check for any recently-modified files nested in the directory.
            for child in path.rglob("*"):
                if child.is_file() and (now - child.stat().st_mtime) <= max_age:
                    return False
            return True
    except OSError:
        return False
    return False


def _clean_temp_directory() -> None:
    temp_dir = settings.temp_dir
    if not temp_dir.exists():
        return

    now = time.time()
    protected_paths = unified_queue.protected_file_paths()

    def clean_item(item: Path) -> None:
        if item.resolve() in protected_paths:
            return
        try:
            stale = _is_stale(item, now, FILE_MAX_AGE)
            if item.is_dir() and not item.is_symlink():
                for child in item.iterdir():
                    clean_item(child)
                if stale and not any(item.iterdir()):
                    item.rmdir()
                    logger.debug("Diretório temporário removido: {}", item.name)
            elif stale:
                item.unlink()
                logger.debug("Arquivo temporário removido: {}", item.name)
        except OSError as exc:
            logger.warning("Falha ao remover {}: {}", item.name, exc)

    for item in temp_dir.iterdir():
        if item.name in ("output", "cache", "web_output"):
            continue
        clean_item(item)


def _clean_output_directory() -> None:
    """Remove stale output directories (outputs from expired jobs)."""
    output_dir = settings.data_dir / "output"
    if not output_dir.exists():
        return

    now = time.time()
    for item in output_dir.iterdir():
        if item.is_dir() and _is_stale(item, now, OUTPUT_MAX_AGE):
            try:
                shutil.rmtree(item, ignore_errors=True)
                logger.debug(t(LOG_OUTPUT_DIR_REMOVED).format(name=item.name))
            except Exception as e:
                logger.warning(
                    t(LOG_CLEANUP_OUTPUT_FAILED).format(name=item.name, error=e)
                )


def _clean_in_memory_statuses() -> None:
    from backend.api.worker import expirar_status_fila

    removed_tasks = state_manager.expirar_tarefas_terminais(IN_MEMORY_STATUS_MAX_AGE)
    removed_queue = expirar_status_fila(IN_MEMORY_STATUS_MAX_AGE)
    if removed_tasks or removed_queue:
        logger.debug(
            "Estados em memória removidos: tarefas={}, fila={}",
            removed_tasks,
            removed_queue,
        )
