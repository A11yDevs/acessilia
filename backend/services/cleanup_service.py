import asyncio
import time
from pathlib import Path

from backend.i18n import t
from backend.log_messages import (
    LOG_CLEANUP_OUTPUT_FAILED,
    LOG_CLEANUP_PERIODIC_ERROR,
)
from backend.tools.logger import logger
from backend.agents.state_manager import state_manager
from backend.config.settings import settings
from backend.services.queue_service import unified_queue
from backend.services.blocking import run_blocking
from backend.services.download_token_service import (
    TOKEN_EXPIRY_DAYS,
    limpar_tokens_expirados,
    remove_unreferenced_output_directory,
    active_download_directories,
)


CLEANUP_INTERVAL = 3600
FILE_MAX_AGE = 7200
OUTPUT_MAX_AGE = TOKEN_EXPIRY_DAYS * 24 * 60 * 60
IN_MEMORY_STATUS_MAX_AGE = FILE_MAX_AGE
#: Cache entries older than this are swept: entries are expired on read, but
#: ones never read again would otherwise live on disk forever. Matches the
#: longest TTL in the codebase (the vision region answers).
CACHE_MAX_AGE = 7 * 24 * 60 * 60


def _clean_cache_directory() -> None:
    """Remove cache entries (and leftover temp writes) older than ``CACHE_MAX_AGE``."""
    from backend.services.cache import CACHE_DIR, _active_cache_writes
    from backend.services.cache_lock import cache_directory_lock

    if not CACHE_DIR.exists():
        return
    now = time.time()
    removed = 0
    with cache_directory_lock(CACHE_DIR):
        for item in CACHE_DIR.iterdir():
            try:
                if item.resolve() in _active_cache_writes:
                    continue
                if item.is_file() and now - item.stat().st_mtime > CACHE_MAX_AGE:
                    item.unlink()
                    removed += 1
            except OSError as exc:
                logger.warning("Falha ao remover {}: {}", item.name, exc)
    if removed:
        logger.debug("Entradas de cache expiradas removidas: {}", removed)


def _clean_fusion_artifact_directory() -> None:
    """Remove persisted fusion inputs after the cache retention period."""
    artifact_dir = settings.data_dir / "artifacts" / "fusion"
    if not artifact_dir.exists():
        return

    now = time.time()
    removed = 0
    for item in artifact_dir.iterdir():
        try:
            if item.is_file() and now - item.stat().st_mtime > CACHE_MAX_AGE:
                item.unlink()
                removed += 1
        except OSError as exc:
            logger.warning("Could not remove fusion artifact {}: {}", item.name, exc)
    if removed:
        logger.debug("Expired fusion artifacts removed: {}", removed)


async def periodic_cleanup() -> None:
    while True:
        try:
            protected_paths = unified_queue.protected_file_paths()
            await run_blocking(_clean_temp_directory, protected_paths)
            await run_blocking(_clean_output_directory)
            await run_blocking(_clean_cache_directory)
            await run_blocking(_clean_fusion_artifact_directory)
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


def _clean_temp_directory(protected_paths: set[Path] | None = None) -> None:
    temp_dir = settings.temp_dir
    if not temp_dir.exists():
        return

    now = time.time()
    if protected_paths is None:
        protected_paths = unified_queue.protected_file_paths()

    def clean_item(item: Path, active_dirs: set[Path]) -> None:
        resolved = item.resolve()
        if resolved in protected_paths or any(
            resolved == active or active in resolved.parents for active in active_dirs
        ):
            return
        try:
            stale = _is_stale(item, now, FILE_MAX_AGE)
            if item.is_dir() and not item.is_symlink():
                for child in item.iterdir():
                    clean_item(child, active_dirs)
                if stale and not any(item.iterdir()):
                    item.rmdir()
                    logger.debug("Diretório temporário removido: {}", item.name)
            elif stale:
                item.unlink()
                logger.debug("Arquivo temporário removido: {}", item.name)
        except OSError as exc:
            logger.warning("Falha ao remover {}: {}", item.name, exc)

    with active_download_directories() as active_dirs:
        for item in temp_dir.iterdir():
            if item.name in ("output", "cache", "web_output"):
                continue
            clean_item(item, active_dirs)


def _clean_output_directory() -> None:
    """Remove stale output directories (outputs from expired jobs)."""
    output_dir = settings.data_dir / "output"
    if not output_dir.exists():
        return

    now = time.time()
    for item in output_dir.iterdir():
        if item.is_dir() and _is_stale(item, now, OUTPUT_MAX_AGE):
            try:
                remove_unreferenced_output_directory(item)
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
