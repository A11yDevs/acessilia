"""The method registry: which handler runs each obligation method.

``METHOD_HANDLERS`` maps every method the executor can run to its handler;
``build_method_registry`` registers them. The registry looks a handler up by
its method's name, so the table's order does not change what runs; it keeps
the order ``_build_executor`` used, for the reader. A
method the manifest can require but that is absent here is reported to the
planner as unavailable: no step only fails. Gathered from the orchestrator's
``DETERMINISTIC_METHOD_HANDLERS`` and the registrations of its
``_build_executor`` (#402, phase 3, step 6), without changing a single
method-handler pair.
"""

from __future__ import annotations

import ast
import inspect
import sys
import typing
from collections.abc import Callable, Mapping
from functools import partial

from acessilia_core.config import CoreConfig
from acessilia_core.execution.executor import MethodRegistry
from acessilia_core.execution.models import MethodResult
from acessilia_core.manifest.models import ProcessingManifest
from acessilia_core.pipeline.handlers.content import (
    _handle_pandoc_code_method,
    _handle_pandoc_table_method,
    _handle_vision_description_method,
)
from acessilia_core.pipeline.handlers.formula import (
    _handle_latex_normalizer_method,
    _handle_latex_verbalizer_method,
    _handle_mathml_method,
)
from acessilia_core.pipeline.handlers.fusion import (
    _handle_agreement_rule_method,
    _handle_dual_provider_fusion_method,
    _handle_single_provider_method,
    _handle_table_smart_fusion_method,
)
from acessilia_core.pipeline.handlers.inspection import (
    _handle_pymupdf_region_method,
    _handle_vision_page_inspection_method,
)
from acessilia_core.pipeline.handlers.judge import (
    _handle_vlm_pairwise_judge_method,
)
from acessilia_core.pipeline.handlers.order import (
    _handle_skeleton_order_method,
    _handle_xycut_order_method,
)
from acessilia_core.pipeline.handlers.rescue import (
    _handle_rescue_omitted_method,
)
from acessilia_core.pipeline.handlers.review import (
    _handle_human_review_method,
)
from acessilia_core.pipeline.handlers.text import (
    _handle_chunk_verse_method,
    _handle_deterministic_heading_repair_method,
    _handle_extract_line_numbers_method,
    _handle_norm_fix_method,
    _handle_repetition_guard_method,
    _handle_tailjoin_method,
    _handle_unicode_repair_method,
)
from acessilia_core.ports import RunPorts

#: Method name -> handler.
METHOD_HANDLERS: dict[str, Callable[[ProcessingManifest, str], MethodResult]] = {
    # Methods that call a Toolbox capability or a model and fail explicitly
    # when it is unavailable, and the provider fusion and choice.
    "mathml": _handle_mathml_method,
    "latex-verbalizer": _handle_latex_verbalizer_method,
    "dual-provider-fusion": _handle_dual_provider_fusion_method,
    "single-provider": _handle_single_provider_method,
    "vlm-pairwise-judge": _handle_vlm_pairwise_judge_method,
    # Work done before planning, deterministic work, or one vision model call
    # (pymupdf-region, vision-page-inspection).
    "vision-description": _handle_vision_description_method,
    "pandoc-table": _handle_pandoc_table_method,
    "pandoc-code": _handle_pandoc_code_method,
    "pymupdf-region": _handle_pymupdf_region_method,
    "vision-page-inspection": _handle_vision_page_inspection_method,
    "latex-normalizer": _handle_latex_normalizer_method,
    "norm-fix": _handle_norm_fix_method,
    "unicode-repair": _handle_unicode_repair_method,
    "rep-guard": _handle_repetition_guard_method,
    "line-number-extractor": _handle_extract_line_numbers_method,
    "verse-chunker": _handle_chunk_verse_method,
    "tailjoin": _handle_tailjoin_method,
    "tailjoin-positioned": _handle_tailjoin_method,
    "xycut-order": _handle_xycut_order_method,
    "skeleton-order": _handle_skeleton_order_method,
    "rescue-omitted": _handle_rescue_omitted_method,
    "table-smart-fusion": _handle_table_smart_fusion_method,
    "agreement-rule": _handle_agreement_rule_method,
    "deterministic-heading-repair": _handle_deterministic_heading_repair_method,
    # `human-review` has its own semantics: it is the terminal escalation the
    # pipeline performs when no automated method can satisfy an obligation.
    "human-review": _handle_human_review_method,
}


