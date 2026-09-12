"""Reconhecedor descartável da cascata; imports de modelo apenas no filho."""

from __future__ import annotations

import io
import json
import os
import sys


def _recognize(image_bytes: bytes) -> str:
    from PIL import Image

    from docling.datamodel.accelerator_options import AcceleratorOptions
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.models.inference_engines.vlm import VlmEngineInput
    from docling.models.stages.code_formula.code_formula_vlm_model import CodeFormulaVlmModel

    options = PdfPipelineOptions().code_formula_options.model_copy(
        update={"extract_code": False, "extract_formulas": True}
    )
    model = CodeFormulaVlmModel(
        enabled=True,
        enable_remote_services=False,
        artifacts_path=None,
        options=options,
        accelerator_options=AcceleratorOptions(),
    )
    if model.engine is None:
        return ""
    with Image.open(io.BytesIO(image_bytes)) as source:
        image = source.convert("RGB")
        with image:
            engine_input = VlmEngineInput(
                image=image,
                prompt="<formula>",
                temperature=0.0,
                max_new_tokens=512,
                extra_generation_config={"skip_special_tokens": False},
            )
            outputs = model.engine.predict_batch([engine_input])
            return model._post_process([outputs[0].text])[0].strip()


def main() -> int:
    """Escreve um único resultado limitado; logs do modelo não são protocolo."""
    try:
        with os.fdopen(int(sys.argv[1]), "wb") as result:
            latex = _recognize(sys.stdin.buffer.read())
            if not isinstance(latex, str) or len(latex) > 2000:
                return 1
            payload = json.dumps({"latex": latex}, ensure_ascii=False).encode("utf-8")
            if len(payload) > 8192:
                return 1
            result.write(payload)
        return 0
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())