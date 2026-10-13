#!/usr/bin/env python
"""Fail-safe for the cluster rule "use only the GPUs Slurm gave this job".

Slurm only *tells* programs which GPU is theirs (CUDA_VISIBLE_DEVICES); on this
cluster the other GPUs stay visible in the node, and Vulkan-based code (ollama's
Vulkan discovery, SAPIEN rendering) ignores that variable. This audit looks at
``nvidia-smi pmon`` and reports every process of THIS job's process tree that
holds a GPU outside the allocation.

  gpu_audit.py                        # one sample; print violations, exit 1 if any
  gpu_audit.py --watch 20 --kill      # loop; SIGTERM the offending processes
"""

import argparse
import os
import signal
import subprocess
import sys
import time
from typing import Dict, Iterable, List, Set, Tuple


def allowed_gpus(env=os.environ) -> Set[int]:
    """GPU indices of the allocation (CUDA_VISIBLE_DEVICES, else SLURM_JOB_GPUS)."""
    raw = env.get("CUDA_VISIBLE_DEVICES") or env.get("SLURM_JOB_GPUS") or ""
    return {int(x) for x in raw.split(",") if x.strip().lstrip("-").isdigit() and int(x) >= 0}


def parse_pmon(text: str) -> List[Tuple[int, int, str, str]]:
    """``nvidia-smi pmon`` rows -> (gpu_index, pid, type, command)."""
    rows = []
    for line in text.splitlines():
        parts = line.split()
        if not parts or parts[0].startswith("#") or len(parts) < 3:
            continue
        if parts[0].isdigit() and parts[1].isdigit():
            rows.append((int(parts[0]), int(parts[1]), parts[2], parts[-1]))
    return rows


def children_map() -> Dict[int, List[int]]:
    out: Dict[int, List[int]] = {}
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            with open(f"/proc/{name}/stat") as f:
                ppid = int(f.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            continue
        out.setdefault(ppid, []).append(int(name))
    return out


def tree(root: int, children: Dict[int, List[int]]) -> Set[int]:
    seen, stack = set(), [root]
    while stack:
        pid = stack.pop()
        if pid not in seen:
            seen.add(pid)
            stack.extend(children.get(pid, []))
    return seen


def violations(rows, mine: Iterable[int], allowed: Set[int]):
    mine = set(mine)
    return [r for r in rows if r[1] in mine and r[0] not in allowed]


def sample(root: int, allowed: Set[int]):
    text = subprocess.run(
        ["nvidia-smi", "pmon", "-c", "1"], capture_output=True, text=True, timeout=30
    ).stdout
    return violations(parse_pmon(text), tree(root, children_map()), allowed)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=int, default=os.getppid(), help="root pid of the job tree")
    ap.add_argument("--watch", type=int, default=0, help="seconds between samples (0 = once)")
    ap.add_argument("--kill", action="store_true", help="SIGTERM offending processes")
    a = ap.parse_args()
    allowed = allowed_gpus()
    if not allowed and os.environ.get("SLURM_JOB_ID"):
        print("gpu_audit: no GPU allocation visible in this job", flush=True)
    bad_total = 0
    while True:
        for gpu, pid, kind, cmd in sample(a.root, allowed):
            bad_total += 1
            print(
                f"gpu_audit: VIOLATION pid={pid} ({cmd}, {kind}) on GPU {gpu}; allowed={sorted(allowed)}",
                flush=True,
            )
            if a.kill:
                try:
                    os.kill(pid, signal.SIGTERM)
                except OSError:
                    pass
        if not a.watch:
            return 1 if bad_total else 0
        time.sleep(a.watch)


if __name__ == "__main__":
    sys.exit(main())
