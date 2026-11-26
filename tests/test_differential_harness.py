"""The harness of the differential fixtures, on its own (#849, #875 review).

The comparison must not accept what it was not told to; the fake Toolbox
must refuse what the case does not answer; a run must leave the environment
as it found it; a recording must publish a whole reference or none.
"""

from __future__ import annotations

import base64
import json
import os
from importlib import util as importlib_util
from pathlib import Path

import httpx
import pytest

from tests.differential import fake_toolbox
from tests.differential.compare import differences, explain
from tests.differential.fake_toolbox import FakeToolbox
from tests.differential.runner import CASES, hermetic_environment, normalize, run_case

ROOT = Path(__file__).resolve().parents[1]


# The comparison.


def test_differences_name_what_was_added_removed_and_changed() -> None:
    reference = {"a": 1, "b": [1, 2], "c": {"d": "x"}, "e/f": 0}
    current = {"a": 2, "b": [1], "c": {"d": "x", "g": True}, "e/f": 1}

    assert differences(reference, current) == [
        {"kind": "changed", "path": "/a"},
        {"kind": "removed", "path": "/b/1"},
        {"kind": "added", "path": "/c/g"},
        {"kind": "changed", "path": "/e~1f"},
    ]


def test_a_block_inserted_is_one_addition_not_a_change_of_every_later_block() -> None:
    """#887: lists of objects with distinct ids are aligned by id, so a
    rescued paragraph is one ``added``; a change inside a block that moved
    names the block's place on both sides."""
    reference = {"blocks": [{"id": "a", "text": "A"}, {"id": "c", "text": "C"}]}
    current = {"blocks": [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}, {"id": "c", "text": "C!"}]}

    assert differences(reference, current) == [
        {"kind": "added", "path": "/blocks/1"},
        {"kind": "changed", "path": "/blocks/2/text", "reference_path": "/blocks/1/text"},
    ]


def test_the_same_blocks_in_another_order_are_a_change() -> None:
    reference = {"blocks": [{"id": "a"}, {"id": "b"}]}
    current = {"blocks": [{"id": "b"}, {"id": "a"}]}

    assert differences(reference, current) == [{"kind": "changed", "path": "/blocks"}]


def test_a_removed_block_is_checked_against_its_reference_place() -> None:
    reference = {"blocks": [{"id": "a"}, {"id": "gone", "text": "G"}, {"id": "c"}]}
    current = {"blocks": [{"id": "a"}, {"id": "c"}]}
    declared = [{"kind": "removed", "path": "/blocks/1", "was": {"id": "gone", "text": "G"}, "reason": "r"}]

    assert explain(reference, current, declared) == ([], [])


@pytest.mark.parametrize(
    "ids",
    [[["a", "b"], "c"], [None, "c"], ["", "c"], ["a", "a"], [1, 2]],
    ids=["unhashable", "missing", "empty", "repeated", "not-strings"],
)
def test_a_list_whose_ids_are_not_distinct_strings_is_compared_by_position(ids) -> None:
    """#891 review: only distinct, non-empty string ids align a list; any
    other (an unhashable id included) is compared position by position,
    without an error."""
    reference = {"items": [{"id": value, "text": "x"} for value in ids]}
    current = {"items": [{"id": value, "text": "y"} for value in ids]}

    assert differences(reference, current) == [
        {"kind": "changed", "path": "/items/0/text"},
        {"kind": "changed", "path": "/items/1/text"},
    ]
    assert differences({"items": []}, {"items": []}) == []


def test_a_declared_change_allows_only_its_value() -> None:
    """A later regression of a field whose change was declared still fails."""
    declared = [{"kind": "changed", "path": "/blocks/*/text", "expected": "x^{2}", "reason": "r"}]

    assert explain({"blocks": [{"text": "x²"}]}, {"blocks": [{"text": "x^{2}"}]}, declared) == ([], [])
    unexplained, unused = explain({"blocks": [{"text": "x²"}]}, {"blocks": [{"text": "y^{3}"}]}, declared)
    assert unexplained == [{"kind": "changed", "path": "/blocks/0/text"}] and unused == declared


