"""Teste de regressao para a issue #99 - cruzamento de dados entre usuarios.

Vai ALEM dos testes que o PR #100 adicionou (que so checam o formato da chave e
o armazenamento do owner). Aqui provamos as PROPRIEDADES DE ISOLAMENTO de fato:

1. Cache: dois documentos distintos nunca retornam o payload um do outro.
2. Cache: a chave inclui hash SHA-256 completo (64 hex) + tamanho do arquivo.
3. Download token: dois jobs concorrentes (donos/dirs distintos) geram tokens
   distintos e cada token so devolve o proprio arquivo/dono - reproduzindo o
   cenario do #99 ("texto de outro usuario retornado").

Sugestao de destino no repo: tests/test_issue_99_cross_user.py
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from backend.config.settings import settings
from backend.services import cache as cache_module
from backend.services import download_token_service as token_service


@pytest.fixture(autouse=True)
def isolate_cache_and_tokens(monkeypatch, tmp_path):
    # cache isolado em pasta temporaria
    monkeypatch.setattr(cache_module, "CACHE_DIR", tmp_path / "cache")
    # banco de tokens isolado
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "temp_dir", tmp_path / "temp")
    token_service._connection = None
    yield
    if token_service._connection is not None:
        token_service._connection.close()
        token_service._connection = None


def test_cache_nao_cruza_dados_entre_documentos(tmp_path):
    """Doc A e Doc B (conteudos diferentes) nunca recebem o texto um do outro."""
    doc_a = tmp_path / "docA.pdf"
    doc_b = tmp_path / "docB.pdf"
    doc_a.write_bytes(b"conteudo do usuario A")
    doc_b.write_bytes(b"conteudo COMPLETAMENTE diferente do usuario B")

    asyncio.run(cache_module.set_cache(doc_a, "TEXTO_DO_A", extra="normal"))
    asyncio.run(cache_module.set_cache(doc_b, "TEXTO_DO_B", extra="normal"))

    assert asyncio.run(cache_module.get_cached(doc_a, extra="normal")) == "TEXTO_DO_A"
    assert asyncio.run(cache_module.get_cached(doc_b, extra="normal")) == "TEXTO_DO_B"


def test_cache_key_usa_hash_completo_e_tamanho(tmp_path):
    """Arquivos diferentes -> chaves diferentes; hash completo (64) + tamanho."""
    a = tmp_path / "a.bin"
    b = tmp_path / "b.bin"
    a.write_bytes(b"x" * 100)
    b.write_bytes(b"y" * 200)

    key_a = cache_module._cache_key(a, "opt")
    key_b = cache_module._cache_key(b, "opt")

    assert key_a != key_b
    digest, size, _extra = key_a.split("_", 2)
    assert len(digest) == 64          # SHA-256 completo (nao truncado em 16)
    assert size == "100"              # tamanho do arquivo entra na chave


def test_download_tokens_isolados_por_job(tmp_path):
    """Dois jobs (donos/dirs distintos) -> tokens distintos, cada um so devolve
    o proprio arquivo e o proprio dono (reproduz o cruzamento do #99)."""
    dir_a = tmp_path / "output" / "job-a"
    dir_b = tmp_path / "output" / "job-b"
    dir_a.mkdir(parents=True)
    dir_b.mkdir(parents=True)
    (dir_a / "doc.txt").write_text("resultado do A", encoding="utf-8")
    (dir_b / "doc.txt").write_text("resultado do B", encoding="utf-8")

    token_a = asyncio.run(token_service.criar_token(
        dir_a, "doc", formats=["txt"], task_id="task-A", owner="userA@x.com"))
    token_b = asyncio.run(token_service.criar_token(
        dir_b, "doc", formats=["txt"], task_id="task-B", owner="userB@x.com"))

    assert token_a != token_b

    info_a = asyncio.run(token_service.obter_info_token(token_a))
    info_b = asyncio.run(token_service.obter_info_token(token_b))

    # cada token aponta pro dono/tarefa certos
    assert info_a["owner"] == "userA@x.com" and info_a["task_id"] == "task-A"
    assert info_b["owner"] == "userB@x.com" and info_b["task_id"] == "task-B"

    # e para o arquivo do proprio job, nunca o do outro
    path_a = Path(info_a["formats"][0]["file_path"])
    path_b = Path(info_b["formats"][0]["file_path"])
    assert path_a != path_b
    assert path_a.read_text(encoding="utf-8") == "resultado do A"
    assert path_b.read_text(encoding="utf-8") == "resultado do B"
