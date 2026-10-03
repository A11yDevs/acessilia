"""Run in a subprocess with PYTHONPATH pointing at the frozen variant."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


def run_fusion(root: Path, variant: str) -> None:
    # Historical CLIs have no config export. Capture their actual argparse result
    # while running them, so defaults and validation belong to that frozen CLI.
    from scripts.drbench.experiments.differ import lib_fuse

    settings = json.loads((root / "manifest.json").read_text())["variants"][variant]
    out = root / variant
    parse_args = argparse.ArgumentParser.parse_args

    def record_args(parser, *args, **kwargs):
        values = parse_args(parser, *args, **kwargs)
        policy = lib_fuse.policy_by_name(values.policy).to_dict()
        if values.garbage_frac is not None:
            policy["garbage_frac"] = values.garbage_frac
        config = {"resolved_fusion_args": {k: str(v) if isinstance(v, Path) else v
                                           for k, v in vars(values).items()},
                  "resolved_policy": policy}
        (out / "fusion-config.json").write_text(json.dumps(config, indent=2) + "\n")
        return values

    argv = ["lib_fuse", "--docling", str(out / "docling"), "--mineru", str(out / "mineru"),
            "--out", str(out / "fusion"), "--policy", settings["policy"], *settings["fusion_args"]]
    with patch.object(sys, "argv", argv), patch.object(argparse.ArgumentParser, "parse_args", record_args):
        lib_fuse.main()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--variant", choices=("baseline", "candidate"), required=True)
    parser.add_argument("--fuse", action="store_true")
    args = parser.parse_args()
    if args.fuse:
        run_fusion(args.run.resolve(), args.variant)
        return
    from acessilia_toolbox.core.normalization.builder import build_processing_manifest
    from acessilia_toolbox.core.normalization.extraction import ExtractionResult
    from acessilia_toolbox.providers.docling_document import DoclingServeDocument
    from acessilia_toolbox.providers.mineru_document import MineruDocument
    from scripts.drbench.markdown_converter import canonical_to_drbench_md
    from scripts.drbench.run_pipeline import provider_blocks, provider_payload_to_canonical

    root = args.run.resolve()
    manifest = json.loads((root / "manifest.json").read_text())
    native_order = manifest["variants"][args.variant].get("docling_native_order", False)
    out = root / args.variant
    out.mkdir(exist_ok=True)
    versions = manifest["inference"].get("versions", {})
    for page in json.loads((root / "pages.json").read_text()):
        for name, cls in (("docling", DoclingServeDocument), ("mineru", MineruDocument)):
            raw = root / "raw" / name / f"{page['id']}.json"
            options = {"native_order": True} if name == "docling" and native_order else {}
            document = cls(json.loads(raw.read_text()), **options)
            now = datetime.now(timezone.utc)
            extraction = ExtractionResult(
                document=document, backend=name, started_at=now, completed_at=now,
                duration_ms=0, version=versions.get(name, "unknown"),
                configuration={"extractor": "docling-serve" if name == "docling" else "mineru-api",
                               **({"native_reading_order": native_order} if name == "docling" else {})},
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
