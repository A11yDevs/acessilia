# QA / Homologação — Acessilia Gestor

Resultados dos testes do **Acessilia Gestor** (`A11yDevs/acessilia-ufg`), a pedido do professor e do @master_jf, por **Pedro Alano** (testes/homologação).

- 📋 **[RELATORIO-QA-GESTOR.md](RELATORIO-QA-GESTOR.md)** — relatório completo: achados, evidências, status de confirmação e sugestões.
- 💬 **[MENSAGEM-GRUPO.md](MENSAGEM-GRUPO.md)** — resumo em linguagem simples para o grupo.

## Placar rápido (2026-09-14)

| Área | Situação |
|---|---|
| 🔴 RBAC / IDOR | **Crítico** — aluno baixa CSV institucional (S1) e abre material de terceiros por ID (S3), inclusive um com `.exe` anexado. Escrita (POST) está protegida. |
| 🐞 Fluxo de material | **Não fecha** — fica em PROCESSANDO, leitor mostra placeholder, os 6 downloads dão 404 (integração com o Core aparenta mockada). |
| ♿ Acessibilidade | **AAA refutado** (19 violações de contraste; passam no AA). Skip link, persistência de preferências e áudio com problemas. |
| 🖥️ Layout | Título longo estica a tela (U1); botão do modal fora da tela (U2); "Gerar Backup" inexistente (U3). |
| 🟢 Bom | CSRF ativo, rotas anônimas redirecionam ao login, SSE exige auth. |

> Estes `.md` documentam o Gestor, cujo código vive em **`A11yDevs/acessilia-ufg`** (não neste repositório core). Estão aqui por conveniência do registro de QA do Pedro.
