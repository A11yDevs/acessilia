import asyncio
import hashlib
import json
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import aiofiles
import aiofiles.os

from acessilia_core.config import CoreConfig
from acessilia_core.i18n import t
from acessilia_core.i18n.log_messages import (
    LOG_CACHE_CLEARED,
    LOG_CACHE_DEBUG_HIT,
    LOG_CACHE_DEBUG_SET,
    LOG_CACHE_SAVE_FAILED,
)
from acessilia_core.logger import logger
from backend.services.cache_lock import cache_directory_lock

CACHE_DIR = Path("var/temp/cache")
# Match the periodic sweep's retention; fresh temporaries may belong to
# another process. Track this process's writers regardless of file age.
CACHE_TEMP_MAX_AGE_SECONDS = 7 * 24 * 60 * 60

#: Bump when ``document_invariant_findings`` starts rejecting manifests that
#: were accepted and cached under the previous rules. It is part of the
#: processing-cache identity, so old entries are not reopened and rejected.
MANIFEST_INVARIANT_REVISION = "2026-11-14"
_active_cache_writes: set[Path] = set()


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


#: Service options a processed document depends on, outside the core's
#: ``CoreConfig``: the engine, the planner and the model revision.
SERVICE_PROCESSING_SETTINGS = (
    "pipeline_engine", "fusion_hybrid_provider", "processing_model_revision",
    "pddl_execute_dry_run", "pddl_max_replans", "pddl_planner_backend",
    "pddl_preferred_plan", "pddl_fast_downward", "pddl_fast_downward_alias",
    "pddl_fast_downward_search",
)


def processing_cache_configuration(config: CoreConfig) -> dict[str, Any]:
    """What a processed document depends on: the run's ``config`` (#544) and
    the service's own options, with the manifest rules and the PDDL domain."""
    from acessilia_core.run_identity import processing_identity
    from backend.config.settings import settings

    configuration: dict[str, Any] = {"core": processing_identity(config)}
    configuration.update({name: getattr(settings, name) for name in SERVICE_PROCESSING_SETTINGS})
    configuration["manifest_invariant_revision"] = MANIFEST_INVARIANT_REVISION
    from acessilia_core.planning.domain_bundle import DomainBundle

    domain = DomainBundle.load()
    configuration["pddl_domain"] = (domain.domain_sha256, domain.description_sha256)
    return configuration


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
    """Read a snapshot; leave removal to the periodic cleanup.

    A writer may replace the path after this reader captured its contents.
    Expired or corrupt snapshots are misses, never grounds to unlink a path
    that may already refer to a newer entry, including from another process.
    """
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
            return None
        logger.debug(t(LOG_CACHE_DEBUG_HIT).format(key=key))
        if "payload" in data:
            return data["payload"]
        return data.get("text")
    except Exception:
        return None


async def set_cache(path: Path, payload: Any, extra: str = "") -> None:
    await _write_cached(_cache_key(path, extra), payload)


async def drop_cache(path: Path, extra: str = "") -> None:
    """Remove the entry for ``path``, if any; a run that must not be cached supersedes it."""
    try:
        await aiofiles.os.remove(str(_cache_path(_cache_key(path, extra))))
    except OSError:
        # Nothing to drop, or it cannot be dropped: a refused entry is
        # refused again on read, so the run need not fail over it.
        pass


async def set_cache_bytes(content: bytes, payload: Any, extra: str = "") -> None:
    """Store a payload for binary content held in memory; see :func:`get_cached_bytes`."""
    await _write_cached(_content_key(content, extra), payload)


class ContentCache:
    """The core's ``RegionCache`` port over this cache (ADR-0016, step 4):
    a region image's answers, keyed on its bytes and the core's variant."""

    async def get(self, content: bytes, variant: str, *, ttl_seconds: int) -> Any | None:
        return await get_cached_bytes(content, extra=variant, ttl=ttl_seconds)

    async def put(self, content: bytes, variant: str, payload: Any) -> None:
        await set_cache_bytes(content, payload, extra=variant)


async def _write_cached(key: str, payload: Any) -> None:
    _ensure_cache_dir()
    cp = _cache_path(key)
    tmp = CACHE_DIR / f".cache-{uuid4().hex}.tmp"
    temporary_created = False
    active_path = tmp.resolve()
    _active_cache_writes.add(active_path)
    try:
        data = {"timestamp": time.time(), "payload": payload}
        if isinstance(payload, str):
            data["text"] = payload
        async with aiofiles.open(str(tmp), "x", encoding="utf-8") as f:
            temporary_created = True
            await f.write(json.dumps(data, ensure_ascii=False))
        # Each writer owns a separate temporary file in the same directory.
        # Replacing the entry publishes one complete JSON even when another
        # writer is saving the same key. A process killed mid-write leaves
        # only its temporary file, which the periodic sweep removes by age.
        await _replace_cached(tmp, cp)
        logger.debug(t(LOG_CACHE_DEBUG_SET).format(key=key))
    except Exception as e:
        logger.warning(t(LOG_CACHE_SAVE_FAILED).format(error=e))
    finally:
        try:
            if temporary_created:
                try:
                    await aiofiles.os.remove(str(tmp))
                except FileNotFoundError:
                    pass
                except OSError as e:
                    logger.warning(t(LOG_CACHE_SAVE_FAILED).format(error=e))
        finally:
            _active_cache_writes.discard(active_path)


def _publish_cache(source: Path, destination: Path) -> None:
    import os

    with cache_directory_lock(destination.parent):
        os.replace(source, destination)


async def _replace_cached(source: Path, destination: Path) -> None:
    # Acquire the process-shared lock off the event loop. Keep acquisition,
    # replacement and release in one worker even if the caller is cancelled.
    await asyncio.to_thread(_publish_cache, source, destination)


async def clear_cache() -> int:
    """Remove published entries and stale temporaries, preserving active writes."""
    _ensure_cache_dir()
    count = 0
    now = time.time()
    for f in CACHE_DIR.iterdir():
        if f.resolve() in _active_cache_writes:
            continue
        try:
            if not f.is_file():
                continue
            stale_temporary = (
                f.suffix == ".tmp"
                and now - f.stat().st_mtime > CACHE_TEMP_MAX_AGE_SECONDS
            )
            if f.suffix == ".json" or stale_temporary:
                await aiofiles.os.remove(str(f))
                count += 1
        except FileNotFoundError:
            # A writer or periodic sweep may have already replaced/removed it.
            continue
    logger.info(t(LOG_CACHE_CLEARED).format(count=count))
    return count
