"""Coordinate publication and age-based deletion across cache processes."""

import fcntl
import os
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def cache_directory_lock(directory: Path):
    # Lock the directory inode itself: no lock file that a sweep can unlink
    # and recreate, splitting workers across different locks.
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)
