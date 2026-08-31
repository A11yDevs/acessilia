import shutil
import asyncio
import time
from pathlib import Path

from backend.tools.logger import logger
from backend.config.settings import settings


CLEANUP_INTERVAL = 3600
FILE_MAX_AGE = 7200


async def periodic_cleanup() -> None:
    while True:
        try:
            _clean_temp_directory()
            _clean_output_directory()
        except Exception:
            logger.exception("Erro na limpeza periódica")
        await asyncio.sleep(CLEANUP_INTERVAL)


def _is_stale(path: Path, now: float, max_age: int) -> bool:
    """Verifica se o arquivo/diretório está inativo há mais que max_age."""
    try:
        if path.is_file():
            return (now - path.stat().st_mtime) > max_age
        if path.is_dir():
            dir_age = now - path.stat().st_mtime
            if dir_age <= max_age:
                return False
            # Verifica se há arquivos recentes dentro do diretório
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
    for item in temp_dir.iterdir():
        if item.name in ("output", "cache", "web_output"):
            continue
        if _is_stale(item, now, FILE_MAX_AGE):
            try:
                if item.is_file():
                    item.unlink()
                    logger.debug("Arquivo temporário removido: {}", item.name)
                elif item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
                    logger.debug("Diretório temporário removido: {}", item.name)
            except Exception as e:
                logger.warning("Falha ao remover {}: {}", item.name, e)


def _clean_output_directory() -> None:
    """Remove diretorios de output antigos (outputs de jobs expirados)."""
    output_dir = settings.data_dir / "output"
    if not output_dir.exists():
        return

    now = time.time()
    for item in output_dir.iterdir():
        if item.is_dir() and _is_stale(item, now, FILE_MAX_AGE * 12):
            try:
                shutil.rmtree(item, ignore_errors=True)
                logger.debug("Diretorio de output removido: {}", item.name)
            except Exception as e:
                logger.warning("Falha ao remover output {}: {}", item.name, e)
