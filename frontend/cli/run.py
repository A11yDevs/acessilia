#!/usr/bin/env python3
"""Console entry point for the shared interface runner."""
import os

from frontend import run as runtime
from frontend.run import _is_process_running, startup  # noqa: F401

LOCK_FILE = os.path.join(os.path.dirname(__file__), "bot.lock")


def acquire_lock() -> None:
    runtime.acquire_lock(LOCK_FILE)


def release_lock() -> None:
    runtime.release_lock(LOCK_FILE)


def main():
    runtime.main(lock_file=LOCK_FILE)


if __name__ == "__main__":
    main()
