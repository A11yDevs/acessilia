from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path


DEFAULT_DOMAIN_DIR = Path(__file__).resolve().parent / "domains"
DEFAULT_DOMAIN_PATH = DEFAULT_DOMAIN_DIR / "domain_v2.2.pddl"
DEFAULT_DESCRIPTION_PATH = DEFAULT_DOMAIN_DIR / "domain_description_v2.2.md"


@dataclass(frozen=True)
class DomainBundle:
    domain_path: Path
    description_path: Path
    name: str
    version: str
    domain_sha256: str
    description_sha256: str

    @classmethod
    def load(
        cls,
        domain_path: Path = DEFAULT_DOMAIN_PATH,
        description_path: Path = DEFAULT_DESCRIPTION_PATH,
    ) -> "DomainBundle":
        domain_path = domain_path.resolve()
        description_path = description_path.resolve()
        if not domain_path.is_file():
            raise FileNotFoundError(f"Domínio PDDL não encontrado: {domain_path}")
        if not description_path.is_file():
            raise FileNotFoundError(
                f"Descrição do domínio não encontrada: {description_path}"
            )

        domain_text = domain_path.read_text(encoding="utf-8")
        description_text = description_path.read_text(encoding="utf-8")
        name_match = re.search(
            r"\(define\s+\(domain\s+([a-zA-Z0-9_-]+)\)",
            domain_text,
            re.IGNORECASE,
        )
        domain_version = re.search(
            r"^\s*;;\s*Version\s+([0-9]+(?:\.[0-9]+)*)",
            domain_text,
            re.MULTILINE | re.IGNORECASE,
        )
        description_version = re.search(
            r"\*\*Versão:\*\*\s*([0-9]+(?:\.[0-9]+)*)",
            description_text,
            re.IGNORECASE,
        )
        if not name_match:
            raise ValueError("Nome do domínio ausente ou inválido")
        if not domain_version or not description_version:
            raise ValueError("Versão ausente no domínio ou em sua descrição")
        if domain_version.group(1) != description_version.group(1):
            raise ValueError(
                "Versões divergentes: "
                f"PDDL={domain_version.group(1)}; "
                f"descrição={description_version.group(1)}"
            )

        required_domain_fragments = (
            "(selected ?o - obligation)",
            "(:derived (ready ?o - obligation)",
            "(:action execute-obligation",
            "(increase (total-cost) (execution-cost ?m ?o))",
            "(:action complete-job",
        )
        missing = [
            fragment
            for fragment in required_domain_fragments
            if fragment not in domain_text
        ]
        if missing:
            raise ValueError(
                "O domínio não implementa o contrato 2.2: "
                + ", ".join(missing)
            )

        required_description_fragments = (
            "fechamento transitivo",
            "(:metric minimize (total-cost))",
            "plano nominal",
        )
        missing_description = [
            fragment
            for fragment in required_description_fragments
            if fragment.lower() not in description_text.lower()
        ]
        if missing_description:
            raise ValueError(
                "A descrição não documenta o contrato exigido: "
                + ", ".join(missing_description)
            )

        return cls(
            domain_path=domain_path,
            description_path=description_path,
            name=name_match.group(1),
            version=domain_version.group(1),
            domain_sha256=_sha256(domain_path),
            description_sha256=_sha256(description_path),
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
