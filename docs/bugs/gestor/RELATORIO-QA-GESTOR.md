# Relatório de QA / Homologação — Acessilia Gestor

| Campo | Valor |
|---|---|
| **Alvo** | https://www.acessilia3.inf.ufg.br/gestor |
| **Repositório dos defeitos** | **A11yDevs/acessilia-ufg** (Node.js / Fastify / EJS / SQLite) — *não é o core* |
| **Testador** | Pedro Alano (papel: testes E2E / homologação) |
| **Data** | 2026-09-14 |
| **Método** | 2 passadas de caixa-preta com agente automatizado (Antigravity: Playwright/Chromium + axe-core 4.9.1) + **validação manual** do Pedro |

> Pedido de origem: o professor e o @master_jf (Jonathan) pediram no grupo para o Pedro **validar e testar** o Acessilia Gestor. Este é o resultado.

## Legenda de confiança
- ✅ **Confirmado** — reproduzido com evidência direta (status HTTP + corpo, ou print do Pedro).
- 🔎 **A confirmar** — depende de interpretação do agente; reverificar antes de virar issue.
- 🟢 **Positivo** — testado e está correto (não é defeito).

---

## Sumário executivo e veredito

**❌ Não apto para homologação/produção nesta versão** — esperado, é uma versão inicial. Bloqueadores:

1. **Controle de acesso furado (RBAC/IDOR)** — um aluno baixa relatório institucional e abre material de qualquer professor iterando o ID na URL, inclusive material com `.exe` anexado. *Prioridade 1 — resolver antes de qualquer demo com dado real.*
2. **Fluxo de material não fecha** — upload fica preso em `PROCESSANDO`, o leitor mostra texto-modelo (placeholder) e **nenhum dos 6 downloads funciona**. Coerente com a integração com o Core ainda estar mockada.
3. **Contraste não cumpre o AAA alegado** — 19 violações; a alegação "WCAG 2.2 AAA" precisa ser corrigida ou a paleta ajustada.

**Pontos fortes:** a base de acessibilidade (barra A/A+/A++, contraste, dislexia, `aria-live`) existe; a estrutura de perfis/telas está montada; **CSRF ativo e funcional**, rotas anônimas redirecionam ao login, SSE exige auth. O time construiu bastante coisa — os problemas são concentrados e corrigíveis.

---

## 1. Segurança — Controle de acesso (Prioridade 1)

| # | Status | Gravidade | Achado | Evidência |
|---|---|---|---|---|
| S1 | ✅ Confirmado (agente + Pedro) | 🔴 Crítica | Aluno baixa `GET /gestor/relatorios/materiais.csv` → **200**. O CSV traz título, disciplina, **nome do docente**, categoria e status de **todos** os materiais. | Pedro baixou `relatorio_acessibilidade_materiais.csv` (2.053 bytes). Corpo: `ID,Data_Cadastro,Titulo,Disciplina,Docente,...` |
| S2 | ✅ Confirmado (esclarecido) | 🟡 Média | `GET /gestor/academico/cursos` e `/disciplinas` como aluno → **200**, renderizando a tela de **gestão** e o `<form method="POST">` de criação. **Porém o POST é bloqueado (403)** — só a leitura vaza. | `POST /gestor/academico/cursos` como aluno (c/ CSRF válido) → **403** `Acesso Proibido`. Nenhum curso criado. |
| S3 | ✅ **Confirmado** (agente, 2ª passada) | 🔴 Crítica | **IDOR** em `/gestor/materiais/:id`: aluno abre `/1`, `/2`, `/3`… e vê materiais de outros docentes, **em PROCESSANDO** (não aprovados) — inclusive um intitulado *"Teste Arquivo Executavel Malicioso"* com `payload_malicioso.exe`. | `/materiais/1`,`/2`,`/3` como aluno → **200** com título/docente/arquivo de terceiros. |
| S4 | ✅ Confirmado | 🟠 Alta | `GET /gestor/academico/disciplinas` como aluno → **200** com formulário de cadastro (mesmo padrão do S2). | Corpo: `<h1>Catálogo de Disciplinas</h1> ... <form action="/gestor/academico/disciplinas" method="POST">` |
| S5 | ✅ Confirmado | 🟡 Média | Professor acessa `GET /gestor/revisoes` → 200 (deveria ser exclusivo de Revisor/Admin). | Link exposto no menu do professor. |
| S6 | ✅ Confirmado | 🟢 Baixa | `GET /gestor/healthz` sem login → **200** expõe uptime, tamanho do SQLite e detalhes da integração (`model_client: openrouter`, status online). | Corpo JSON completo capturado. |
| S7 | ✅ Novo achado | 🟡 Média | Cookie de sessão **sem a flag `Secure`** (CWE-614). Tem `HttpOnly` e `SameSite=Lax` (bom), mas sem `Secure` o cookie pode trafegar em claro numa degradação de protocolo. | `Set-Cookie: sessionId=...; Path=/; HttpOnly; SameSite=Lax` (sem `Secure`). |
| S8 | ✅ Novo achado | 🟡 Média | **Sem proteção dedicada a força bruta no login.** 6 tentativas seguidas com senha errada, todas aceitas (400); só existe o limite genérico de 100 req/min por IP. | `x-ratelimit-remaining` caiu 91→81 em 6 tentativas, sem bloqueio. |

