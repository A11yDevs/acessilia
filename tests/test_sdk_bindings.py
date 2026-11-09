"""The SDK registry's contract data is generated from the published contract (#213).

``scripts/generate_sdk_bindings.py`` writes the block of
``libs/sdk/src/acessilia_sdk/toolbox/capabilities.py`` between
``# BEGIN GENERATED BINDINGS`` and ``# END GENERATED BINDINGS`` from
``tests/fixtures/toolbox-contract.json``. CI runs this suite, so a stale block,
or a selected capability the contract no longer supports, fails it.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GENERATOR_PATH = REPO_ROOT / "scripts" / "generate_sdk_bindings.py"


@pytest.fixture(scope="module")
def generator():
    spec = importlib.util.spec_from_file_location("generate_sdk_bindings", GENERATOR_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def source(generator) -> str:
    return generator.REGISTRY_PATH.read_text(encoding="utf-8")


@pytest.fixture
def contract(generator) -> dict:
    return json.loads(generator.CONTRACT_PATH.read_text(encoding="utf-8"))


def _entry(contract: dict, capability_id: str, version: int) -> dict:
    return next(
        entry
        for entry in contract["capabilities"]
        if (entry["id"], entry["version"]) == (capability_id, version)
    )


def test_the_generated_block_is_up_to_date(generator, source, contract) -> None:
    assert generator.regenerate(source, contract) == source, (
        "the SDK bindings are stale: run python scripts/generate_sdk_bindings.py"
    )


def test_the_registry_is_built_from_the_generated_block(generator, source, contract) -> None:
    """Every allowed capability takes its schema and idempotency from the contract."""
    from acessilia_sdk.toolbox.capabilities import TOOLBOX_CAPABILITIES

    data = generator.bindings(generator.selection(source), contract)
    assert set(data) == {(c.id, c.contract_version) for c in TOOLBOX_CAPABILITIES.values()}
    for capability in TOOLBOX_CAPABILITIES.values():
        assert (capability.output_schema, capability.idempotent) == data[
            (capability.id, capability.contract_version)
        ], capability.id


def test_a_changed_contract_makes_the_block_stale(generator, source, contract) -> None:
    _entry(contract, "dataset.sync", 1)["execution"]["idempotent"] = False

    regenerated = generator.regenerate(source, contract)

    assert regenerated != source
    assert "('dataset.sync', 1): (None, False)," in regenerated
    # Only the generated block changes; the hand-written selection stays.
    head, _, tail = source.partition(generator.BEGIN)
    assert regenerated.startswith(head + generator.BEGIN)
    assert regenerated.endswith(tail.partition(generator.END)[2])


def test_the_execute_output_schema_drops_the_artifact_prefix(generator, contract) -> None:
    data = generator.bindings([("pdf.render", 2, "execute")], contract)

    assert data == {("pdf.render", 2): ("image@2", True)}


def test_a_rest_capability_has_no_output_schema(generator, contract) -> None:
    data = generator.bindings([("dataset.list", 1, "rest")], contract)

    assert data == {("dataset.list", 1): (None, True)}


def test_a_selected_capability_the_contract_does_not_publish_is_refused(
    generator, contract
) -> None:
    with pytest.raises(generator.BindingError, match=r"pdf\.render@9 is selected"):
        generator.bindings([("pdf.render", 9, "execute")], contract)


@pytest.mark.parametrize("value", [None, "true", 1])
def test_a_non_boolean_idempotent_is_refused(generator, contract, value) -> None:
    _entry(contract, "dataset.sync", 1)["execution"]["idempotent"] = value

    with pytest.raises(generator.BindingError, match="not a boolean"):
        generator.bindings([("dataset.sync", 1, "rest")], contract)


def test_a_missing_idempotent_is_refused(generator, contract) -> None:
    del _entry(contract, "dataset.sync", 1)["execution"]

    with pytest.raises(generator.BindingError, match="not a boolean"):
        generator.bindings([("dataset.sync", 1, "rest")], contract)


def test_an_execute_capability_without_an_output_schema_is_refused(generator, contract) -> None:
    del _entry(contract, "document.ocr", 1)["output"]

    with pytest.raises(generator.BindingError, match="no output.schema"):
        generator.bindings([("document.ocr", 1, "execute")], contract)


def test_the_selection_is_read_from_literal_arguments_only(generator) -> None:
    source = (
        'A = _selected("x.y", 1, "X")\n'
        'B = _selected("z.w", 2, "Z", transport="rest")\n'
    )
    assert generator.selection(source) == [("x.y", 1, "execute"), ("z.w", 2, "rest")]

    with pytest.raises(generator.BindingError, match="must be literals"):
        generator.selection('ID = "x.y"\nA = _selected(ID, 1, "X")\n')


def test_the_registry_needs_exactly_one_generated_block(generator, source, contract) -> None:
    without = source.replace(generator.BEGIN, "")
    with pytest.raises(generator.BindingError, match="exactly one generated block"):
        generator.regenerate(without, contract)

    twice = source + generator.BEGIN + generator.END
    with pytest.raises(generator.BindingError, match="exactly one generated block"):
        generator.regenerate(twice, copy.deepcopy(contract))


# ── Result models generated from published schemas (#185) ──────────────────


def _reference_schema(generator) -> dict:
    return json.loads((generator.SCHEMAS_DIR / "reference@1.json").read_text(encoding="utf-8"))


def test_the_generated_models_are_up_to_date(generator) -> None:
    for path, text in generator.models().items():
        assert path.read_text(encoding="utf-8") == text, (
            f"{path.name} is stale: run python scripts/generate_sdk_bindings.py"
        )


def test_the_reference_model_comes_from_the_captured_schema(generator) -> None:
    from acessilia_sdk.toolbox.reference import REQUIRED, SCHEMA_ID, ArtifactReference

    schema = _reference_schema(generator)
    assert SCHEMA_ID == schema["$id"]
    assert REQUIRED == tuple(schema["required"])
    assert list(ArtifactReference.__dataclass_fields__) == list(schema["properties"])


def test_a_changed_schema_changes_the_generated_model(generator) -> None:
    schema = _reference_schema(generator)
    schema["properties"]["size"]["minimum"] = 1

    module = generator.render_model(schema, "ArtifactReference", "reference@1.json")

    assert "value < 1" in module
    assert module != generator.models()[generator.MODELS["reference@1.json"][1]]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"type": "array"}, "only flat object schemas"),
        ({"properties": {"nested": {"type": "object"}}}, "unsupported type"),
        ({"properties": {"x": {"type": "string", "format": "uri"}}}, "unsupported keywords"),
        ({"properties": {"x": {"type": "string"}}, "required": ["y"]}, "not declared"),
        ({"properties": {"not-an-id": {"type": "string"}}, "required": []}, "not an identifier"),
    ],
)
def test_the_model_generator_refuses_what_it_cannot_express(generator, change, message) -> None:
    schema = {"$id": "urn:test:1", "type": "object", "properties": {}, "required": []}
    schema.update(change)

    with pytest.raises(generator.BindingError, match=message):
        generator.render_model(schema, "Model", "test@1.json")