def test_a_declared_addition_or_removal_checks_its_value() -> None:
    added = [{"kind": "added", "path": "/flag", "expected": {}, "reason": "r"}]
    assert explain({}, {"flag": {}}, added) == ([], [])
    assert explain({}, {"flag": {"x": 1}}, added)[0] == [{"kind": "added", "path": "/flag"}]

    removed = [{"kind": "removed", "path": "/old", "was": 1, "reason": "r"}]
    assert explain({"old": 1}, {}, removed) == ([], [])
    assert explain({"old": 2}, {}, removed)[0] == [{"kind": "removed", "path": "/old"}]


def test_an_addition_or_change_without_its_value_is_refused() -> None:
    with pytest.raises(ValueError, match="expected value"):
        explain({"a": 1}, {"a": 2}, [{"kind": "changed", "path": "/a", "reason": "r"}])


def test_only_the_volatile_pointers_are_dropped() -> None:
    """A ``path`` elsewhere in the output is compared."""
    document = {"id": "doc-1", "source": {"path": "/tmp/x", "name": "x"}, "blocks": [{"path": "kept"}],
                "metadata": {"pddl_plan_id": "plan-1", "pddl_planner": "internal"}}

    assert normalize(document) == {"blocks": [{"path": "kept"}], "metadata": {"pddl_planner": "internal"},
                                   "source": {"name": "x"}}


# The fake Toolbox.


def _case() -> dict:
    return json.loads((CASES / "text-and-picture" / "case.json").read_text(encoding="utf-8"))


def _render(fake: FakeToolbox, clip: dict) -> bytes:
    request = httpx.Request(
        "POST", f"{fake_toolbox.BASE_URL}/v1/capabilities/pdf.render:execute",
        files={"file": ("x.pdf", b"%PDF", "application/pdf")},
        data={"provider": "fake", "parameters": json.dumps({"page_number": 1, "clip": clip})},
    )
    request.read()  # what the transport does before it hands the request over
    response = fake.handle(request)
    artifact = response.json()["document"]["artifact_id"].removeprefix("sha256:")
    return fake.artifacts[artifact]


def _ask(fake: FakeToolbox, image: bytes, schema: dict | None = None) -> httpx.Response:
    body: dict = {"model": "m", "messages": [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(image).decode()}},
    ]}]}
    if schema is not None:
        body["response_format"] = {"type": "json_schema", "json_schema": {"name": "S", "schema": schema}}
    return fake.handle(httpx.Request("POST", f"{fake_toolbox.BASE_URL}/v1/vlm/p/chat/completions", json=body))


SCHEMA = {"type": "object", "properties": {"description": {"type": "string", "minLength": 1}},
          "required": ["description"], "additionalProperties": False}


def test_the_fake_answers_the_element_the_clip_overlaps_most() -> None:
    fake = FakeToolbox(_case())
    picture = _render(fake, {"left": 72, "top": 222, "right": 540, "bottom": 418, "origin": "TOPLEFT"})

    answer = json.loads(_ask(fake, picture, SCHEMA).json()["choices"][0]["message"]["content"])

    assert answer == {"description": "Photograph of a bench with an oscilloscope and cables."}
    assert fake.unhandled == []


@pytest.mark.parametrize("problem", ["no answer", "no element", "not rendered", "invalid"])
def test_the_fake_refuses_what_the_case_does_not_answer(problem) -> None:
    """A wrong region or a missing answer is never answered generically."""
    case = _case()
    if problem == "no answer":
        case["vision"] = {}
    fake = FakeToolbox(case)
    clip = {"left": 72, "top": 222, "right": 540, "bottom": 418, "origin": "TOPLEFT"}
    if problem == "no element":
        clip = {"left": 560, "top": 700, "right": 600, "bottom": 780, "origin": "TOPLEFT"}
    image = _render(fake, clip)
    if problem == "not rendered":
        image = fake_toolbox._solid_png(7)
    schema = {**SCHEMA, "properties": {"description": {"type": "string", "maxLength": 3}}} if problem == "invalid" else SCHEMA

    response = _ask(fake, image, schema)

    assert response.status_code == 422 and len(fake.unhandled) == 1


