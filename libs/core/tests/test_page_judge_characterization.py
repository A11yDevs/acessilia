"""What the core's page judge does with each answer of the Toolbox (#470 phase 4).

``_judge_one_page`` renders a page, asks ``document.adjudicate.page`` and reads
the answer. These tests fake the Toolbox at the client factory, so the whole
path runs: the render client and the adjudicate client the run's
``ToolboxConfig`` builds, the request, and the reading of the answer. They
were written against develop before the judge reused the SDK's page judge
operation, and pin what it does, so the reuse changes nothing a run can see.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from core_config_support import toolbox_config
from pddl_support import build_element, build_manifest

from acessilia_core.pipeline import judge
from acessilia_core.toolbox.toolbox_client import ToolboxProviderUnavailable

PNG = b"\x89PNG\r\n\x1a\njudged-page"


class _Rendered:
    image = PNG
    clip = (0.0, 0.0, 595.0, 842.0)


class _FakeToolbox:
    """The two clients the judge builds, answering as the Toolbox would."""

    def __init__(self, answer=None, error: Exception | None = None) -> None:
        self.answer = answer
        self.error = error
        self.renders: list[dict] = []
        self.judged: list[dict] = []
        self.closed = 0

    def factory(self, client_cls, _toolbox, **_overrides):
        fake = self

        class Client:
            provider = "fake"

            async def render(self, file_path=None, artifact_id=None, **kwargs):
                fake.renders.append({"file_path": file_path, "artifact_id": artifact_id, **kwargs})
                return _Rendered()

            async def judge_page(self, candidate_a, candidate_b, file_path=None, **kwargs):
                fake.judged.append(
                    {"a": candidate_a, "b": candidate_b, "image": file_path.read_bytes()}
                )
                if fake.error is not None:
                    raise fake.error
                return fake.answer

            async def close(self):
                fake.closed += 1

        return Client()


@pytest.fixture
def manifest(tmp_path: Path):
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    built = build_manifest([build_element("p-1", "paragraph", text="x")], [])
    built.source.path = str(source)
    built.source.media_type = "application/pdf"
    return built


def _run(monkeypatch, manifest, toolbox: _FakeToolbox):
    monkeypatch.setattr("acessilia_core.toolbox.toolbox_client.make_toolbox_client", toolbox.factory)
    return judge._judge_one_page(
        manifest, 1, "primary", "secondary", "page as held", "the other reading",
        toolbox=toolbox_config(),
    )


def test_the_page_is_rendered_whole_and_bounded_then_judged(monkeypatch, manifest) -> None:
    toolbox = _FakeToolbox({"document": {"pB": 0.3, "pB_ab": 0.4, "pA_ba": 0.8, "model": "m"}})

    judgement, failure = _run(monkeypatch, manifest, toolbox)

    assert failure is None
    (render,) = toolbox.renders
    assert (render["page_number"], render["dpi"], render["max_side"]) == (1, 144, 1600)
    assert render.get("clip") is None
    assert toolbox.judged == [{"a": "page as held", "b": "the other reading", "image": PNG}]
    assert toolbox.closed == 2
    assert judgement == {
        "content": "primary", "choice": "primary", "pB": 0.3, "pB_ab": 0.4,
        "pA_ba": 0.8, "model": "m", "truncated": False,
    }


@pytest.mark.parametrize(
    ("document", "choice", "p_b"),
    [
        ({"pB": 0.9, "pB_ab": 0.95, "pA_ba": 0.1, "model": "qwen"}, "secondary", 0.9),
        ({"pB": "0.8"}, "secondary", 0.8),
        ({"pB": True}, "secondary", 1.0),
        ({"pB": 0}, "primary", 0.0),
    ],
    ids=["prefers B", "numeric string", "boolean", "zero"],
)
def test_the_choice_follows_pb_against_the_threshold(
    monkeypatch, manifest, document, choice, p_b
) -> None:
    judgement, failure = _run(monkeypatch, manifest, _FakeToolbox({"document": document}))

    assert failure is None
    assert judgement["choice"] == choice
    assert judgement["pB"] == pytest.approx(p_b)
    assert judgement["model"] == document.get("model")


@pytest.mark.parametrize(
    "document",
    [{"pB": 1.5}, {"pB": "n/a"}, {"pB": None}, {}],
    ids=["out of range", "not a number", "null", "absent"],
)
def test_an_answer_without_a_valid_pb_fails_the_method(monkeypatch, manifest, document) -> None:
    judgement, failure = _run(monkeypatch, manifest, _FakeToolbox({"document": document}))

    assert judgement is None
    assert failure is not None and not failure.success
    assert repr(document.get("pB")) in failure.message


def test_an_answer_without_a_document_fails_the_method(monkeypatch, manifest) -> None:
    judgement, failure = _run(monkeypatch, manifest, _FakeToolbox({"status": "succeeded"}))

    assert judgement is None
    assert "None" in failure.message


def test_an_unavailable_judge_fails_the_method(monkeypatch, manifest) -> None:
    toolbox = _FakeToolbox(error=ToolboxProviderUnavailable("busy"))

    judgement, failure = _run(monkeypatch, manifest, toolbox)

    assert judgement is None
    assert "ToolboxProviderUnavailable" in failure.message


def test_a_long_transcription_is_judged_truncated(monkeypatch, manifest) -> None:
    monkeypatch.setattr("acessilia_core.toolbox.toolbox_client.make_toolbox_client",
                        _FakeToolbox({"document": {"pB": 0.1}}).factory)

    judgement, failure = judge._judge_one_page(
        manifest, 1, "primary", "secondary", "x" * (judge._JUDGE_MAX_CHARS + 1), "y",
        toolbox=toolbox_config(),
    )

    assert failure is None and judgement["truncated"] is True


@pytest.mark.parametrize(
    "document",
    [["not", "an", "object"], "text", None, 42, True],
    ids=["a list", "a string", "null", "a number", "a boolean"],
)
def test_a_document_that_is_not_an_object_fails_the_method(monkeypatch, manifest, document) -> None:
    """The one change of the reuse: develop raised ``AttributeError`` here
    (``.get`` on a list, a string, ``None``, a number or a boolean), out of
    the method; the SDK reads such an answer as one without ``pB``, so the
    method fails with that reason. An answer with no ``document`` key at all
    is a different case, which develop already failed the method for."""
    judgement, failure = _run(monkeypatch, manifest, _FakeToolbox({"document": document}))

    assert judgement is None
    assert failure is not None and "None" in failure.message
