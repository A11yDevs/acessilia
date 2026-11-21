"""Tests for pipeline comparison helpers (stateless logic only).

Full end-to-end comparison tests require the Toolbox to be running
and are covered by E2E tests (pytest -m e2e).
"""
from __future__ import annotations

import asyncio
import ast
import json
import sys
from pathlib import Path

import pytest

from scripts import compare_pipelines
from scripts.compare_pipelines import (
    _collect_inputs,
    _compare_documents,
    _compute_verdict,
    _count_by_type,
    _extract_formulas,
    _extract_tables,
    _extract_text,
    _flatten_blocks,
    _jaccard_similarity,
    _summarize_document,
    _tokenize,
    run_comparison,
)


def _make_canonical(title: str, blocks: list[dict], sections: list | None = None) -> dict:
    """Build a minimal canonical document for testing."""
    if sections is None:
        sections = [{"title": "root", "blocks": blocks, "children": []}]
    return {
        "title": title,
        "metadata": {"page_count": 1},
        "sections": sections,
    }


SAMPLE_BLOCKS = [
    {"type": "paragraph", "text": "Hello world"},
    {"type": "heading", "title": "Introduction", "text": "Introduction"},
    {"type": "list", "items": ["item A", "item B"]},
    {"type": "table", "rows": [["a", "b"], ["c", "d"]]},
    {"type": "formula", "text": "E = mc^2"},
    {"type": "image", "alt_text": "Chart"},
]


class TestFlattenBlocks:
    def test_flat_list(self):
        doc = _make_canonical("Test", SAMPLE_BLOCKS)
        result = _flatten_blocks(doc)
        assert len(result) == 6
        for block in result:
            assert "_section_path" in block

    def test_nested_sections(self):
        doc = _make_canonical("Nested", [], sections=[
            {"title": "Ch1", "blocks": [
                {"type": "paragraph", "text": "para 1"},
            ], "children": [
                {"title": "Ch1.1", "blocks": [
                    {"type": "paragraph", "text": "para 2"},
                ], "children": []},
            ]},
        ])
        result = _flatten_blocks(doc)
        assert len(result) == 2
        assert "Ch1" in result[0]["_section_path"]
        assert "Ch1.1" in result[1]["_section_path"]


class TestCountByType:
    def test_counts(self):
        result = _count_by_type(SAMPLE_BLOCKS)
        assert result == {
            "formula": 1,
            "heading": 1,
            "image": 1,
            "list": 1,
            "paragraph": 1,
            "table": 1,
        }

    def test_empty(self):
        assert _count_by_type([]) == {}


class TestExtractText:
    def test_extracts_all_text(self):
        doc = _make_canonical("T", [
            {"type": "paragraph", "text": "Hello"},
            {"type": "heading", "title": "Intro"},
            {"type": "list", "items": ["a", "b"]},
            {"type": "table", "rows": [["cell1", "cell2"]]},
            {"type": "image", "alt_text": "Chart img"},
        ])
        text = _extract_text(doc)
        assert "Hello" in text
        assert "Intro" in text
        assert "a" in text
        assert "b" in text
        assert "cell1" in text
        assert "Chart img" in text


class TestJaccardSimilarity:
    def test_identical(self):
        assert _jaccard_similarity("hello world", "hello world") == 1.0

    def test_partial(self):
        sim = _jaccard_similarity("hello world", "hello there")
        assert 0.3 < sim < 0.7

    def test_disjoint(self):
        assert _jaccard_similarity("abc", "xyz") == 0.0

    def test_both_empty(self):
        assert _jaccard_similarity("", "") == 1.0

    def test_case_insensitive(self):
        assert _jaccard_similarity("Hello World", "hello world") == 1.0


class TestTokenize:
    def test_basic(self):
        assert _tokenize("Hello World") == {"hello", "world"}

    def test_empty(self):
        assert _tokenize("") == set()