def test_a_whole_page_is_not_taken_for_the_element_at_its_centre() -> None:
    case = json.loads((CASES / "formulas" / "case.json").read_text(encoding="utf-8"))
    fake = FakeToolbox(case)
    page = _render(fake, {"left": 0, "top": 0, "right": 612, "bottom": 792, "origin": "TOPLEFT"})

    assert fake._element_of_image(page) == "page-1"


def test_two_elements_matching_a_clip_equally_are_refused() -> None:
    case = _case()
    twin = json.loads(json.dumps(next(e for e in case["document"]["elements"] if e["id"] == "pic1")))
    twin["id"] = "pic2"
    case["document"]["elements"].append(twin)
    fake = FakeToolbox(case)
    image = _render(fake, {"left": 72, "top": 220, "right": 540, "bottom": 420, "origin": "TOPLEFT"})

    with pytest.raises(fake_toolbox._Unanswerable, match="equally"):
        fake._element_of_image(image)


def test_the_colour_index_has_a_bound() -> None:
    assert fake_toolbox._decode_index(fake_toolbox._solid_png(511)) == 511
    with pytest.raises(ValueError):
        fake_toolbox._solid_png(512)


# The environment.


def test_a_run_restores_the_environment_even_when_it_fails(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LEGACY_UNICODE_REPAIR", "repair")
    case = tmp_path / "broken" / "case.json"
    case.parent.mkdir()
    case.write_text(json.dumps({"document": {"elements": "not a list"},
                                "environment": {"DIFFERENTIAL_ONLY_IN_THE_CASE": "1"}}))
    before = dict(os.environ)

    with pytest.raises(Exception):  # noqa: B017 - any failure of the run
        run_case(case)

    assert dict(os.environ) == before


def test_the_settings_see_only_their_defaults_and_the_harness(monkeypatch) -> None:
    """What a developer's shell or ``.env`` sets does not reach the run."""
    monkeypatch.setenv("LEGACY_UNICODE_REPAIR", "repair")
    monkeypatch.setenv("PDDL_MAX_DISCOVERY_REPLANS", "0")
    from backend.config.settings import Settings

    with hermetic_environment({}) as workdir:
        settings = Settings()
        assert settings.legacy_unicode_repair != "repair"
        assert str(settings.data_dir).startswith(str(workdir))


def test_the_orchestrator_keeps_its_own_replan_budgets(monkeypatch) -> None:
    """The settings read the budgets at import, which no environment cleaning
    reaches: the runner leaves them to the constructor's defaults."""
    import dataclasses

    from acessilia_core.pipeline.orchestrator import PddlAccessibilityOrchestrator
    from backend.config.settings import Settings
    from tests.differential.runner import _orchestrator

    settings = dataclasses.replace(Settings(), pddl_max_replans=0, pddl_max_discovery_replans=0)
    orchestrator = _orchestrator(PddlAccessibilityOrchestrator, settings)
    default = PddlAccessibilityOrchestrator(enable_ocr=False, extractor_backend="toolbox")

    assert (orchestrator.max_replans, orchestrator.max_discovery_replans) == (
        default.max_replans, default.max_discovery_replans)
    assert not orchestrator.execute_dry_run


# The recording.


def _recorder():
    spec = importlib_util.spec_from_file_location("recorder", ROOT / "scripts" / "record_differential_references.py")
    module = importlib_util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _outputs(directory: Path, cases: dict[str, list]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for case, unhandled in cases.items():
        (directory / f"{case}.json").write_text(json.dumps({"canonical": {"case": case}, "unhandled": unhandled}))
    return directory


def _reference(target: Path, source: dict) -> None:
    target.mkdir(parents=True)
    for name in ("a", "gone"):
        (target / f"{name}.json").write_text("old")
    (target / "intended.json").write_text("{}")
    (target / "SOURCE.json").write_text(json.dumps(source))


def test_a_failed_case_publishes_nothing(tmp_path) -> None:
    recorder = _recorder()
    target = tmp_path / "references" / "core-x"
    _reference(target, {"commit": "c"})
    out = _outputs(tmp_path / "out", {"a": [], "b": ["POST /v1/x"]})

    with pytest.raises(SystemExit, match="did not answer"):
        recorder.publish(out, target, {"commit": "d"}, ["a", "b"], complete=True)

    assert sorted(path.name for path in target.iterdir()) == ["SOURCE.json", "a.json", "gone.json", "intended.json"]
    assert (target / "a.json").read_text() == "old"


def test_a_complete_recording_replaces_the_reference_and_keeps_the_declarations(tmp_path) -> None:
    recorder = _recorder()
    target = tmp_path / "references" / "core-x"
    _reference(target, {"commit": "c"})

    recorder.publish(_outputs(tmp_path / "out", {"a": [], "b": []}), target, {"commit": "d"}, ["a", "b"], complete=True)

    assert sorted(path.name for path in target.iterdir()) == ["SOURCE.json", "a.json", "b.json", "intended.json"]
    assert json.loads((target / "SOURCE.json").read_text()) == {"commit": "d"}
    assert not any(path.name.startswith(".") for path in target.parent.iterdir())


def test_a_failure_on_purpose_the_run_did_not_meet_publishes_nothing(tmp_path) -> None:
    """#888 review: an older core that never called the failing capability
    would record a healthy run as the degraded case's reference."""
    recorder = _recorder()
    target = tmp_path / "references" / "core-x"
    _reference(target, {"commit": "c"})
    out = _outputs(tmp_path / "out", {"a": []})

    with pytest.raises(SystemExit, match="failures on purpose"):
        recorder.publish(out, target, {"commit": "d"}, ["a"], complete=True, failures={"a": {"math.recognize"}})

    assert (target / "a.json").read_text() == "old"


def test_a_partial_recording_needs_the_same_commit_and_harness(tmp_path) -> None:
    recorder = _recorder()
    target = tmp_path / "references" / "core-x"
    _reference(target, {"commit": "c"})
    out = _outputs(tmp_path / "out", {"a": []})

    with pytest.raises(SystemExit, match="another commit or harness"):
        recorder.publish(out, target, {"commit": "d"}, ["a"], complete=False)
    recorder.publish(out, target, {"commit": "c"}, ["a"], complete=False)

    assert json.loads((target / "a.json").read_text()) == {"canonical": {"case": "a"}, "unhandled": []}
    assert (target / "gone.json").read_text() == "old"


# Two providers, a page judgement and failures on purpose (#876).


def _execute(fake: FakeToolbox, capability: str, provider: str = "fake") -> httpx.Response:
    request = httpx.Request(
        "POST", f"{fake_toolbox.BASE_URL}/v1/capabilities/{capability}:execute",
        files={"file": ("x.pdf", b"%PDF", "application/pdf")}, data={"provider": provider},
    )
    request.read()
    return fake.handle(request)


def test_the_secondary_provider_gets_the_secondary_document() -> None:
    case = json.loads((CASES / "dual-provider" / "case.json").read_text(encoding="utf-8"))
    fake = FakeToolbox(case)

    primary = _execute(fake, "document.structure.extract", "docling").json()["document"]
    secondary = _execute(fake, "document.structure.extract", "mineru").json()["document"]

    assert primary == case["document"] and secondary == case["secondary_document"]


def _render_page(fake: FakeToolbox, page: int) -> bytes:
    request = httpx.Request(
        "POST", f"{fake_toolbox.BASE_URL}/v1/capabilities/pdf.render:execute",
        files={"file": ("x.pdf", b"%PDF", "application/pdf")},
        data={"provider": "fake", "parameters": json.dumps({"page_number": page})},
    )
    request.read()
    artifact = fake.handle(request).json()["document"]["artifact_id"].removeprefix("sha256:")
    return fake.artifacts[artifact]


def _judge(fake: FakeToolbox, image: bytes) -> httpx.Response:
    request = httpx.Request(
        "POST", f"{fake_toolbox.BASE_URL}/v1/capabilities/document.adjudicate.page:execute",
        files={"file": ("page.png", image, "image/png")}, data={"provider": "fake"},
    )
    request.read()
    return fake.handle(request)


def _dual() -> dict:
    return json.loads((CASES / "dual-provider" / "case.json").read_text(encoding="utf-8"))


def test_a_page_judgement_answers_the_page_it_was_asked_about() -> None:
    """#888 review: the judgement is the declared page's; another page, or
    an image the fake did not render, is unhandled."""
    fake = FakeToolbox(_dual())
    assert _judge(fake, _render_page(fake, 1)).json()["document"] == {"pB": 0.2}

    assert _judge(fake, _render_page(fake, 2)).status_code == 422
    assert _judge(fake, fake_toolbox._solid_png(9)).status_code == 422
    assert len(fake.unhandled) == 2


@pytest.mark.parametrize("provider", ["mineru-hyb", "unknown"])
def test_an_unexpected_extraction_provider_is_unhandled(provider) -> None:
    """#888 review: only the primary provider, and the secondary when the
    case has a secondary document, get an extraction."""
    fake = FakeToolbox(_dual())
    assert _execute(fake, "document.structure.extract", provider).status_code == 422
    assert fake.unhandled


def test_a_single_provider_case_gives_no_secondary_extraction() -> None:
    fake = FakeToolbox(_case())
    assert _execute(fake, "document.structure.extract", "mineru").status_code == 422


def test_a_region_only_the_secondary_extracted_is_matched() -> None:
    """#888 review: page 3 is routed to the secondary, whose formula ``v2``
    the primary does not have; a region both providers have (``u1``,
    ``v1``) is the primary's, with no artificial tie."""
    fake = FakeToolbox(_dual())

    def region(top, bottom):
        request = httpx.Request(
            "POST", f"{fake_toolbox.BASE_URL}/v1/capabilities/pdf.render:execute",
            files={"file": ("x.pdf", b"%PDF", "application/pdf")},
            data={"provider": "fake", "parameters": json.dumps({"page_number": 3, "clip": {
                "left": 72, "top": top, "right": 540, "bottom": bottom, "origin": "TOPLEFT"}})},
        )
        request.read()
        artifact = fake.handle(request).json()["document"]["artifact_id"].removeprefix("sha256:")
        return fake._element_of_image(fake.artifacts[artifact])

    assert region(250, 280) == "v2"
    assert region(60, 170) == "u1"


def test_a_failure_on_purpose_is_refused_but_not_unhandled() -> None:
    case = {**_case(), "failures": {"capabilities": ["math.recognize"], "vision": ["pic1"]}}
    fake = FakeToolbox(case)

    assert _execute(fake, "math.recognize").status_code == 503
    picture = _render(fake, {"left": 72, "top": 222, "right": 540, "bottom": 418, "origin": "TOPLEFT"})
    assert _ask(fake, picture, SCHEMA).status_code == 503
    assert fake.refused == ["math.recognize", "vlm:pic1"] and fake.unhandled == []


def test_the_output_does_not_follow_the_process_locale() -> None:
    """#888 review: an earlier test (the API's lifespan) or ``LANG`` set the
    process locale to pt_BR, and the degraded case's warnings and fallback
    alt text followed it. The run pins its locale, and restores the one it
    found."""
    from acessilia_core import i18n

    previous = i18n._SERVER_LOCALE
    try:
        outputs = []
        for locale in ("pt_BR", "en_US"):
            i18n.configure_server_locale(locale)
            outputs.append(run_case(CASES / "degraded" / "case.json")["canonical"])
            assert i18n.server_locale() == locale
    finally:
        i18n._SERVER_LOCALE = previous

    assert outputs[0] == outputs[1]
