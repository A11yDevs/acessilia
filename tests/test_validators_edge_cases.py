"""Testes exploratorios de validacao de upload (backend/tools/validators.py).

Valida is_extension_allowed / validate_file em casos de borda: extensoes
perigosas, dupla extensao, maiusculas e limite de tamanho. Documenta tambem
um quirk de baixo risco (payload.exe.pdf e aceito).

Sugestao de destino no repo: tests/test_validators_edge_cases.py
"""
from __future__ import annotations

import pytest

from backend.config.settings import settings
from backend.tools import validators


@pytest.fixture(autouse=True)
def _pddl_engine(monkeypatch):
    # o motor legacy foi desativado; garante o caminho atual (pddl)
    monkeypatch.setattr(settings, "pipeline_engine", "pddl")


LIMIT = settings.max_file_size_bytes


@pytest.mark.parametrize(
    "name", ["a.exe", "a.bat", "a.sh", "a.js", "a.php", "a.bin", "a.cmd"]
)
def test_rejeita_extensoes_perigosas(name):
    ok, msg = validators.validate_file(name, 10)
    assert ok is False and msg


def test_rejeita_sem_extensao():
    ok, _ = validators.validate_file("arquivo_sem_extensao", 10)
    assert ok is False


@pytest.mark.parametrize(
    "name",
    [
        "doc.pdf", "img.png", "img.JPG", "img.Jpeg", "scan.TIFF",
        "x.webp", "planilha.docx", "pagina.html", "foto.gif",
    ],
)
def test_aceita_extensoes_permitidas_case_insensitive(name):
    ok, msg = validators.validate_file(name, 10)
    assert ok is True and msg == ""


def test_dupla_extensao_perigosa_no_final_e_barrada():
    # a extensao efetiva e a ultima (.exe) -> barrado (bom)
    ok, _ = validators.validate_file("malware.pdf.exe", 10)
    assert ok is False


def test_quirk_extensao_perigosa_no_meio_passa():
    # QUIRK conhecido / baixo risco: so a ULTIMA extensao conta, entao
    # "payload.exe.pdf" e aceito. O conteudo nao e executado (vira artefato),
    # mas vale registrar. Este teste DOCUMENTA o comportamento atual.
    ok, _ = validators.validate_file("payload.exe.pdf", 10)
    assert ok is True


def test_tamanho_exatamente_no_limite_e_aceito():
    ok, _ = validators.validate_file("doc.pdf", LIMIT)
    assert ok is True


def test_tamanho_acima_do_limite_e_barrado():
    ok, msg = validators.validate_file("doc.pdf", LIMIT + 1)
    assert ok is False and msg
