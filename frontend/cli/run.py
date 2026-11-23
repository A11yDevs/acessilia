#!/usr/bin/env python3
"""Console-script entry point for the shared frontend runtime.

The runtime lives in :mod:`frontend.run`. Both entry points intentionally reuse
it so they start the same interfaces and share the same process lock.
"""

from __future__ import annotations

from frontend.run import main

__all__ = ["main"]


if __name__ == "__main__":
    main()
