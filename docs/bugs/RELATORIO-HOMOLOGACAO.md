# Relatório de Homologação — Acessilia `release/0.1.0`

| Campo | Valor |
|---|---|
| **Versão avaliada** | `release/0.1.0` @ `7a5e70f` |
| **Data** | 2026-09-08 |
| **Responsável** | Pedro Alano |
| **Ambiente de teste** | Windows 11 · Python 3.11 · Docling + PyTorch CPU |
| **Modelos testados** | `qwen3-vl-8b` (produção, VM2) e `llava:7b` (local) |
| **Parecer** | ⚠️ **Aprovado com ressalvas** — ver condições no final |

---

## 1. Escopo e método

Cinco frentes de verificação:

1. **Suíte automatizada** — reprodução do CI (variantes slim e docling).
2. **Testes E2E via API** — script automatizado que envia documentos, mede tempo e compara saídas.
3. **Validação de modelo** — re-teste com o modelo de produção da equipe.
4. **Revisão de código e segurança** — auditoria das áreas de risco (upload, download, export, e-mail, subprocess, API).
5. **Teste dirigido de tabelas** — isolando o extrator (DLA) do modelo de visão.

---

## 2. Resultados de teste

### 2.1 Suíte automatizada
| Item | Resultado |
|---|---|
| `pytest -m "not docling"` | ✅ **136 passed**, 3 deselected |
| Testes pulados (skips) | ✅ **0** — critério do CI atendido |
| Regressão após correção do 0005 | ✅ 136 passed |

### 2.2 Testes E2E (pipeline completo via API)
| Entrada | Tempo | Resultado |
|---|---|---|
| Imagem (1ª vez) | 39 s | descrição + 6 formatos gerados |
| Imagem (2ª vez) | 3 s | **cache hit** — idêntico |
| PDF 3 páginas | 57 s | texto extraído + figura descrita |

- **Cache verificado**: chave por hash de conteúdo; sem mistura entre documentos. ✅
- **Formatos entregues**: TXT, DOCX, PDF, HTML, MP3, ZIP. ⚠️ PDF/UA exige Pandoc + engine LaTeX (ausentes no ambiente local).

### 2.3 Modelo de produção (`qwen3-vl-8b`, VM2)
| Imagem | Recusas | Erros | Tempo médio |
|---|---|---|---|
| Silhueta escura | **0/3** | 0/3 | 68,8 s |
| Foto controle | **0/3** | 0/3 | 63,1 s |

✅ **6 execuções, zero recusas.** Descrições ricas e precisas. Desempenho: **~65 s/imagem**.

---

## 3. Achados anteriores — situação atual