class TestExtractFormulas:
    def test_extracts_formula_blocks(self):
        doc = _make_canonical("F", [
            {"type": "formula", "text": "E = mc^2"},
            {"type": "paragraph", "text": "normal text"},
            {"type": "formula", "text": "F = ma"},
        ])
        result = _extract_formulas(doc)
        assert len(result) == 2
        assert "E = mc^2" in result
        assert "F = ma" in result

    def test_no_formulas(self):
        doc = _make_canonical("NF", [{"type": "paragraph", "text": "text"}])
        assert _extract_formulas(doc) == []


class TestExtractTables:
    def test_extracts_table_blocks(self):
        doc = _make_canonical("T", [
            {"type": "table", "rows": [["a", "b"]]},
            {"type": "paragraph", "text": "text"},
        ])
        assert len(_extract_tables(doc)) == 1

    def test_no_tables(self):
        doc = _make_canonical("NT", [{"type": "paragraph", "text": "text"}])
        assert _extract_tables(doc) == []


class TestSummarizeDocument:
    def test_summary_fields(self):
        doc = _make_canonical("Summary Test", SAMPLE_BLOCKS)
        summary = _summarize_document(doc)
        assert summary["title"] == "Summary Test"
        assert summary["block_count"] == 6
        assert summary["formula_count"] == 1
        assert summary["table_count"] == 1
        assert summary["blocks_by_type"]["paragraph"] == 1
        assert summary["text_length"] > 0


class TestCompareDocuments:
    def test_identical_documents(self):
        a = _make_canonical("Same", [
            {"type": "paragraph", "text": "Hello"},
            {"type": "formula", "text": "E = mc^2"},
        ])
        b = _make_canonical("Same", [
            {"type": "paragraph", "text": "Hello"},
            {"type": "formula", "text": "E = mc^2"},
        ])
        comp = _compare_documents(a, b)
        assert comp["text"]["jaccard_similarity"] == 1.0
        assert comp["structural"]["block_count"]["delta"] == 0
        assert comp["formulas"]["common_formulas"] == 1

    def test_different_documents(self):
        a = _make_canonical("A", [
            {"type": "paragraph", "text": "Hello world"},
            {"type": "table", "rows": [["x", "y"]]},
        ])
        b = _make_canonical("B", [
            {"type": "paragraph", "text": "Different content here"},
            {"type": "formula", "text": "F = ma"},
        ])
        comp = _compare_documents(a, b)
        assert comp["text"]["jaccard_similarity"] < 1.0
        assert comp["formulas"]["common_formulas"] == 0


class TestComputeVerdict:
    @staticmethod
    def _make_comparison(similarity: float = 1.0, block_delta: int = 0,
                         type_deltas: dict | None = None) -> dict:
        return {
            "text": {"jaccard_similarity": similarity},
            "structural": {
                "block_count": {"reference": 10, "toolbox": 10 + block_delta, "delta": block_delta},
                "blocks_by_type_delta": type_deltas or {},
            },
        }

    def test_equivalent(self):
        comp = self._make_comparison(similarity=0.95, block_delta=2)
        verdict = _compute_verdict(comp)
        assert "EQUIVALENTE" in verdict

    def test_low_similarity(self):
        comp = self._make_comparison(similarity=0.5)
        verdict = _compute_verdict(comp)
        assert "DIVERGENTE" in verdict

    def test_large_block_delta(self):
        comp = self._make_comparison(similarity=0.95, block_delta=50)
        verdict = _compute_verdict(comp)
        assert "DIVERGENTE" in verdict

    def test_significant_type_delta(self):
        comp = self._make_comparison(
            similarity=0.95,
            type_deltas={"table": {"reference": 10, "toolbox": 2}},
        )
        verdict = _compute_verdict(comp)
        assert "DIVERGENTE" in verdict


