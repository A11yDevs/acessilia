# Bibliotecas do Acessilia

Pacotes Python compartilhados que vivem neste repositório, ao lado do core (`backend`).

> Também disponível em **inglês (EUA)**: [English version](README.md) — versão autoritativa.

| Pacote | Diretório | Em uma frase |
|---|---|---|
| `acessilia-docstruct` | [docstruct/](docstruct/) | **O que** se calcula sobre um documento: algoritmos estruturais puros. |
| `acessilia-sdk` | [sdk/](sdk/) | **Como** o core pede à Toolbox que execute uma operação: contratos, transporte HTTP, clientes, referências de artefatos e failover. |

## docstruct vs. SDK

| | **acessilia-docstruct** | **acessilia-sdk** |
|---|---|---|
| **O que é** | Algoritmos de estrutura de documentos: tipos canônicos (`CanonicalDocument`, `BBox`…), ordem de leitura, fusão de vários provedores, normalização de texto e LaTeX, tabelas, validação | Acesso uniforme às capacidades da Toolbox: registro de contratos, transporte HTTP (`execute_capability`), clientes, catálogo, erros, referências de artefatos, retries e failover |
| **Natureza** | Pura: sem rede, arquivos, subprocess ou settings | Faz I/O: cliente HTTP assíncrono |
| **Dependências** | Nenhuma (`dependencies = []`) | `httpx` |
| **Quem usa** | O core (`backend/pipeline`, `tools`, `export`…) **e a Toolbox**, que roda esses algoritmos do lado dela | Só o core, para falar com a Toolbox |
| **Distribuição** | Wheel publicada em GitHub Release (`.github/workflows/docstruct-release.yml`, tags `docstruct-v*`); a Toolbox a fixa por hash | Instalada em modo editável, só dentro deste repositório |
| **Restrição de imports** (`tests/test_purity.py`) | Não pode importar `backend`, `acessilia_toolbox` nem `acessilia_sdk` | Não pode importar `backend` nem `acessilia_toolbox` |

## Direção das dependências

```
backend (core) ──→ acessilia-sdk ──contrato HTTP──→ Toolbox
      │                  │                             │
      ▼                  ▼                             ▼
            acessilia-docstruct  ←─────────────────────┘
```

As dependências só apontam para baixo: a docstruct não importa nada acima dela,
a SDK nunca importa o core nem o pacote da Toolbox, e a Toolbox nunca importa a
SDK. A matriz completa de responsabilidades e dependências permitidas está no
[ADR-0002](../docs/adr/0002-component-responsibilities.pt-br.md).

## Por que a docstruct não faz parte da SDK

A separação é intencional, e os testes de pureza a garantem:

1. **A Toolbox depende da docstruct, não da SDK.** Juntar as duas obrigaria a
   Toolbox a instalar a SDK (com `httpx` e o código cliente que chama a própria
   Toolbox) só para ter os algoritmos. O servidor passaria a depender do próprio
   pacote cliente.
2. **A pureza é um contrato.** A docstruct não tem dependências e não pode
   importar `acessilia_sdk`. Juntar as duas misturaria código puro e
   determinístico com I/O assíncrono.
3. **Elas evoluem em ritmos diferentes.** A docstruct tem versão, tags de release
   e procedimento de atualização próprios na Toolbox; a SDK acompanha os
   contratos de capacidade da Toolbox. Um pacote único exigiria uma nova versão
   de um sempre que o outro mudasse.

A relação prevista é a inversa: **a SDK pode usar os algoritmos puros da
docstruct no próprio processo**, por exemplo para montar ou validar modelos
canônicos. Isso não é um executor local: capacidades operacionais (Pandoc, TeX
Live, veraPDF, renderização com PyMuPDF, inspeção de mídias, OCR, modelos de
IA) rodam só na Toolbox, e a SDK não tem executores locais nem um extra
`[local]` para elas
([ADR-0003](../docs/adr/0003-remote-only-operational-capabilities.pt-br.md)).

## Testes

```bash
cd libs/docstruct && python -m pytest
cd libs/sdk && python -m pytest
```
