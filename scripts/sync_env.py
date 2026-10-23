"""Bring a local ``.env`` up to date with ``.env.example``.

``.env`` is not versioned, so keys added to ``.env.example`` after someone
created theirs never reach it, and keys removed from the code linger there
unnoticed. This script compares the two files:

* keys declared in ``.env.example`` but absent from ``.env`` are appended to
  ``.env`` with the example's value and the comment that documents them
  (a key commented out in the example, such as ``#LOCALE=pt_BR``, is copied
  commented out). Existing lines are never changed; ``.env`` is created from
  the example when it does not exist;
* keys set in ``.env`` but absent from ``.env.example`` are reported. Each one
  is looked up in the versioned files (``git grep``, leaving out docs, tests and
  the example itself): a key nothing references is probably deprecated, while a
  referenced one is still read somewhere (compose files, server scripts, legacy
  aliases) and is listed with the files that mention it.

A key commented out in ``.env`` (``#KEY=``, no space after the ``#``) counts as
present, so a value someone chose to disable is not added again.

The staging and production scripts ``source`` ``.env`` in bash with ``set -e``,
so an unquoted value with spaces or shell characters (``SMTP_NAME=A11y
Acessibilidade``, ``astar(blind())``) stops the auto-update timer. Such values
are reported for quoting; compose and dotenv strip the quotes.

Usage:
    python scripts/sync_env.py            # appends the missing keys and reports
    python scripts/sync_env.py --check    # changes nothing; exit 1 if keys are missing
    python scripts/sync_env.py --env /opt/acessilia/.env --example .env.example

Exit status is 0, or 1 when ``--check`` finds missing keys or values that need
quoting.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: ``KEY=value``, optionally preceded by ``export`` or commented out (``#KEY=``).
#: The key must directly follow the ``#``, so prose such as
#: ``# use FOO=bar to ...`` or ``# FOO=bar enables ...`` is not taken for a key.
_ASSIGNMENT = re.compile(
    r"^\s*(?P<comment>#)?(?:export\s+)?(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*="
)

#: Paths left out of the reference search: mentioning a key there does not
#: mean the application still reads it.
_SEARCH_EXCLUDES = (":!.env.example", ":!*.md", ":!docs/", ":!tests/")


@dataclass
class Group:
    """Consecutive assignments of an env file and the comment above them."""

    comment: list[str] = field(default_factory=list)
    #: (key, raw line, commented out)
    entries: list[tuple[str, str, bool]] = field(default_factory=list)


def parse_groups(text: str) -> list[Group]:
    """Split an env file into groups of assignments with their comments.

    A comment block documents every assignment that follows it up to the next
    blank line or comment, which is how ``.env.example`` documents related keys
    (e.g. the three VLM providers under one comment).
    """
    groups: list[Group] = []
    pending: list[str] = []
    current: Group | None = None
    for line in text.splitlines():
        match = _ASSIGNMENT.match(line)
        if match:
            if current is None:
                current = Group(comment=pending)
                groups.append(current)
                pending = []
            current.entries.append(
                (match.group("key"), line, match.group("comment") is not None)
            )
        elif line.strip().startswith("#"):
            current = None
            pending.append(line)
        else:
            current = None
            pending = []
    return groups


def declared_keys(text: str) -> dict[str, bool]:
    """Map each key of an env file to whether it is set (not commented out).

    A key both set and commented out counts as set.
    """
    keys: dict[str, bool] = {}
    for group in parse_groups(text):
        for key, _, commented in group.entries:
            keys[key] = keys.get(key, False) or not commented
    return keys


def duplicated_keys(text: str) -> list[str]:
    """Keys set more than once; the last value wins, which hides the others."""
    seen: set[str] = set()
    duplicates: list[str] = []
    for group in parse_groups(text):
        for key, _, commented in group.entries:
            if commented:
                continue
            if key in seen and key not in duplicates:
                duplicates.append(key)
            seen.add(key)
    return duplicates


#: Characters bash treats specially in an unquoted assignment value.
_SHELL_SPECIAL = re.compile(r"[\s()&;|<>`]")


def shell_unsafe_keys(text: str) -> list[str]:
    """Set keys whose unquoted value bash cannot ``source`` as a plain assignment.

    A value fully wrapped in single or double quotes is safe, and so is a
    trailing `` # comment``, which bash ignores.
    """
    unsafe: list[str] = []
    for line in text.splitlines():
        match = _ASSIGNMENT.match(line)
        if not match or match.group("comment") is not None:
            continue
        value = line[match.end():].strip()
        if value[:1] in {"'", '"'} and len(value) > 1 and value[-1] == value[0]:
            continue
        value = re.split(r"\s+#", value, maxsplit=1)[0]
        if _SHELL_SPECIAL.search(value) and match.group("key") not in unsafe:
            unsafe.append(match.group("key"))
    return unsafe


def missing_block(example_text: str, env_keys: dict[str, bool]) -> tuple[list[str], str]:
    """Keys of the example absent from ``.env`` and the text that adds them."""
    missing: list[str] = []
    chunks: list[str] = []
    for group in parse_groups(example_text):
        lines = [line for key, line, _ in group.entries if key not in env_keys]
        if not lines:
            continue
        missing.extend(key for key, _, _ in group.entries if key not in env_keys)
        chunks.append("\n".join([*group.comment, *lines]))
    return missing, "\n\n".join(chunks)


def references(key: str, root: Path) -> list[str] | None:
    """Versioned files that mention ``key``, or None when git is unavailable."""
    try:
        result = subprocess.run(
            ["git", "grep", "-l", "-w", "-F", "-e", key, "--", ".", *_SEARCH_EXCLUDES],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    # git grep exits 1 when nothing matches and >1 on errors (e.g. not a repo).
    if result.returncode > 1:
        return None
    return result.stdout.split()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env", type=Path, default=REPO_ROOT / ".env")
    parser.add_argument("--example", type=Path, default=REPO_ROOT / ".env.example")
    parser.add_argument(
        "--check",
        action="store_true",
        help="change nothing; exit 1 if keys are missing",
    )
    args = parser.parse_args(argv)

    example_text = args.example.read_text(encoding="utf-8")
    if not args.env.exists():
        if args.check:
            print(f"{args.env} does not exist.")
            return 1
        shutil.copyfile(args.example, args.env)
        print(f"{args.env} did not exist; created from {args.example}.")
        print("Replace the example values (tokens, passwords, URLs) before use.")
        return 0

    env_text = args.env.read_text(encoding="utf-8")
    env_keys = declared_keys(env_text)
    example_keys = declared_keys(example_text)
    missing, block = missing_block(example_text, env_keys)

    if missing:
        verb = "Missing" if args.check else "Added"
        print(f"{verb} {len(missing)} key(s) of {args.example.name} in {args.env.name}:")
        for key in missing:
            print(f"  + {key}" + ("" if example_keys[key] else " (commented out)"))
        if not args.check:
            separator = "" if env_text.endswith("\n") or not env_text else "\n"
            today = datetime.now().astimezone()
            header = (
                f"# --- Added by scripts/sync_env.py on {today:%Y-%m-%d} "
                f"from {args.example.name}; review the values ---"
            )
            with args.env.open("a", encoding="utf-8") as handle:
                handle.write(f"{separator}\n{header}\n{block}\n")
    else:
        print(f"No key of {args.example.name} is missing from {args.env.name}.")

    extras = [key for key, is_set in env_keys.items() if is_set and key not in example_keys]
    if extras:
        root = args.example.resolve().parent
        unused: list[str] = []
        referenced: list[tuple[str, list[str]]] = []
        unknown: list[str] = []
        for key in extras:
            files = references(key, root)
            if files is None:
                unknown.append(key)
            elif files:
                referenced.append((key, files))
            else:
                unused.append(key)
        print()
        print(f"Keys of {args.env.name} not in {args.example.name}:")
        if unused:
            print("  Probably deprecated (no versioned file references them):")
            for key in unused:
                print(f"    - {key}")
        if referenced:
            print("  Still referenced (compose files, server scripts or legacy aliases):")
            for key, files in referenced:
                shown = ", ".join(files[:3]) + (", ..." if len(files) > 3 else "")
                print(f"    - {key}: {shown}")
        if unknown:
            print("  Not checked (git unavailable):")
            for key in unknown:
                print(f"    - {key}")

    duplicates = duplicated_keys(env_text)
    if duplicates:
        print()
        print(f"Keys set more than once in {args.env.name} (the last one wins):")
        for key in duplicates:
            print(f"  ! {key}")

    unsafe = shell_unsafe_keys(env_text)
    if unsafe:
        print()
        print(
            f"Values in {args.env.name} that bash cannot source unquoted; the server "
            "scripts fail on them, so wrap each value in quotes (KEY='value'):"
        )
        for key in unsafe:
            print(f"  ! {key}")

    return 1 if args.check and (missing or unsafe) else 0


if __name__ == "__main__":
    sys.exit(main())
