"""The method handlers' contract with the executor and the run (#543).

The executor calls a handler as ``handler(manifest, obligation_id)``, and a
run binds the ``config`` and ``ports`` the handler declares. These tests pin
that contract: every registered handler keeps it, a broken handler fails when
the registry is built or bound, not when a plan first runs it, and each rule
rejects what it is meant to.
"""

from __future__ import annotations

import argparse
import sys
from functools import partial
from types import ModuleType, SimpleNamespace
from typing import Annotated

import acessilia_core.config
import pytest
from acessilia_core.config import CoreConfig
from acessilia_core.execution.executor import MethodRegistry
from acessilia_core.pipeline.handlers import registry as handler_registry
from acessilia_core.pipeline.handlers.registry import (
    METHOD_HANDLERS,
    HandlerContractError,
    bind_run,
    build_method_registry,
    run_parameters,
)
from acessilia_core.ports import RunPorts

from tests.core_config_support import core_config

#: The handlers that take run parameters, by method. Any other handler takes none.
EXPECTED_RUN_PARAMETERS = {
    "mathml": ("config",),
    "latex-verbalizer": ("config",),
    "dual-provider-fusion": ("config",),
    "single-provider": ("config",),
    "vlm-pairwise-judge": ("config",),
    "rescue-omitted": ("config",),
    "pymupdf-region": ("config", "ports"),
    "vision-page-inspection": ("config", "ports"),
}


def test_every_registered_handler_keeps_the_contract() -> None:
    declared = {method: run_parameters(handler) for method, handler in METHOD_HANDLERS.items()}

    assert {method: names for method, names in declared.items() if names} == EXPECTED_RUN_PARAMETERS


def test_a_broken_registered_handler_fails_when_the_registry_is_built(monkeypatch) -> None:
    def broken(manifest, obligation_id, *, cfg: CoreConfig):
        return None

    monkeypatch.setitem(handler_registry.METHOD_HANDLERS, "mathml", broken)

    with pytest.raises(HandlerContractError, match="broken"):
        build_method_registry()


def test_bind_run_checks_every_handler_before_binding_any(monkeypatch) -> None:
    def fine(manifest, obligation_id, *, config: CoreConfig):
        return config

    def broken(manifest, obligation_id, *, config):
        return config

    registry = MethodRegistry()
    registry.register("fine", fine)
    registry.register("broken", broken)
    bound = []

    class Recording(MethodRegistry):
        def register(self, method, handler):
            bound.append(method)
            super().register(method, handler)

    monkeypatch.setattr(handler_registry, "MethodRegistry", Recording)

    with pytest.raises(HandlerContractError, match=r"broken: `config` must be annotated `CoreConfig`"):
        bind_run(registry, core_config(), RunPorts.none())
    assert bound == [], "the first handler, which keeps the contract, is not bound either"


def test_the_contract_error_is_a_type_error() -> None:
    assert issubclass(HandlerContractError, TypeError)


def _plain(manifest, obligation_id):
    return None


def _with_both(manifest, obligation_id, *, config: CoreConfig, ports: RunPorts):
    return config, ports


def _dotted(manifest, obligation_id, *, config: acessilia_core.config.CoreConfig):
    return config


def _quoted(manifest, obligation_id, *, config: "CoreConfig", ports: "RunPorts"):  # noqa: UP037 - the quotes are the case
    return config


def _annotated(manifest, obligation_id, *, config: Annotated[CoreConfig, "the run's"]):
    return config


def _optional_extra(manifest, obligation_id, *, config: CoreConfig, retries: int = 2):
    return config


def _anything(*args, **kwargs):
    return None


@pytest.mark.parametrize(
    ("handler", "declared"),
    [
        (_plain, ()),
        (_with_both, ("config", "ports")),
        # Annotations are resolved in the handler's module (review of #581).
        (_dotted, ("config",)),
        (_quoted, ("config", "ports")),
        (_annotated, ("config",)),
        # An optional keyword-only parameter is allowed; nothing binds it.
        (_optional_extra, ("config",)),
        (_anything, ()),
        # An already bound handler is bound again with the next run's values.
        (partial(_with_both, config="first", ports="first"), ("config", "ports")),
        (lambda manifest, obligation_id: None, ()),
    ],
    ids=[
        "plain", "both", "dotted", "quoted", "annotated", "optional-extra", "var-args",
        "partial", "lambda",
    ],
)
def test_the_contract_accepts(handler, declared) -> None:
    assert run_parameters(handler) == declared


def _positional_config(manifest, obligation_id, config: CoreConfig):
    return None


def _unannotated(manifest, obligation_id, *, config):
    return None


def _wrong_type(manifest, obligation_id, *, ports: CoreConfig):
    return None


def _misspelled(manifest, obligation_id, *, cfg: CoreConfig):
    return None


#: A class with the run type's name, from somewhere else.
elsewhere = SimpleNamespace(CoreConfig=type("CoreConfig", (), {}))


def _homonym(manifest, obligation_id, *, config: elsewhere.CoreConfig):
    return None