def build_method_registry() -> MethodRegistry:
    """A ``MethodRegistry`` with every method of ``METHOD_HANDLERS``.

    Each handler's contract is checked here (``run_parameters``), so a
    handler that breaks it fails when the executor is built, not when a plan
    first runs it (#543).
    """
    registry = MethodRegistry()
    for method, handler in METHOD_HANDLERS.items():
        run_parameters(handler)
        registry.register(method, handler)
    return registry


#: What a run binds to a handler: the parameter's name and its type.
RUN_PARAMETERS: dict[str, type] = {"config": CoreConfig, "ports": RunPorts}


class HandlerContractError(TypeError):
    """A method handler whose signature the executor or a run cannot call."""


#: An annotation that cannot be resolved to an object.
_UNRESOLVED = object()


def _namespace(handler: Callable[..., object]) -> Mapping[str, object]:
    """The globals a handler's string annotations are resolved in."""
    target = handler.func if isinstance(handler, partial) else handler
    found = getattr(target, "__globals__", None)
    if found is None:
        module = sys.modules.get(getattr(target, "__module__", "") or "")
        found = vars(module) if module is not None else {}
    return found


def _unwrap(annotation: object) -> object:
    """``Annotated[X, ...]`` is ``X``."""
    if typing.get_origin(annotation) is typing.Annotated:
        return typing.get_args(annotation)[0]
    return annotation


def _resolve(annotation: object, namespace: Mapping[str, object]) -> object:
    """The object ``annotation`` names, or ``_UNRESOLVED`` (review of #581).

    Handler modules use ``from __future__ import annotations``, so their
    annotations are strings. They are resolved in the handler's module,
    without evaluating code: names, dotted attributes, quoted strings
    (``"CoreConfig"``) and ``Annotated[X, ...]``. The resolved object is then
    compared by identity, so a homonym from another module never matches.
    """
    if not isinstance(annotation, str):
        return _unwrap(annotation)
    try:
        node = ast.parse(annotation.strip(), mode="eval").body
    except SyntaxError:
        return _UNRESOLVED
    return _resolve_node(node, namespace)


def _resolve_node(node: ast.expr, namespace: Mapping[str, object]) -> object:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return _resolve(node.value, namespace)
    if isinstance(node, ast.Name):
        return _unwrap(namespace[node.id]) if node.id in namespace else _UNRESOLVED
    if isinstance(node, ast.Attribute):
        base = _resolve_node(node.value, namespace)
        if base is _UNRESOLVED:
            return _UNRESOLVED
        return _unwrap(getattr(base, node.attr, _UNRESOLVED))
    if isinstance(node, ast.Subscript) and _resolve_node(node.value, namespace) is typing.Annotated:
        first = node.slice.elts[0] if isinstance(node.slice, ast.Tuple) else node.slice
        return _resolve_node(first, namespace)
    return _UNRESOLVED


def _names_a_run_type(annotation: object, resolved: object) -> str | None:
    """The run parameter whose type ``annotation`` names, if any.

    An annotation that cannot be resolved still counts when it spells a run
    type's name, so a misspelled parameter is not let through for want of an
    import.
    """
    for name, kind in RUN_PARAMETERS.items():
        if resolved is kind:
            return name
    if resolved is _UNRESOLVED and isinstance(annotation, str):
        spelled = annotation.strip().strip("\"'").rsplit(".", 1)[-1]
        for name, kind in RUN_PARAMETERS.items():
            if spelled == kind.__name__:
                return name
    return None


def _handler_name(handler: Callable[..., object]) -> str:
    target = handler.func if isinstance(handler, partial) else handler
    return getattr(target, "__qualname__", repr(target))