class TestPipelineRunnerWiring:
    """The comparison must not hide bugs in its own runner wiring (#646).

    ``run_comparison`` catches pipeline failures so the report can record
    them, but a ``NameError`` means this script calls a helper that does not
    exist -- a programming mistake that must surface instead of becoming an
    ``"error_type": "NameError"`` entry in an otherwise valid report.
    """

    @staticmethod
    def _write_reference(tmp_path: Path) -> Path:
        reference = tmp_path / "reference.json"
        reference.write_text(json.dumps({"sections": []}), encoding="utf-8")
        return reference

    def test_runner_name_error_is_not_swallowed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def runner_using_missing_helper(*_args: object, **_kwargs: object) -> dict:
            raise NameError("name '_run_pddl_toolbox' is not defined")

        monkeypatch.setattr(compare_pipelines, "_run_toolbox", runner_using_missing_helper)

        with pytest.raises(NameError, match="_run_pddl_toolbox"):
            asyncio.run(
                run_comparison(
                    file_path=tmp_path / "input.pdf",
                    reference_path=self._write_reference(tmp_path),
                    output_dir=tmp_path / "out",
                )
            )

    def test_pipeline_failure_is_still_recorded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def failing_runner(*_args: object, **_kwargs: object) -> dict:
            raise RuntimeError("toolbox offline")

        monkeypatch.setattr(compare_pipelines, "_run_toolbox", failing_runner)

        report_path = asyncio.run(
            run_comparison(
                file_path=tmp_path / "input.pdf",
                reference_path=self._write_reference(tmp_path),
                output_dir=tmp_path / "out",
            )
        )

        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["engines"]["toolbox"]["status"] == "error"
        assert report["engines"]["toolbox"]["error_type"] == "RuntimeError"
        assert "toolbox offline" in report["verdict"]

    def test_retired_reference_entry_point_stays_removed(self) -> None:
        """The duplicate reference runner deleted in #646 must not return."""
        assert not hasattr(compare_pipelines, "run_comparison_with_reference")

    def test_runner_is_defined_once(self) -> None:
        source = Path(compare_pipelines.__file__).read_text(encoding="utf-8")
        names = [
            node.name
            for node in ast.parse(source).body
            if isinstance(node, ast.AsyncFunctionDef)
        ]
        assert names.count("_run_toolbox") == 1


