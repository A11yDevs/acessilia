from __future__ import annotations

import argparse
import json
import re
import subprocess
from typing import Any


UNITS = {
    "B": 1,
    "KB": 1_000,
    "MB": 1_000_000,
    "GB": 1_000_000_000,
    "TB": 1_000_000_000_000,
}


def parse_docker_size(value: str) -> int:
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([kKMGT]?B)", value.strip())
    if match is None:
        raise ValueError(f"Docker size is invalid: {value!r}")
    return round(float(match.group(1)) * UNITS[match.group(2).upper()])


def docker(*args: str) -> str:
    return subprocess.check_output(["docker", *args], text=True).strip()


def inspect_local(image: str) -> tuple[int, int]:
    total = int(docker("image", "inspect", image, "--format", "{{.Size}}"))
    history = docker("history", image, "--no-trunc", "--format", "{{.Size}}")
    largest_layer = max(
        (parse_docker_size(line) for line in history.splitlines()), default=0
    )
    return total, largest_layer


def _manifest(image: str) -> dict[str, Any]:
    return json.loads(docker("buildx", "imagetools", "inspect", image, "--raw"))


def inspect_remote(image: str) -> tuple[int, int]:
    manifest = _manifest(image)
    if "layers" not in manifest:
        candidates = [
            item
            for item in manifest.get("manifests", [])
            if item.get("platform", {}).get("os") == "linux"
            and item.get("platform", {}).get("architecture") == "amd64"
        ]
        if not candidates:
            raise RuntimeError("linux/amd64 manifest not found")
        manifest = _manifest(f"{image.split('@', 1)[0]}@{candidates[0]['digest']}")
    layer_sizes = [int(layer["size"]) for layer in manifest.get("layers", [])]
    return sum(layer_sizes), max(layer_sizes, default=0)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("local", "remote"))
    parser.add_argument("image")
    parser.add_argument("--limit-gb", type=float, default=9.0)
    args = parser.parse_args()

    inspect = inspect_local if args.mode == "local" else inspect_remote
    total, largest_layer = inspect(args.image)
    limit = round(args.limit_gb * 1_000_000_000)
    print(f"image={args.image}")
    print(f"total_bytes={total}")
    print(f"total_gb={total / 1_000_000_000:.2f}")
    print(f"largest_layer_bytes={largest_layer}")
    print(f"largest_layer_gb={largest_layer / 1_000_000_000:.2f}")
    if total > limit or largest_layer > limit:
        raise SystemExit(
            f"Image exceeds {args.limit_gb:g} GB guardrail: "
            f"total={total}, largest_layer={largest_layer}"
        )


if __name__ == "__main__":
    main()