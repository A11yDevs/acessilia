from __future__ import annotations

import argparse
import re
from pathlib import Path


ACCELERATOR_PACKAGES = {"torch", "torchvision", "triton"}
REQUIREMENT_NAME = re.compile(r"^([A-Za-z0-9_.-]+)")


def normalized_requirement_name(line: str) -> str | None:
    candidate = line.strip()
    if not candidate or candidate.startswith(("#", "-")):
        return None
    match = REQUIREMENT_NAME.match(candidate)
    if match is None:
        return None
    return match.group(1).lower().replace("_", "-").replace(".", "-")


def filter_requirements(content: str) -> str:
    kept_lines = []
    for line in content.splitlines():
        package_name = normalized_requirement_name(line)
        if package_name in ACCELERATOR_PACKAGES:
            continue
        if package_name is not None and package_name.startswith("nvidia-"):
            continue
        kept_lines.append(line)
    return "\n".join(kept_lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Remove GPU and replaceable Torch packages from requirements."
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(
        filter_requirements(args.input.read_text(encoding="utf-8")),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()