@pytest.mark.parametrize(
    "input_kind", ["relative-directory", "relative-file", "absolute-directory"]
)
def test_batch_mode_accepts_a_relative_or_absolute_input(
    tmp_path, monkeypatch, input_kind: str
) -> None:
    """A relative or absolute --batch input must resolve against the same base (#671)."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "001.pdf").write_bytes(b"%PDF-1.4\n")
    (tmp_path / "refs").mkdir()
    (tmp_path / "refs" / "001.json").write_text(
        json.dumps({"sections": []}), encoding="utf-8"
    )
    input_arg = {
        "relative-directory": "input",
        "relative-file": "input/001.pdf",
        "absolute-directory": str(tmp_path / "input"),
    }[input_kind]

    async def fake_run_comparison(
        *, file_path: Path, reference_path: Path, output_dir: Path, **_kwargs
    ) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        report = output_dir / "comparison_report.json"
        report.write_text(json.dumps({"verdict": "ok"}), encoding="utf-8")
        return report

    monkeypatch.setattr(compare_pipelines, "run_comparison", fake_run_comparison)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "compare-pipelines",
            input_arg,
            "--batch",
            "--reference-dir",
            "refs",
            "--output-dir",
            "out",
            "--max-files",
            "1",
        ],
    )

    assert compare_pipelines.main() == 0
    summary = json.loads(
        (tmp_path / "out" / "batch_summary.json").read_text(encoding="utf-8")
    )
    assert summary == [
        {
            "file": str(tmp_path / "input" / "001.pdf"),
            "status": "ok",
            "report_path": str(
                tmp_path / "out" / "001" / "comparison_report.json"
            ),
        }
    ]


@pytest.mark.parametrize("target_kind", ["inside", "outside"])
def test_batch_mode_keeps_a_symlinked_file_name(
    tmp_path, monkeypatch, target_kind: str
) -> None:
    """A symlinked file keeps its stem and cannot escape the input root (#671)."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "input").mkdir()
    source = tmp_path / "input" / "001.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    if target_kind == "inside":
        target = source
    else:
        target = tmp_path / "outside.pdf"
        target.write_bytes(b"%PDF-1.4\n")
    (tmp_path / "input" / "alias.pdf").symlink_to(target)
    (tmp_path / "refs").mkdir()
    for stem in ("001", "alias"):
        (tmp_path / "refs" / f"{stem}.json").write_text(
            json.dumps({"sections": []}), encoding="utf-8"
        )

    output_dirs: list[Path] = []

    async def fake_run_comparison(
        *, file_path: Path, reference_path: Path, output_dir: Path, **_kwargs
    ) -> Path:
        output_dirs.append(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        report = output_dir / "comparison_report.json"
        report.write_text(json.dumps({"verdict": "ok"}), encoding="utf-8")
        return report

    monkeypatch.setattr(compare_pipelines, "run_comparison", fake_run_comparison)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "compare-pipelines",
            "input",
            "--batch",
            "--reference-dir",
            "refs",
            "--output-dir",
            "out",
            "--max-files",
            "2",
        ],
    )

    assert compare_pipelines.main() == 0
    assert [directory.name for directory in output_dirs] == ["001", "alias"]
    summary = json.loads(
        (tmp_path / "out" / "batch_summary.json").read_text(encoding="utf-8")
    )
    assert [row["file"] for row in summary] == [
        str(tmp_path / "input" / "001.pdf"),
        str(tmp_path / "input" / "alias.pdf"),
    ]


def test_batch_mode_keeps_the_nested_stem_with_recursive(tmp_path, monkeypatch) -> None:
    """A recursive input keeps its subdirectory in the output stem (#671)."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "input" / "sub").mkdir(parents=True)
    (tmp_path / "input" / "sub" / "002.pdf").write_bytes(b"%PDF-1.4\n")
    (tmp_path / "refs").mkdir()
    (tmp_path / "refs" / "sub_002.json").write_text(
        json.dumps({"sections": []}), encoding="utf-8"
    )

    async def fake_run_comparison(
        *, file_path: Path, reference_path: Path, output_dir: Path, **_kwargs
    ) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        report = output_dir / "comparison_report.json"
        report.write_text(json.dumps({"verdict": "ok"}), encoding="utf-8")
        return report

    monkeypatch.setattr(compare_pipelines, "run_comparison", fake_run_comparison)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "compare-pipelines",
            "input",
            "--batch",
            "--recursive",
            "--reference-dir",
            "refs",
            "--output-dir",
            "out",
            "--max-files",
            "1",
        ],
    )

    assert compare_pipelines.main() == 0
    summary = json.loads(
        (tmp_path / "out" / "batch_summary.json").read_text(encoding="utf-8")
    )
    assert summary == [
        {
            "file": str(tmp_path / "input" / "sub" / "002.pdf"),
            "status": "ok",
            "report_path": str(
                tmp_path / "out" / "sub_002" / "comparison_report.json"
            ),
        }
    ]


def test_batch_mode_without_a_reference_reports_a_row(tmp_path, monkeypatch) -> None:
    """A batch input without --reference records the error row and fails (#671)."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "001.pdf").write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "compare-pipelines",
            "input",
            "--batch",
            "--output-dir",
            "out",
        ],
    )

    assert compare_pipelines.main() == 1
    summary = json.loads(
        (tmp_path / "out" / "batch_summary.json").read_text(encoding="utf-8")
    )
    assert summary == [
        {
            "file": str(tmp_path / "input" / "001.pdf"),
            "status": "ERRO: sem referencia",
            "report_path": "",
        }
    ]


