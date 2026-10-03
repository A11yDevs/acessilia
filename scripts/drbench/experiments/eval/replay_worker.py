"""Run in a subprocess with PYTHONPATH pointing at the frozen variant."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--variant", choices=("baseline", "candidate"), required=True)
    args = parser.parse_args()
    from acessilia_toolbox.core.normalization.builder import build_processing_manifest
    from acessilia_toolbox.core.normalization.extraction import ExtractionResult
    from acessilia_toolbox.providers.docling_document import DoclingServeDocument
    from acessilia_toolbox.providers.mineru_document import MineruDocument
    from docstruct.policy import FusionPolicy
    from scripts.drbench.markdown_converter import canonical_to_drbench_md
    from scripts.drbench.run_pipeline import provider_blocks, provider_payload_to_canonical

    root = args.run.resolve()
    manifest = json.loads((root / "manifest.json").read_text())
    variant = manifest["variants"][args.variant]
    policy = {"v12": FusionPolicy.drbench_v12, "v13": FusionPolicy.drbench_v13,
              "default": FusionPolicy}[variant["policy"]]()
    out = root / args.variant
    out.mkdir(exist_ok=True)
    (out / "policy.json").write_text(json.dumps(policy.to_dict(), indent=2) + "\n")
    versions = manifest["inference"].get("versions", {})
    for page in json.loads((root / "pages.json").read_text()):
        for name, cls in (("docling", DoclingServeDocument), ("mineru", MineruDocument)):
            raw = root / "raw" / name / f"{page['id']}.json"
            document = cls(json.loads(raw.read_text()))
            now = datetime.now(timezone.utc)
            extraction = ExtractionResult(
                document=document, backend=name, started_at=now, completed_at=now,
                duration_ms=0, version=versions.get(name, "unknown"),
                configuration={"extractor": "docling-serve" if name == "docling" else "mineru-api"},
            )
            result = {"document": build_processing_manifest(
                root / "data/hf" / page["image"], extraction, language=page.get("language", "en")
            ).model_dump(mode="json")}
            provider = out / name
            provider.mkdir(exist_ok=True)
            for suffix, value in (("provider.json", result), ("blocks.json", provider_blocks(result))):
                (provider / f"{page['id']}.{suffix}").write_text(json.dumps(value, ensure_ascii=False))
            (provider / f"{page['id']}.drbench.md").write_text(
                canonical_to_drbench_md(provider_payload_to_canonical(result))
            )
        print(page["id"], flush=True)


if __name__ == "__main__":
    main()