def _unresolvable(manifest, obligation_id, *, config: Missing):  # noqa: F821
    return None


def _misspelled_quoted(manifest, obligation_id, *, cfg: "CoreConfig" = None):  # noqa: UP037 - the quotes are the case
    return None


def _misspelled_unresolvable(manifest, obligation_id, *, cfg: nowhere.CoreConfig = None):  # noqa: F821
    return None


def _required_unknown(manifest, obligation_id, *, budget: int):
    return None


def _one_positional(manifest):
    return None


def _three_positionals(manifest, obligation_id, extra):
    return None


@pytest.mark.parametrize(
    ("handler", "message"),
    [
        (_positional_config, "`config` must be keyword-only"),
        (_unannotated, "`config` must be annotated `CoreConfig`"),
        (_wrong_type, "`ports` must be annotated `RunPorts`"),
        (_misspelled, "`cfg` is annotated `CoreConfig`, but a run binds it only as `config`"),
        (_homonym, "`config` must be annotated `CoreConfig` (`acessilia_core.config.CoreConfig`)"),
        (_unresolvable, "`config` must be annotated `CoreConfig`"),
        (_misspelled_quoted, "`cfg` is annotated `CoreConfig`, but a run binds it only as `config`"),
        (_misspelled_unresolvable, "`cfg` is annotated `CoreConfig`"),
        (_required_unknown, "`budget` is a required keyword-only parameter that no run binds"),
        (_one_positional, "must accept (manifest, obligation_id) positionally"),
        (_three_positionals, "requires 3 positional parameters (manifest, obligation_id, extra)"),
    ],
    ids=[
        "positional", "unannotated", "wrong-type", "misspelled", "homonym", "unresolvable",
        "misspelled-quoted", "misspelled-unresolvable", "required-unknown", "one", "three",
    ],
)
def test_the_contract_rejects(handler, message) -> None:
    with pytest.raises(HandlerContractError) as raised:
        run_parameters(handler)

    assert message in str(raised.value)
    assert handler.__name__ in str(raised.value)


def test_every_broken_rule_is_reported_at_once() -> None:
    def twice_broken(manifest, *, config, cfg: RunPorts):
        return None

    with pytest.raises(HandlerContractError) as raised:
        run_parameters(twice_broken)

    message = str(raised.value)
    for part in ("must accept", "`config` must be annotated", "`cfg` is annotated `RunPorts`"):
        assert part in message


class _Unreadable:
    """A callable whose signature ``inspect`` cannot read."""

    __signature__ = "not a signature"

    def __call__(self, manifest, obligation_id):
        return None


def test_a_handler_whose_signature_cannot_be_read_is_refused() -> None:
    registry = MethodRegistry()
    registry.register("unreadable", _Unreadable())

    with pytest.raises(HandlerContractError, match="its signature cannot be read"):
        bind_run(registry, core_config(), RunPorts.none())


def _pipeline_execute(monkeypatch, tmp_path, handlers: dict) -> MethodRegistry:
    """Run ``pddl_pipeline execute`` with a handler module, up to the executor."""
    from scripts import pddl_pipeline

    module = ModuleType("pipeline_contract_handlers")
    module.register_handlers = lambda registry: [
        registry.register(method, handler) for method, handler in handlers.items()
    ]
    monkeypatch.setitem(sys.modules, module.__name__, module)
    for name in ("ProcessingManifest", "NominalPlan"):
        monkeypatch.setattr(pddl_pipeline, name, SimpleNamespace(model_validate_json=lambda _text: None))
    received = []

    class Stop(Exception):
        pass

    def executor(registry, **_kwargs):
        received.append(registry)
        raise Stop

    monkeypatch.setattr(pddl_pipeline, "ExecutorAgent", executor)
    monkeypatch.setattr(pddl_pipeline, "DomainBundle", SimpleNamespace(load=lambda *_args: None))
    (tmp_path / "m.json").write_text("{}", encoding="utf-8")
    args = argparse.Namespace(
        manifest=tmp_path / "m.json",
        plan=tmp_path / "m.json",
        handler_module=module.__name__,
        domain=None,
        domain_description=None,
    )
    with pytest.raises(Stop):
        pddl_pipeline._run_execute(args)
    return received[0]


def test_the_pipeline_cli_binds_its_handler_module_like_a_run(monkeypatch, tmp_path) -> None:
    def with_config(manifest, obligation_id, *, config: CoreConfig):
        return config

    registry = _pipeline_execute(monkeypatch, tmp_path, {"vision-description": with_config})

    assert isinstance(registry.get("vision-description")(None, "o"), CoreConfig)


def test_the_pipeline_cli_refuses_a_handler_module_that_breaks_the_contract(monkeypatch, tmp_path) -> None:
    def broken(manifest, obligation_id, *, budget: int):
        return None

    with pytest.raises(HandlerContractError, match="`budget` is a required keyword-only"):
        _pipeline_execute(monkeypatch, tmp_path, {"vision-description": broken})