def test_collect_inputs_accepts_supported_suffixes(tmp_path: Path) -> None:
    """Batch input collection accepts .pdf/.jpg/.jpeg/.png and ignores the rest (#695)."""
    for name in (
        "001.pdf",
        "002.PDF",
        "003.jpg",
        "004.jpeg",
        "005.JPEG",
        "006.png",
        "007.PNG",
        "008.ppg",
        "009.jng",
        "010.txt",
    ):
        (tmp_path / name).write_bytes(b"")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "011.jpeg").write_bytes(b"")
    (tmp_path / "dir.pdf").mkdir()
    (tmp_path / "broken.pdf").symlink_to(tmp_path / "missing.pdf")

    assert [path.name for path in _collect_inputs(tmp_path, recursive=False)] == [
        "001.pdf",
        "002.PDF",
        "003.jpg",
        "004.jpeg",
        "005.JPEG",
        "006.png",
        "007.PNG",
    ]
    assert [path.name for path in _collect_inputs(tmp_path, recursive=True)] == [
        "001.pdf",
        "002.PDF",
        "003.jpg",
        "004.jpeg",
        "005.JPEG",
        "006.png",
        "007.PNG",
        "011.jpeg",
    ]


@pytest.mark.parametrize("recursive", [False, True])
def test_collect_inputs_missing_path_returns_empty(tmp_path: Path, recursive: bool) -> None:
    """A missing input path is reported as no files, not a traceback (#695)."""
    assert _collect_inputs(tmp_path / "missing", recursive=recursive) == []


def test_collect_inputs_returns_empty_when_listing_fails(
    tmp_path: Path, monkeypatch
) -> None:
    """An unreadable directory is an empty collection, not a traceback (#695)."""

    def fail(_path: Path):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "iterdir", fail)

    assert _collect_inputs(tmp_path, recursive=False) == []


def test_main_reports_a_missing_input_without_a_traceback(
    tmp_path, monkeypatch, capsys
) -> None:
    """The CLI keeps its clean 'no files found' contract for a typo'd path (#695)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["compare-pipelines", "missing", "--batch"])

    assert compare_pipelines.main() == 1
    assert "nenhum arquivo encontrado" in capsys.readouterr().out


def test_max_files_rejects_a_negative_value(monkeypatch) -> None:
    """A negative --max-files must fail instead of slicing off the last file (#695)."""
    monkeypatch.setattr(
        sys,
        "argv",
        ["compare-pipelines", "input", "--batch", "--max-files", "-1"],
    )

    with pytest.raises(SystemExit) as caught:
        compare_pipelines.parse_args()

    assert caught.value.code == 2


def test_max_files_zero_processes_every_file(tmp_path, monkeypatch) -> None:
    """Zero keeps the documented unlimited semantics (#695)."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "input").mkdir()
    for name in ("001.pdf", "002.pdf"):
        (tmp_path / "input" / name).write_bytes(b"%PDF-1.4\n")
    (tmp_path / "refs").mkdir()
    for name in ("001.json", "002.json"):
        (tmp_path / "refs" / name).write_text(
            json.dumps({"sections": []}), encoding="utf-8"
        )

    seen: list[str] = []

    async def fake_run_comparison(
        *, file_path: Path, reference_path: Path, output_dir: Path, **_kwargs
    ) -> Path:
        seen.append(file_path.name)
        output_dir.mkdir(parents=True, exist_ok=True)
        report = output_dir / "comparison_report.json"
        report.write_text(json.dumps({"verdict": "ok"}), encoding="utf-8")
        return report

    monkeypatch.setattr(compare_pipelines, "run_comparison", fake_run_comparison)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "compare-pipelines",
            "input",
            "--batch",
            "--reference-dir",
            "refs",
            "--output-dir",
            "out",
            "--max-files",
            "0",
        ],
    )

    assert compare_pipelines.main() == 0
    assert seen == ["001.pdf", "002.pdf"]
