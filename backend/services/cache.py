import hashlib
import json
import time
from pathlib import Path
from typing import Any

import aiofiles
import aiofiles.os

from backend.i18n import t
from backend.log_messages import (
    LOG_CACHE_CLEARED,
    LOG_CACHE_DEBUG_HIT,
    LOG_CACHE_DEBUG_SET,
    LOG_CACHE_SAVE_FAILED,
)
from backend.tools.logger import logger

CACHE_DIR = Path("var/temp/cache")


def _ensure_cache_dir() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _file_hash(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _cache_key(path: Path, extra: str = "") -> str:
    digest = _file_hash(path)
    file_size = path.stat().st_size if path.exists() else 0
    return f"{digest}_{file_size}_{extra}"


def _cache_path(key: str) -> Path:
    return CACHE_DIR / f"{key}.json"


def processing_cache_configuration() -> dict[str, Any]:
    """Configuration shared by whole-document and page-level result caches."""
    from backend.config.settings import settings

    fields = (
        "ai_client", "ollama_model", "ollama_base_url", "openrouter_model",
        "openrouter_base_url", "openrouter_max_tokens", "pipeline_engine", "structurer",
        "fusion_mode", "fusion_secondary_provider", "fusion_hybrid_provider",
        "toolbox_base_url", "toolbox_provider", "toolbox_layout_provider",
        "toolbox_pdf_provider", "toolbox_math_recognize_provider", "toolbox_math_provider",
        "toolbox_ocr_provider", "toolbox_page_ocr_provider", "toolbox_adjudicate_provider",
        "toolbox_orientation_provider", "toolbox_media_inspect_provider",
        "toolbox_media_inspect_enabled", "pdf_split_dpi", "jpg_quality", "callout_known_titles",
    )
    return {name: getattr(settings, name) for name in fields}


def options_cache_key(prefix: str, **options: Any) -> str:
    """Build a filesystem-safe cache variant from output-affecting options."""
    serialized = json.dumps(
        options,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


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
        logger.debug(t(LOG_CACHE_DEBUG_HIT).format(key=key))
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
        logger.debug(t(LOG_CACHE_DEBUG_SET).format(key=key))
    except Exception as e:
        logger.warning(t(LOG_CACHE_SAVE_FAILED).format(error=e))


async def clear_cache() -> int:
    _ensure_cache_dir()
    count = 0
    for f in CACHE_DIR.iterdir():
        if f.suffix == ".json":
            await aiofiles.os.remove(str(f))
            count += 1
    logger.info(t(LOG_CACHE_CLEARED).format(count=count))
    return count