**Positivos (🟢):** POST de criação bloqueado (S2); rotas anônimas (`/relatorios`, `/revisoes`, `/usuarios`) → **302 → /login**; SSE `/api/v1/notifications/stream` sem login → **401**; **CSRF ativo** (POST sem token ou com token forjado → 403 `FST_CSRF_INVALID_TOKEN`).

### 💡 Sugestões (Seção 1)
- **Aplicar `requirePermission` também nas rotas GET** de `/relatorios/*`, `/academico/*` e na visualização `/materiais/:id` — hoje a proteção só cobre parte das mutações (POST), deixando a leitura aberta.
- **Checagem de posse (ownership) em `/materiais/:id`**: o aluno só deveria ver material **aprovado/publicado da sua turma**; professor só o próprio; revisor os atribuídos. Corrige o IDOR (S3).
- Adicionar a flag **`Secure`** ao cookie de sessão (S7).
- **Rate limit específico do `/login`** por e-mail+IP (ex.: atraso progressivo/bloqueio após 5 falhas), além do limite global (S8).

---

## 2. Fluxo de material e integração com o Core

| # | Status | Tipo | Achado | Evidência |
|---|---|---|---|---|
| F1 | ✅ Confirmado (Pedro) | 🚧/🐞 | Upload **aceita** um arquivo (o Pedro subiu uma imagem), mas o material **fica preso em `PROCESSANDO`**; só existe a **v1 ORIGINAL** (com hash SHA-256), sem a v2 PROCESSADO_BOT. O pipeline não conclui. | Print: material "testes pedro", Status PROCESSANDO, só v1. |
| F2 | ✅ Confirmado (Pedro) | 🐞 Crítica | **Nenhum dos 6 downloads funciona** (HTML, PDF/UA, DOCX, TXT, MP3, ZIP). Clicar gera um `.json` que "não estava disponível no site" (404). | Print do histórico de downloads: vários `mat_..._Captura...json` → *"O arquivo não estava disponível no site"*. |
| F3 | ✅ Confirmado (Pedro) | 🐞 | O **Leitor Acessível** mostra **texto-modelo/placeholder**, não o conteúdo processado — "Resumo Pedagógico: kkk" e um parágrafo genérico fixo ("...respeita o nível AAA"). Não é a saída real da IA. | Print da tela do material. |
| F4 | ✅ Confirmado (agente) | 🐞 Crítica | Fila de revisão vazia / `/gestor/revisoes/:id/analise` inacessível → a tela lado a lado não é exercitável enquanto o pipeline não gera a v2. | 1ª passada. |
| F5 | 🔎 A confirmar | 🐞 Crítica | `/gestor/monitoramento` → **500** `SQLITE_ERROR: no such table: conversion_jobs` (migração ausente). Não foi reexecutado na 2ª passada — **reverificar**. | 1ª passada. |

> **Leitura:** F1–F4 indicam que a **integração real com o Core não está entregando artefatos** — o leitor e os downloads usam dados-modelo. Isso bate com o "algumas coisas mocadas" citado pelo Jonathan. **Ação principal aqui é de documentação**: marcar esses itens como *em desenvolvimento*, não "operacional/implementado".

### 💡 Sugestões (Seção 2)
- Enquanto o Core não integra, **rotular claramente** as telas mockadas (ou desabilitar os botões de download) para não passar impressão de pronto — importante para a demo.
- Servir de fato a pasta de artefatos gerados (rota estática) e ligar o webhook do Core que cria a v2; validar a migração que cria `conversion_jobs` (F5).

---

## 3. Acessibilidade (WCAG) — núcleo do produto

**Alegação "WCAG 2.2 AAA": ❌ refutada.** O axe-core apontou **19 violações** da regra `color-contrast-enhanced` (critério 1.4.6, AAA, exige 7:1). As razões medidas ficam entre **4.54:1 e 5.93:1** — reprovam o AAA, mas em geral **passam no AA** (≥4.5:1).

