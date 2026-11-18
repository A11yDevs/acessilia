"""The method handlers' contract with the executor and the run (#543).

The executor calls a handler as ``handler(manifest, obligation_id)``, and a
run binds the ``config`` and ``ports`` the handler declares. These tests pin
that contract: every registered handler keeps it, a broken handler fails when
the registry is built or bound, not when a plan first runs it, and each rule
rejects what it is meant to.
"""

from __future__ import annotations

from functools import partial

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


def test_bind_run_checks_every_handler_before_binding_any() -> None:
    calls = []

    def fine(manifest, obligation_id, *, config: CoreConfig):
        calls.append(config)

    def broken(manifest, obligation_id, *, config):
        calls.append(config)

    registry = MethodRegistry()
    registry.register("fine", fine)
    registry.register("broken", broken)

    with pytest.raises(HandlerContractError, match=r"broken: `config` must be annotated `CoreConfig`"):
        bind_run(registry, core_config(), RunPorts.none())
    assert calls == [], "no handler runs"


def test_the_contract_error_is_a_type_error() -> None:
    assert issubclass(HandlerContractError, TypeError)


def _plain(manifest, obligation_id):
    return None


def _with_both(manifest, obligation_id, *, config: CoreConfig, ports: RunPorts):
    return config, ports


def _dotted(manifest, obligation_id, *, config: acessilia_core.config.CoreConfig):  # noqa: F821
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
        # A string annotation is compared by its last dotted name.
        (_dotted, ("config",)),
        # An optional keyword-only parameter is allowed; nothing binds it.
        (_optional_extra, ("config",)),
        (_anything, ()),
        # An already bound handler is bound again with the next run's values.
        (partial(_with_both, config="first", ports="first"), ("config", "ports")),
        (lambda manifest, obligation_id: None, ()),
    ],
    ids=["plain", "both", "dotted", "optional-extra", "var-args", "partial", "lambda"],
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
        (_required_unknown, "`budget` is a required keyword-only parameter that no run binds"),
        (_one_positional, "must accept (manifest, obligation_id) positionally"),
        (_three_positionals, "requires 3 positional parameters (manifest, obligation_id, extra)"),
    ],
    ids=["positional", "unannotated", "wrong-type", "misspelled", "required-unknown", "one", "three"],
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
