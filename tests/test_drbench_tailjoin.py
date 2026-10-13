"""Tests for the position-conditioned tail-join (tj3) in the Dr.DocBench pipeline.

Ground truth keeps the running header before a BOTTOM page number in 91% of dev
pages, but is ~70/30 when the number sits at the top. ``tailjoin3`` therefore joins
the short trailing blocks only when the page number is not known to be at the
bottom; at the bottom, ``BOT=keep`` leaves the tail alone and ``BOT=hdr`` moves the
number(s) last.

The script reads its arguments from ``sys.argv`` at import time, so it is exercised
as a subprocess.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "drbench" / "experiments" / "pages" / "tailjoin3.py"

pytestmark = pytest.mark.skipif(
    not SCRIPT.exists(), reason="tailjoin3.py not present"
)


def run_tailjoin(tmp_path: Path, pages: dict[str, str], positions: dict[str, str],
                 maxlen: int = 50, k: int = 3, bot: str = "keep") -> dict[str, str]:
    src = tmp_path / "src"
    out = tmp_path / "out"
    src.mkdir()
    for name, content in pages.items():
        (src / name).write_text(content, encoding="utf-8")
    pos = tmp_path / "pos.json"
    pos.write_text(json.dumps(positions), encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), str(src), str(out), str(pos), str(maxlen), str(k), bot],
        capture_output=True, text=True,
    )
    assert completed.returncode == 0, completed.stderr
    return {p.name: p.read_text(encoding="utf-8") for p in out.glob("*.drbench.md")}


class TestTailJoin:
    def test_top_page_number_joins_the_tail(self, tmp_path):
        page = "body text here\n\n\n\n\nRUNNING HEAD\n\n\n\n\n42\n"
        result = run_tailjoin(tmp_path, {"doc_p1.drbench.md": page}, {"doc_p1": "top"})
        content = result["doc_p1.drbench.md"]
        assert "RUNNING HEAD 42" in content

    def test_bottom_page_number_keeps_the_tail_with_bot_keep(self, tmp_path):
        page = "body text here\n\n\n\n\nRUNNING HEAD\n\n\n\n\n42\n"
        result = run_tailjoin(tmp_path, {"doc_p1.drbench.md": page}, {"doc_p1": "bot"}, bot="keep")
        content = result["doc_p1.drbench.md"]
        assert "RUNNING HEAD 42" not in content
        assert "RUNNING HEAD" in content

    def test_bottom_page_number_moves_number_last_with_bot_hdr(self, tmp_path):
        page = "body text here\n\n\n\n\n42\n\n\n\n\nRUNNING HEAD\n"
        result = run_tailjoin(tmp_path, {"doc_p1.drbench.md": page}, {"doc_p1": "bot"}, bot="hdr")
        content = result["doc_p1.drbench.md"]
        assert content.index("RUNNING HEAD") < content.index("42")

    def test_unknown_position_joins_like_top(self, tmp_path):
        page = "body text here\n\n\n\n\nRUNNING HEAD\n\n\n\n\n42\n"
        result = run_tailjoin(tmp_path, {"doc_p1.drbench.md": page}, {})
        assert "RUNNING HEAD 42" in result["doc_p1.drbench.md"]

    def test_tail_without_a_page_number_is_untouched(self, tmp_path):
        page = "body text here\n\n\n\n\nRUNNING HEAD\n\n\n\n\nANOTHER LINE\n"
        result = run_tailjoin(tmp_path, {"doc_p1.drbench.md": page}, {"doc_p1": "top"})
        content = result["doc_p1.drbench.md"]
        assert "RUNNING HEAD ANOTHER LINE" not in content

    def test_single_trailing_block_is_not_joined(self, tmp_path):
        page = "body text here\n\n\n\n\n42\n"
        result = run_tailjoin(tmp_path, {"doc_p1.drbench.md": page}, {"doc_p1": "top"})
        assert "42" in result["doc_p1.drbench.md"]

    def test_long_trailing_block_is_not_part_of_the_tail(self, tmp_path):
        long_block = "x" * 80
        page = f"body text here\n\n\n\n\n{long_block}\n\n\n\n\n42\n"
        result = run_tailjoin(tmp_path, {"doc_p1.drbench.md": page}, {"doc_p1": "top"}, maxlen=50)
        assert long_block in result["doc_p1.drbench.md"]

    def test_roman_numeral_page_number_is_recognised(self, tmp_path):
        page = "body text here\n\n\n\n\nRUNNING HEAD\n\n\n\n\nxii\n"
        result = run_tailjoin(tmp_path, {"doc_p1.drbench.md": page}, {"doc_p1": "top"})
        assert "RUNNING HEAD xii" in result["doc_p1.drbench.md"]

    def test_body_only_page_is_unchanged(self, tmp_path):
        page = "only body text\n"
        result = run_tailjoin(tmp_path, {"doc_p1.drbench.md": page}, {"doc_p1": "top"})
        assert result["doc_p1.drbench.md"].strip() == "only body text"