| Tela | Elemento | Frente | Fundo | Medido | AAA (7:1) |
|---|---|---|---|---|---|
| Login/Dashboard | texto secundário `#64748b` | `#64748b` | branco/`#f8fafc` | 4.54–4.75:1 | ❌ |
| Vários | botão primário / `.role-tag` | `#ffffff` | `#0369a1` | 5.93:1 | ❌ |
| Materiais | status "PROCESSANDO" | `#ffffff` | `#b45309` | 5.02:1 | ❌ |

> ⚠️ A 1ª passada relatou contraste de **1.06:1** (botão "Sair") e **2.23:1** (links de download) — reprovando até no AA. A 2ª passada **não reconfirmou** esses valores (pior caso 4.54:1). Tratar o AA-fail como **não confirmado** (provável erro de medição da 1ª passada); o **AAA-fail está confirmado**.

Outros (✅ confirmados pelo agente, alguns pendentes de teste com leitor de tela):
- **A3 (2.4.1):** skip link no login não leva o foco ao conteúdo (foco vai pro `<body>`).
- **A4 (1.1.1):** o gráfico SVG do dashboard e a tabela `<details>` equivalente **não existem** no DOM (recurso prometido ausente).
- **A5:** preferências (contraste/dislexia) só no `localStorage`; o backend não injeta no HTML → **perde-se em outro navegador/dispositivo**.
- **A6 (1.2):** player de audiolivro sem mídia real (áudio 404) — liga com F2.
- **A7 (3.3.1/3.3.2):** erros de validação voltam como **JSON cru** (400/415/500), sem `role="alert"`/foco.
- **Pendente manual:** teste com **NVDA** (rótulos, `aria-live`, ordem de foco).

### 💡 Sugestões (Seção 3)
- Escurecer o cinza secundário (`#64748b` → algo como `#475569`/`#334155`) e o azul do botão para atingir **7:1**, **ou** ajustar a alegação para **"WCAG 2.2 AA"** (mais honesto e ainda forte).
- Corrigir o skip link (foco programático no `#conteudo-principal` com `tabindex="-1"`).
- Persistir preferências no backend (a doc já promete isso) para valer entre dispositivos.
- Trocar respostas de erro JSON por mensagens na página com `role="alert"` e foco.

---

## 4. UI / Layout e robustez

| # | Status | Gravidade | Achado |
|---|---|---|---|
| U1 | ✅ Confirmado (Pedro) | 🟠 Alta | **Tela de Materiais quebra com título longo:** um material com título muito grande **estica a página horizontalmente** em vez de quebrar/abreviar o texto, desalinhando toda a lista. |
| U2 | ✅ Confirmado (agente) | 🟠 Alta | Modal "+ Enviar Material" (`position:fixed; inset:0` sem `overflow-y:auto`): em 1280×720 o botão "Enviar e Processar" fica **fora da tela**, inclicável pelo mouse. |
| U3 | ✅ Confirmado (agente) | 🟠 Alta | Botão/rotas de **"Gerar Backup"** (`/gestor/backup`, `/gestor/admin/backup`) **não existem** (recurso documentado ausente). |
| V1 | 🔎 A confirmar | 🟡 Média | Sem validação de **extensão** — registro com `filename="teste.exe"` aceito (o material "payload_malicioso.exe" existe no sistema, ver S3). |
| V2 | 🔎 A confirmar | 🟡 Média | Sem validação de **tamanho** no backend (registro >50MB aceito). |
| V3 | ✅ Confirmado | 🟡 Média | Duplo envio concorrente cria **registros duplicados** (o CSV tem "Material Duplo Clique Race Test"). |
| V4 | ✅ Confirmado | 🟢 Baixa | CSV em UTF-8 **sem BOM** → risco de acento corrompido no Excel pt-BR. |

### 💡 Sugestões (Seção 4)
- Título longo (U1): CSS `max-width` + `text-overflow: ellipsis`/`word-break` na coluna; nunca deixar a linha empurrar o layout.
- Modal (U2): `overflow-y: auto` + `max-height` no container.
- Validar **extensão e tamanho no backend** e rejeitar `.exe` etc.; idempotência/`debounce` no envio (V3); BOM no CSV (V4).

---

## Próximos passos
1. **Prioridade 1:** fechar RBAC/IDOR (S1–S4) — cobrir GET com permissão + ownership em `/materiais/:id`.
2. Alinhar com o Jonathan o que é *mock/em desenvolvimento* (F1–F5) e ajustar a documentação de "implementado" → "em desenvolvimento".
3. Rever contraste vs. alegação AAA (Seção 3).
4. Reverificar F5 (monitoramento 500) e V1/V2 (validação) quando o upload real estiver ligado.

> **Nota de papel:** este relatório é de **teste/homologação**. As "sugestões" são para o time de desenvolvimento do Gestor decidir e implementar — nada de código foi alterado pelo testador.
