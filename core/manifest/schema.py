from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from core.manifest.models import ProcessingManifest


def processing_manifest_schema() -> dict[str, Any]:
    return ProcessingManifest.model_json_schema(
        by_alias=True,
        mode="validation",
    )


def write_processing_manifest_schema(destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(processing_manifest_schema(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return destination


def validate_manifest(
    payload: dict[str, Any],
    schema_path: Path | None = None,
) -> list[str]:
    """Valida o contrato Pydantic e, opcionalmente, o Schema versionado."""
    errors: list[str] = []
    try:
        ProcessingManifest.model_validate(payload)
    except ValidationError as exc:
        errors.extend(
            f"{'.'.join(map(str, error['loc']))}: {error['msg']}"
            for error in exc.errors()
        )

    if schema_path is not None:
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            errors.append(
                "A dependência jsonschema não está instalada; "
                "não foi possível validar o arquivo de schema."
            )
        else:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
            validator = Draft202012Validator(schema)
            errors.extend(
                f"{'.'.join(map(str, error.absolute_path)) or '$'}: {error.message}"
                for error in sorted(
                    validator.iter_errors(payload),
                    key=lambda item: list(item.absolute_path),
                )
            )
    return errors
