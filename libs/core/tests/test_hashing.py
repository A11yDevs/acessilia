"""The core's file digest helper."""

from __future__ import annotations

import hashlib

import pytest

from acessilia_core.hashing import file_sha256


@pytest.mark.parametrize("content", [b"", b"a", b"x" * (2 * 1024 * 1024)])
def test_file_sha256_hashes_the_exact_bytes(tmp_path, content: bytes) -> None:
    path = tmp_path / "payload.bin"
    path.write_bytes(content)

    assert file_sha256(path) == hashlib.sha256(content).hexdigest()


def test_file_sha256_accepts_a_string_path(tmp_path) -> None:
    path = tmp_path / "payload.bin"
    path.write_bytes(b"content")

    assert file_sha256(str(path)) == hashlib.sha256(b"content").hexdigest()


def test_file_sha256_propagates_a_missing_file(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        file_sha256(tmp_path / "missing.bin")