def run_parameters(handler: Callable[..., MethodResult]) -> tuple[str, ...]:
    """The run parameters ``handler`` declares, after checking its contract (#543).

    The executor calls a handler as ``handler(manifest, obligation_id)``, and
    a run binds what the handler declares of ``RUN_PARAMETERS``. The contract:

    - it accepts ``(manifest, obligation_id)`` positionally, and requires no
      other positional parameter;
    - a run parameter is keyword-only (after ``*``) and annotated with its
      type: ``*, config: CoreConfig``, ``*, ports: RunPorts``;
    - no other parameter is annotated ``CoreConfig`` or ``RunPorts``: a
      misspelled name (``cfg: CoreConfig``) would never be bound;
    - no other keyword-only parameter is required, since nothing would pass it.

    An annotation is resolved in the handler's module and compared by
    identity (``_resolve``).

    Raises ``HandlerContractError`` naming every broken rule, and when the
    handler's signature cannot be read, since then nothing can be checked.
    """
    try:
        parameters = list(inspect.signature(handler).parameters.values())
    except (TypeError, ValueError) as exc:
        raise HandlerContractError(
            f"method handler {_handler_name(handler)}: its signature cannot be read ({exc})"
        ) from exc
    namespace = _namespace(handler)
    positional = [
        p for p in parameters
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    takes_any = any(p.kind is inspect.Parameter.VAR_POSITIONAL for p in parameters)
    problems = []
    if len(positional) < 2 and not takes_any:
        problems.append("it must accept (manifest, obligation_id) positionally")
    required = [p.name for p in positional if p.default is inspect.Parameter.empty]
    if len(required) > 2:
        problems.append(
            f"it requires {len(required)} positional parameters ({', '.join(required)}); "
            "the executor passes two"
        )
    declared = []
    for parameter in parameters:
        expected = RUN_PARAMETERS.get(parameter.name)
        if expected is not None:
            if parameter.kind is not inspect.Parameter.KEYWORD_ONLY:
                problems.append(f"`{parameter.name}` must be keyword-only (after `*`)")
            elif _resolve(parameter.annotation, namespace) is not expected:
                problems.append(
                    f"`{parameter.name}` must be annotated `{expected.__name__}` "
                    f"(`{expected.__module__}.{expected.__qualname__}`)"
                )
            else:
                declared.append(parameter.name)
            continue
        misnamed = _names_a_run_type(
            parameter.annotation, _resolve(parameter.annotation, namespace)
        )
        if misnamed:
            problems.append(
                f"`{parameter.name}` is annotated `{RUN_PARAMETERS[misnamed].__name__}`, "
                f"but a run binds it only as `{misnamed}`"
            )
        elif (
            parameter.kind is inspect.Parameter.KEYWORD_ONLY
            and parameter.default is inspect.Parameter.empty
        ):
            problems.append(
                f"`{parameter.name}` is a required keyword-only parameter that no run binds "
                f"(a run binds {', '.join(f'`{name}`' for name in RUN_PARAMETERS)})"
            )
    if problems:
        raise HandlerContractError(
            f"method handler {_handler_name(handler)}: " + "; ".join(problems)
        )
    return tuple(declared)


def bind_run(registry: MethodRegistry, config: CoreConfig, ports: RunPorts) -> MethodRegistry:
    """The registry of one run (ADR-0016, steps 3 and 4).

    A handler that declares ``config`` gets the run's ``CoreConfig`` bound,
    and one that declares ``ports`` gets its ``RunPorts``; the others are
    registered as they are, so the executor keeps calling every handler as
    ``handler(manifest, obligation_id)``. The copy keeps the registration
    order, and the given registry is left unchanged.

    A handler opts in by declaring ``*, config: CoreConfig`` or
    ``*, ports: RunPorts``. Every handler's contract is checked
    (``run_parameters``) before any is bound, so a broken one fails the run
    before its first step.
    """
    values = {"config": config, "ports": ports}
    declared = [(method, handler, run_parameters(handler)) for method, handler in registry.items()]
    bound = MethodRegistry()
    for method, handler, names in declared:
        given = {name: values[name] for name in names}
        bound.register(method, partial(handler, **given) if given else handler)
    return bound


__all__ = [
    "METHOD_HANDLERS",
    "RUN_PARAMETERS",
    "HandlerContractError",
    "bind_run",
    "build_method_registry",
    "run_parameters",
]
