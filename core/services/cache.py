import hashlib
import json
import time
from pathlib import Path
from typing import Any

import aiofiles
import aiofiles.os

from core.utils.logger import logger

CACHE_DIR = Path("temp/cache")


def _ensure_cache_dir() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _file_hash(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()[:16]


def _cache_key(path: Path, extra: str = "") -> str:
    digest = _file_hash(path)
    return f"{digest}_{extra}"


def _cache_path(key: str) -> Path:
    return CACHE_DIR / f"{key}.json"


async def get_cached(path: Path, extra: str = "", ttl: int = 3600) -> Any:
    _ensure_cache_dir()
    key = _cache_key(path, extra)
    cp = _cache_path(key)
    try:
        async with aiofiles.open(str(cp), "r", encoding="utf-8") as f:
            content = await f.read()
    except FileNotFoundError:
        return None
    except Exception:
        return None
    try:
        data = json.loads(content)
        if time.time() - data["timestamp"] > ttl:
            await aiofiles.os.remove(str(cp))
            return None
        logger.debug("Cache hit: {}", key)
        if "payload" in data:
            return data["payload"]
        return data.get("text")
    except Exception:
        try:
            await aiofiles.os.remove(str(cp))
        except OSError:
            pass
        return None


async def set_cache(path: Path, payload: Any, extra: str = "") -> None:
    _ensure_cache_dir()
    key = _cache_key(path, extra)
    cp = _cache_path(key)
    try:
        data = {"timestamp": time.time(), "payload": payload}
        if isinstance(payload, str):
            data["text"] = payload
        async with aiofiles.open(str(cp), "w", encoding="utf-8") as f:
            await f.write(json.dumps(data, ensure_ascii=False))
        logger.debug("Cache set: {}", key)
    except Exception as e:
        logger.warning("Falha ao salvar cache: {}", e)


async def clear_cache() -> int:
    _ensure_cache_dir()
    count = 0
    for f in CACHE_DIR.iterdir():
        if f.suffix == ".json":
            await aiofiles.os.remove(str(f))
            count += 1
    logger.info("Cache limpo: {} arquivos removidos", count)
    return count
