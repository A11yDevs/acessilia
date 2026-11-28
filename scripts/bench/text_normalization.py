"""Qualify #929 over real HTTP; local Docstruct is only the historical oracle.

Run against an isolated Toolbox with filesystem storage and, optionally, Redis.
The reference handler is compiled unchanged from an immutable Core commit.
Synthetic latency is explicit; figures are local evidence, not production claims.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import json
import math
import platform
import resource
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "libs/core/tests"))

from core_config_support import core_config  # noqa: E402
from pddl_support import build_element, build_manifest, build_obligation  # noqa: E402

from acessilia_core.execution.models import MethodResult  # noqa: E402
from acessilia_core.i18n import n, t  # noqa: E402
from acessilia_core.logger import logger  # noqa: E402
from acessilia_core.manifest.models import ProcessingManifest  # noqa: E402
from acessilia_core.pipeline.handlers.common import (  # noqa: E402
    _missing_obligation,
    _target_elements,
)
from acessilia_core.pipeline.handlers.messages import (  # noqa: E402
    MSG_NORMALIZE_APPLIED,
    MSG_NORMALIZE_NO_TEXT,
)
from acessilia_core.pipeline.handlers.text_normalization import _handle_norm_fix_method  # noqa: E402
from acessilia_core.ports import PHASE_EXECUTION, RunPorts  # noqa: E402
from acessilia_sdk.toolbox.text_normalization import MAX_PAYLOAD_BYTES  # noqa: E402
from docstruct.text.norm_fix import norm_fix  # noqa: E402


class Interrupted(BaseException):
    """A controlled interruption after the first successful batch, before the second."""


class Wire:
    def __init__(self, delay_ms):
        self.delay_ms = delay_ms
        self.records = []
        self.capture = False
        self.interrupt_at = None
        self.lock = threading.Lock()
        self.original = httpx.AsyncClient.send

    async def send(self, client, request, *args, **kwargs):
        await request.aread()
        record = {
            "request_body_bytes": len(request.content),
            "operation_id": request.headers.get("X-Acessilia-Operation-Id"),
        }
        with self.lock:
            self.records.append(record)
            number = len(self.records)
        if number == self.interrupt_at:
            raise Interrupted()
        if self.delay_ms:
            await asyncio.sleep(self.delay_ms / 1000)
        response = await self.original(client, request, *args, **kwargs)
        await response.aread()
        body = response.json()
        record.update(
            response_body_bytes=len(response.content),
            status=response.status_code,
            cache_hit=body.get("provenance", {}).get("cache_hit", False),
        )
        if self.capture:
            record["envelope"] = body
        return response


def historical_handler(ref):
    source = subprocess.check_output(
        [
            "git",
            "show",
            f"{ref}:libs/core/src/acessilia_core/pipeline/handlers/text.py",
        ],
        cwd=ROOT,
        text=True,
    )
    handler = next(
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name == "_handle_norm_fix_method"
    )
    namespace = {
        "ProcessingManifest": ProcessingManifest,
        "MethodResult": MethodResult,
        "n": n,
        "t": t,
        "norm_fix": norm_fix,
        "_target_elements": _target_elements,
        "_missing_obligation": _missing_obligation,
        "MSG_NORMALIZE_APPLIED": MSG_NORMALIZE_APPLIED,
        "MSG_NORMALIZE_NO_TEXT": MSG_NORMALIZE_NO_TEXT,
    }
    exec(
        compile(
            ast.Module(body=[handler], type_ignores=[]), f"{ref}:legacy-handler", "exec"
        ),
        namespace,
    )
    return namespace["_handle_norm_fix_method"]


def manifest_for(texts):
    elements = [
        build_element(
            f"e{i}",
            "paragraph",
            text=text,
            reading_order=i + 1,
            metadata={"keep": i, "norm_fixed": False},
        )
        for i, text in enumerate(texts)
    ]
    return build_manifest(
        elements,
        [build_obligation("normalize-text", [e.id for e in elements], ["norm-fix"])],
    )


def run_one(mode, texts, config, legacy):
    manifest = manifest_for(texts)
    expected = manifest.model_copy(deep=True)
    expected_result = legacy(expected, "o-1")
    started = time.perf_counter()
    if mode == "legacy":
        result = legacy(manifest, "o-1")
    elif mode == "individual":
        for element in manifest.elements:
            manifest.obligations[0].target_ids = [element.id]
            result = _handle_norm_fix_method(
                manifest, "o-1", config=config, ports=RunPorts.none()
            )
            assert result.success and result.validated, result.message
    else:
        result = _handle_norm_fix_method(
            manifest, "o-1", config=config, ports=RunPorts.none()
        )
        assert result == expected_result, (result, expected_result)
    elapsed = (time.perf_counter() - started) * 1000
    assert result.success and result.validated, result.message
    assert manifest.elements == expected.elements
    return elapsed


def process_sample(pid):
    if pid is None:
        return {}
    raw = subprocess.check_output(
        ["ps", "-p", str(pid), "-o", "time=,rss="], text=True
    ).split()
    seconds = 0.0
    for part in raw[0].split(":"):
        seconds = seconds * 60 + float(part)
    return {"cpu_ms": seconds * 1000, "rss_bytes": int(raw[1]) * 1024}


def profile(mode, texts, config, legacy, wire, args, *, concurrency=1):
    wire.records.clear()
    before = process_sample(args.server_pid)
    cpu = time.process_time()
    if concurrency == 1:
        latencies = [
            run_one(mode, texts, config, legacy) for _ in range(args.iterations)
        ]
    else:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            latencies = list(
                pool.map(
                    lambda _: run_one(mode, texts, config, legacy),
                    range(args.iterations * concurrency),
                )
            )
    cpu_ms = (time.process_time() - cpu) * 1000
    after = process_sample(args.server_pid)
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {
        "mode": mode,
        "concurrency": concurrency,
        "runs": len(latencies),
        "latency_median_ms": statistics.median(latencies),
        "latency_p95_ms": sorted(latencies)[math.ceil(len(latencies) * 0.95) - 1],
        "parent_cpu_ms_total": cpu_ms,
        "parent_process_lifetime_peak_rss_bytes": peak
        if sys.platform == "darwin"
        else peak * 1024,
        "server_cpu_ms_total": after.get("cpu_ms", 0) - before.get("cpu_ms", 0),
        "server_rss_after_bytes": after.get("rss_bytes"),
        "requests": len(wire.records),
        "request_body_bytes": sum(r["request_body_bytes"] for r in wire.records),
        "response_body_bytes": sum(
            r.get("response_body_bytes", 0) for r in wire.records
        ),
        "cache_hits": sum(r.get("cache_hit", False) for r in wire.records),
    }


def atomic_resume(config, legacy, wire):
    """Real SDK, server joins, SQLite operation journal and file checkpoint rehydration."""
    from backend.config.settings import settings
    from backend.services.job_checkpoint import FileJobCheckpoints
    from backend.services.operation_registry import JobOperations, OperationRegistry

    with (
        tempfile.TemporaryDirectory(prefix="norm-checkpoint-") as data,
        patch.object(settings, "data_dir", Path(data)),
    ):
        manifest = manifest_for(["a-\nb-\nc"] * 257)
        expected = manifest.model_copy(deep=True)
        legacy(expected, "o-1")
        checkpoints = FileJobCheckpoints("normalization-http-resume")
        checkpoints.save(
            PHASE_EXECUTION, {"manifest": manifest.model_dump(mode="json")}
        )
        registry = OperationRegistry()
        ports = replace(
            RunPorts.none(), operations=JobOperations(checkpoints.job_id, registry)
        )
        wire.records.clear()
        wire.capture, wire.interrupt_at = True, 2
        try:
            _handle_norm_fix_method(manifest, "o-1", config=config, ports=ports)
        except Interrupted:
            pass
        else:
            raise AssertionError("the second batch was not interrupted")
        assert all(
            e.text == "a-\nb-\nc" and not e.metadata["norm_fixed"]
            for e in manifest.elements
        )
        assert not registry.active(checkpoints.job_id)
        first = list(wire.records)
        restored = FileJobCheckpoints(checkpoints.job_id).load(PHASE_EXECUTION)
        resumed = ProcessingManifest.model_validate(restored["manifest"])
        ports = replace(
            RunPorts.none(),
            operations=JobOperations(checkpoints.job_id, OperationRegistry()),
        )
        wire.records.clear()
        wire.interrupt_at = None
        result = _handle_norm_fix_method(resumed, "o-1", config=config, ports=ports)
        assert result.success and resumed.elements == expected.elements
        assert [r["operation_id"] for r in wire.records] == [
            r["operation_id"] for r in first
        ]
        assert wire.records[0]["envelope"] == first[0]["envelope"]
        assert not wire.records[0]["cache_hit"], (
            "the original outcome must join with execution cache disabled"
        )
        wire.capture = False
        return {
            "atomic": True,
            "rehydrated": True,
            "journal_ids_stable": True,
            "first_batch_original_outcome_joined": True,
            "remote_execution_cache": False,
        }


def storage_sample(path):
    if path is None:
        return {}
    files = [p for p in path.rglob("*") if p.is_file()]
    return {"files": len(files), "bytes": sum(p.stat().st_size for p in files)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--api-key", default="normalization-benchmark")
    parser.add_argument("--legacy-ref", required=True)
    parser.add_argument("--server-pid", type=int)
    parser.add_argument("--storage-root", type=Path)
    parser.add_argument("--delay-ms", type=float, default=5)
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.iterations < 1 or args.delay_ms < 0:
        parser.error("iterations must be positive and delay nonnegative")
    logger.disable("acessilia_core")
    config = core_config()
    config = replace(
        config,
        toolbox=replace(
            config.toolbox,
            base_url=args.base_url,
            base_urls="",
            api_key=args.api_key,
            retries=0,
            use_remote_cache=False,
            timeout_seconds=30,
        ),
    )
    legacy, wire = historical_handler(args.legacy_ref), Wire(args.delay_ms)

    async def tracked(client, request, *a, **kw):
        return await wire.send(client, request, *a, **kw)

    scenarios = {"64-targets": [f"ﬁ  text\u00a0value {i}." for i in range(64)]}
    unit = "ﬁ  text\u00a0value. "
    scenarios["near-limit"] = [
        unit * ((MAX_PAYLOAD_BYTES - 1024) // len(unit.encode()))
    ]
    report = {
        "legacy_ref": args.legacy_ref,
        "platform": sys.platform,
        "python": platform.python_version(),
        "transport": "real HTTP; controlled local qualification",
        "synthetic_delay_per_request_ms": args.delay_ms,
        "notes": "Qualification-process CPU includes fixtures, parity/oracle checks and HTTP instrumentation; handler latency excludes the oracle; parent RSS is process-lifetime peak; server RSS is sampled after each phase, not peak. Filesystem/Redis are local, not production MinIO/Valkey.",
        "storage_before": storage_sample(args.storage_root),
        "scenarios": {},
    }
    with patch.object(httpx.AsyncClient, "send", tracked):
        for name, texts in scenarios.items():
            rows = [profile("legacy", texts, config, legacy, wire, args)]
            if name == "64-targets":
                rows.append(profile("individual", texts, config, legacy, wire, args))
            rows.append(profile("batch", texts, config, legacy, wire, args))
            cached = replace(
                config, toolbox=replace(config.toolbox, use_remote_cache=True)
            )
            run_one("batch", texts, cached, legacy)
            rows.append(profile("warm-cache", texts, cached, legacy, wire, args))
            if name == "64-targets":
                rows.append(
                    profile("batch", texts, config, legacy, wire, args, concurrency=4)
                )
            report["scenarios"][name] = rows
        report["checkpoint_resume"] = atomic_resume(config, legacy, wire)
    report["storage_after"] = storage_sample(args.storage_root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(args.out)


if __name__ == "__main__":
    main()
