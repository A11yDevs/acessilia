"""Bounded request snapshots for the published text-normalization@1 contract."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from acessilia_sdk.toolbox.errors import ToolboxContractViolation, ToolboxInvalidInput
from acessilia_sdk.toolbox.results._model import decode
from acessilia_sdk.toolbox.results._text_normalization_generated import (
    TextNormalizationRequest,
    TextNormalizationRequestTargetsItem as TextTarget,
    TextNormalizationResult,
    TextNormalizationResultResultsItem as TextObservation,
)

CAPABILITY = "document.text.normalize"
PROVIDER_VERSION = "1.0.0"
DOCSTRUCT_VERSION = "0.5.8"
MAX_TARGETS = TextNormalizationRequest._rule["properties"]["targets"]["maxItems"]
# Published adapter limit; it covers the complete serialized request, not text length.
MAX_PAYLOAD_BYTES = 1_048_576
_PREFIX, _SUFFIX = b'{"targets":[', b"]}"


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def fingerprint(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def target_fingerprint(target: TextTarget) -> str:
    return fingerprint(canonical_json({"id": target.id, "text": target.text}))


@dataclass(frozen=True)
class NormalizationBatch:
    """An immutable original request, reused unchanged by HTTP retries."""

    targets: tuple[TextTarget, ...]
    payload: bytes


@dataclass(frozen=True)
class NormalizedBatch:
    observations: tuple[TextObservation, ...]
    processed_count: int
    changed_count: int
    provenance: NormalizationProvenance


@dataclass(frozen=True)
class NormalizationProvenance:
    provider: str
    provider_version: str
    runtime: str
    docstruct: str
    norm_fix: str
    input_fingerprint: str


def normalization_batches(
    targets: Sequence[TextTarget],
) -> tuple[NormalizationBatch, ...]:
    """Partition by count and actual UTF-8 bytes, without splitting a target's text."""
    batches: list[NormalizationBatch] = []
    pending: list[TextTarget] = []
    parts: list[bytes] = []
    size = len(_PREFIX) + len(_SUFFIX)
    seen: set[str] = set()
    try:
        for item in targets:
            target = decode(
                item.to_dict(),
                TextTarget._rule,
                TextTarget._models,
                "target",
                strict=True,
            )
            encoded = canonical_json(target.to_dict())
            if target.id in seen:
                raise ValueError("normalization target ids must be unique")
            seen.add(target.id)
            if len(_PREFIX) + len(encoded) + len(_SUFFIX) > MAX_PAYLOAD_BYTES:
                raise ValueError(
                    "one normalization target exceeds the serialized byte limit"
                )
            if pending and (
                len(pending) == MAX_TARGETS
                or size + 1 + len(encoded) > MAX_PAYLOAD_BYTES
            ):
                batches.append(
                    NormalizationBatch(
                        tuple(pending), _PREFIX + b",".join(parts) + _SUFFIX
                    )
                )
                pending, parts, size = [], [], len(_PREFIX) + len(_SUFFIX)
            size += len(encoded) + bool(pending)
            pending.append(target)
            parts.append(encoded)
        if pending:
            batches.append(
                NormalizationBatch(tuple(pending), _PREFIX + b",".join(parts) + _SUFFIX)
            )
    except (ValueError, TypeError, AttributeError) as exc:
        raise ToolboxInvalidInput(f"Invalid normalization targets: {exc}") from exc
    return tuple(batches)


def read_normalization(
    envelope: Any, batch: NormalizationBatch, *, provider: str
) -> NormalizedBatch:
    """Validate contract, provenance and observations against the immutable input."""
    try:
        _check_provenance(envelope, batch, provider)
        result = decode(
            envelope["document"],
            TextNormalizationResult._rule,
            TextNormalizationResult._models,
            "normalization result",
            strict=True,
        )
        observations = tuple(result.results)
        if tuple(item.id for item in observations) != tuple(
            item.id for item in batch.targets
        ):
            raise ValueError("normalization result ids/order differ from the request")
        for target, item in zip(batch.targets, observations):
            _check_observation(target, item)
        if result.processed_count != sum(item.processed for item in observations):
            raise ValueError(
                "normalization processed_count disagrees with observations"
            )
        if result.changed_count != sum(item.changed for item in observations):
            raise ValueError("normalization changed_count disagrees with observations")
        versions = envelope["provenance"]["model_versions"]
        provenance = NormalizationProvenance(
            provider,
            PROVIDER_VERSION,
            versions["runtime"],
            versions["docstruct"],
            versions["norm_fix"],
            fingerprint(batch.payload),
        )
        return NormalizedBatch(
            observations, result.processed_count, result.changed_count, provenance
        )
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise ToolboxContractViolation(f"Invalid {CAPABILITY} response: {exc}") from exc


def _check_observation(target: TextTarget, item: TextObservation) -> None:
    if item.input_fingerprint != target_fingerprint(target):
        raise ValueError("normalization observation has a different input fingerprint")
    if item.processed != bool(target.text) or item.changed != (
        item.text != target.text
    ):
        raise ValueError("normalization observation flags disagree with input/output")
    if (not item.processed and item.text != target.text) or (
        target.text is not None and item.text is None
    ):
        raise ValueError("normalization observation did not preserve empty/null input")
    if item.text is not None:
        item.text.encode("utf-8")


def _check_provenance(envelope: Any, batch: NormalizationBatch, provider: str) -> None:
    if not isinstance(envelope, dict) or (
        envelope.get("status"),
        envelope.get("capability"),
        envelope.get("provider"),
    ) != ("succeeded", CAPABILITY + "@1", provider):
        raise ValueError("unexpected normalization response identity/status")
    provenance = envelope["provenance"]
    if not isinstance(provenance, dict) or (
        provenance.get("capability"),
        provenance.get("capability_version"),
        provenance.get("provider"),
        provenance.get("provider_version"),
    ) != (CAPABILITY, 1, provider, PROVIDER_VERSION):
        raise ValueError("unexpected normalization provenance identity/version")
    if type(provenance["capability_version"]) is not int:
        raise ValueError("normalization capability_version must be an integer")
    versions = provenance["model_versions"]
    if not isinstance(versions, dict) or (
        versions.get("docstruct"),
        versions.get("norm_fix"),
    ) != (DOCSTRUCT_VERSION, DOCSTRUCT_VERSION):
        raise ValueError("unexpected normalization algorithm/component versions")
    if not isinstance(versions.get("runtime"), str) or not versions["runtime"]:
        raise ValueError("missing normalization runtime version")
    if provenance.get("input_fingerprints") != [fingerprint(batch.payload)]:
        raise ValueError(
            "normalization provenance does not identify the submitted payload"
        )
    if provenance.get("parameters_hash") != fingerprint(canonical_json({})):
        raise ValueError("normalization provenance has unexpected parameters")


__all__ = [
    "CAPABILITY",
    "DOCSTRUCT_VERSION",
    "PROVIDER_VERSION",
    "MAX_PAYLOAD_BYTES",
    "MAX_TARGETS",
    "NormalizationBatch",
    "NormalizationProvenance",
    "NormalizedBatch",
    "TextObservation",
    "TextTarget",
    "canonical_json",
    "fingerprint",
    "normalization_batches",
    "read_normalization",
    "target_fingerprint",
]
