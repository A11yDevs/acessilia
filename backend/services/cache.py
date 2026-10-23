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


def _content_key(content: bytes, extra: str = "") -> str:
    """Cache key for bytes held in memory, hashed instead of read from a path."""
    return f"{hashlib.sha256(content).hexdigest()}_{len(content)}_{extra}"


def _cache_path(key: str) -> Path:
    return CACHE_DIR / f"{key}.json"


def processing_cache_configuration() -> dict[str, Any]:
    """Configuration shared by whole-document and page-level result caches."""
    from backend.config.settings import settings

    fields = (
        "ai_client", "ollama_model", "ollama_base_url", "openrouter_model",
        "openrouter_base_url", "openrouter_max_tokens", "pipeline_engine",
        "fusion_mode", "fusion_secondary_provider", "fusion_hybrid_provider",
        "toolbox_base_url", "toolbox_base_urls", "toolbox_provider", "toolbox_layout_provider",
        "toolbox_pdf_provider", "toolbox_math_recognize_provider", "toolbox_math_provider",
        "toolbox_ocr_provider", "toolbox_page_ocr_provider", "toolbox_adjudicate_provider",
        "toolbox_orientation_provider", "toolbox_media_inspect_provider",
        "toolbox_media_inspect_enabled", "slide_visual_coverage", "pdf_split_dpi",
        "pddl_execute_dry_run", "pddl_max_replans", "pddl_planner_backend",
        "pddl_preferred_plan", "pddl_fast_downward", "pddl_fast_downward_alias",
        "pddl_fast_downward_search",
    )
    configuration = {name: getattr(settings, name) for name in fields}
    from backend.core.planning.domain_bundle import DomainBundle

    domain = DomainBundle.load()
    configuration["pddl_domain"] = (domain.domain_sha256, domain.description_sha256)
    return configuration


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
    return await _read_cached(_cache_key(path, extra), ttl)


async def get_cached_bytes(content: bytes, extra: str = "", ttl: int = 3600) -> Any:
    """Cached payload for binary content held in memory, keyed on its SHA-256.

    Mirrors :func:`get_cached` for callers that never materialize the content
    as a file (a cropped region image), so identical content across pages or
    reruns reuses the stored answer.
    """
    return await _read_cached(_content_key(content, extra), ttl)


async def _read_cached(key: str, ttl: int) -> Any:
    _ensure_cache_dir()
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
    await _write_cached(_cache_key(path, extra), payload)


async def set_cache_bytes(content: bytes, payload: Any, extra: str = "") -> None:
    """Store a payload for binary content held in memory; see :func:`get_cached_bytes`."""
    await _write_cached(_content_key(content, extra), payload)


async def _write_cached(key: str, payload: Any) -> None:
    _ensure_cache_dir()
    cp = _cache_path(key)
    tmp = Path(str(cp) + ".tmp")
    try:
        data = {"timestamp": time.time(), "payload": payload}
        if isinstance(payload, str):
            data["text"] = payload
        async with aiofiles.open(str(tmp), "w", encoding="utf-8") as f:
            await f.write(json.dumps(data, ensure_ascii=False))
        # The rename makes the write atomic for concurrent readers: they see
        # either the previous complete file or this one, never a half-written
        # JSON that a parallel reader would parse-fail and delete. A process
        # killed mid-write leaves only the temporary file behind, which the
        # periodic cache sweep removes by age.
        await aiofiles.os.replace(str(tmp), str(cp))
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
