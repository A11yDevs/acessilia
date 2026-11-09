# Histórico de alterações

Também disponível em **inglês (EUA)**: [English version](CHANGELOG.md)

O SDK é uma API pública para scripts e benchmarks (#402). As mudanças visíveis
para quem o usa ficam registradas aqui, das mais novas para as mais antigas.

## Não lançado

- **Adicionados** `ArtifactReference` (`acessilia_sdk.toolbox.reference`), o
  `artifact/reference@1` publicado, gerado a partir do schema da Toolbox; o
  `parse_reference`, que também confere `digest == artifact_id`; e o
  `ToolboxArtifactClient.upload_reference`. `upload()` e `ArtifactRef.parse`
  não mudam (#185).
- **Alterado** O `output_schema` e o `idempotent` do registro são gerados a
  partir do contrato publicado pela Toolbox, pelo
  `scripts/generate_sdk_bindings.py` do core (#213); os ids permitidos,
  versões, transportes, chaves de provider e rótulos continuam escritos à mão
  em `_selected(...)`. O `TOOLBOX_CAPABILITIES` não muda, campo a campo.
- **Alterado** Retries e failover valem só para capacidades que o registro
  marca como `idempotent` (ADR-0006, #406). Após um timeout ou uma instância
  indisponível, uma chamada a `dataset.sample` tem uma tentativa no primeiro
  endpoint e levanta o erro dessa tentativa; antes ela era reenviada, ao mesmo
  e a outro endpoint. As capacidades idempotentes mantêm retries, backoff e
  failover.
- **Alterado** `ToolboxCapability` tem um campo nomeado obrigatório `idempotent`,
  o `execution.idempotent` do manifesto na `contract_version`. Toda entrada do
  registro o define; só `dataset.sample` é `False` (#406). Quem monta o próprio
  `ToolboxCapability` precisa passá-lo.

## 0.2.0 (2026-11-09)

- **Adicionados** `ToolboxClientConfig` e `make_client` (`acessilia_sdk.toolbox.config`,
  também exportados por `acessilia_sdk.toolbox`). Quem chama monta toda a
  configuração do cliente como valores explícitos e recebe um cliente
  configurado, sem instalar o core. O `make_toolbox_client` do core passa a
  delegar a eles; os clientes que ele monta não mudam (#402, passo 1).
- **Adicionado** um teste que falha se algum módulo do SDK ler o ambiente do
  processo (`os.environ`, `os.getenv`, sob qualquer nome com que `os` seja
  importado), como pede a ADR-0002.
- `acessilia_sdk.__version__` informa 0.2.0, e um teste o mantém igual à
  versão do `pyproject.toml`.

## 0.1.0

A primeira versão, anterior a este histórico: o registro de capacidades, o
transporte, os clientes por capacidade, endpoints e failover, artefatos, o
catálogo, os helpers do gateway VLM e o `run_sync`.
