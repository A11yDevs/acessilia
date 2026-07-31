#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from core.agents.informational_structural import InformationalStructuralAgent
from core.manifest.docling_extractor import DoclingManifestExtractor
from core.manifest.schema import validate_manifest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCHEMA = PROJECT_ROOT / "schemas" / "processing_manifest.schema.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="a11y-manifest",
        description=(
            "Extrai a estrutura de um documento com Docling e gera um "
            "manifesto de processamento validado."
        ),
    )
    parser.add_argument("document", type=Path, help="Documento de entrada.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="JSON de saída (padrão: <documento>.processing-manifest.json).",
    )
    parser.add_argument(
        "--language",
        default="pt-BR",
        help="Idioma BCP 47 assumido para o documento (padrão: pt-BR).",
    )
    parser.add_argument(
        "--no-ocr",
        action="store_true",
        help="Desabilita OCR no pipeline PDF do Docling.",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=DEFAULT_SCHEMA,
        help="Schema usado na validação Draft 2020-12.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source = args.document.resolve()
    output = (
        args.output.resolve()
        if args.output
        else source.with_suffix(".processing-manifest.json")
    )

    try:
        agent = InformationalStructuralAgent(
            DoclingManifestExtractor(enable_ocr=not args.no_ocr)
        )
        manifest = agent.process(source, language=args.language)
        payload = manifest.model_dump(mode="json", by_alias=True)
        errors = validate_manifest(payload, args.schema.resolve())
        if errors:
            print("Manifesto inválido:", file=sys.stderr)
            for error in errors:
                print(f"- {error}", file=sys.stderr)
            return 2

        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except Exception as exc:
        print(f"Erro: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"Manifesto válido: {output}")
    print(
        f"Páginas: {manifest.summary.page_count}; "
        f"elementos: {manifest.summary.element_count}; "
        f"obrigações candidatas: {manifest.summary.obligation_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