| ID | Achado | Situação |
|---|---|---|
| [0001](0001-html-export-crash.md) | Conversão quebrava no export HTML | ✅ **Corrigido** na `release/0.1.0` (mesma correção sugerida no relatório) |
| [0002](0002-test-isolation-history-db.md) | Testes não isolados do banco real | ⚠️ **Aberto na release** — já corrigido em `feat/observability-stack` e `feat/suporte-mysql-mariadb` |
| [0003](0003-vision-no-description-dark-image.md) | Modelo recusava imagens válidas | ✅ **Não reproduz** com o modelo de produção — era limitação do `llava:7b` local |
| [0004](0004-api-blocks-during-inference.md) | API travava durante a inferência | ✅ **Corrigido e mergeado** (PR #67, com teste de regressão) |

---

## 4. Achados novos

### 4.1 Funcional
| ID | Achado | Severidade | Situação |
|---|---|---|---|
| [0005](0005-docling-table-cells-descartadas.md) | Conteúdo das tabelas do Docling é descartado | 🔴 Alta | 🔎 **Causa raiz confirmada** · correção **sugerida** ao time |

**Destaque:** o Docling extrai as tabelas corretamente; o adaptador da Acessilia é que descartava o conteúdo. A correção sugerida (aditiva, ~75 linhas) foi validada em protótipo local **não versionado**: o HTML passou a conter `<table>`, `<thead>` e `<th scope>`, e o texto linearizado associa cada célula ao seu cabeçalho.

### 4.2 Revisão de segurança
| # | Achado | Severidade |
|---|---|---|
| S1 | `/history` e `/stats` públicos expõem metadados (nome de arquivo, título) de todos os usuários | 🟢 Baixa* |
| S2 | Painel web grava upload inteiro sem limite de tamanho (DoS de disco) | 🟠 Alta |
| S3 | E-mail enviado a endereço arbitrário, sem validação/verificação | 🟡 Média |
| S4 | Expiração de 7 dias do link não é checada no acesso (só na limpeza periódica) | 🟡 Média |
| S5 | Painel web expõe mensagem crua de exceção ao usuário | 🟡 Média |
| S6 | Validação de upload apenas por extensão (sem checagem de conteúdo) | 🟡 Média |
| S7 | SQL montado com `.format()` em `limpar_tokens_expirados` | 🟢 Baixa |
| S8 | Guarda de path com `startswith` antes de `rmtree` | 🟢 Baixa |
| S9 | `/health` expõe configuração interna do modelo | 🟢 Baixa |

\* **S1 rebaixado por decisão de escopo:** projeto de código aberto com fins educacionais, sem usuários externos no momento. **Recomenda-se revisitar antes de abrir a usuários reais ou promover a 1.0.0.**

### 4.3 Pontos verificados e aprovados ✅
- **Sem XSS** — o renderizador HTML escapa todo o conteúdo, inclusive a saída do LLM
- **Sem injeção de comando** — Pandoc chamado por lista de argumentos, sem `shell=True`, com `timeout`
- **Sem path traversal** — formato de download validado por allowlist; uploads renomeados para UUID
- **Token de download imprevisível** — `uuid4` (122 bits)
- **API não vaza stack trace**, sem CORS permissivo, rate limiting em todas as rotas

---

## 5. Parecer de homologação

> ⚠️ **APROVADO COM RESSALVAS** para a versão **0.1.0** (experimental / uso interno), condicionado às pendências abaixo.

**Condições recomendadas antes do encerramento do ciclo BHS:**

| Prioridade | Pendência |
|---|---|
| 🔴 Alta | Avaliar e aplicar a correção sugerida no **0005** — hoje há **perda de conteúdo tabular**, e tabela é meta declarada do 1.0.0 |
| 🔴 Alta | Tratar **S2** (upload sem limite no painel web) — risco de indisponibilidade |
| 🟡 Média | Aplicar a correção do **0002** (já existe em duas branches) |
| 🟡 Média | **S5** (vazamento de mensagem de erro) — correção trivial |

**Não recomendado para produção com usuários reais** enquanto **S1**, **S2** e o **0005** não estiverem resolvidos.

### Justificativa
A versão está **funcionalmente sólida**: suíte verde sem skips, pipeline completo entregando todos os formatos, cache correto, e o modelo de produção com desempenho consistente. Os dois bugs críticos anteriores (0001 e 0004) foram corrigidos no ciclo. A ressalva principal é o **0005**, que compromete diretamente o objetivo do produto (conteúdo de tabela não chega ao usuário) — a causa raiz está identificada e há **correção sugerida validada em protótipo**, sem regressão na suíte.

---

## 6. Sugestões para o CI/CD (prevenção de regressão)
1. Teste que exercite a **extração real de tabela** do Docling, validando linhas, colunas e cabeçalho (trava o 0005).
2. Fixture que garanta **banco temporário** em toda a suíte de API (trava o 0002).
3. Teste de **responsividade da API** durante processamento (trava o 0004 — já adicionado no PR #67).
4. Conjunto de imagens variadas validando descrição **não-vazia e não-recusa** (trava o 0003).
