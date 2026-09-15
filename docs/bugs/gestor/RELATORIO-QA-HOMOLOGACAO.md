# Relatório de QA / Homologação — Acessilia Gestor (re-teste)

| Campo | Valor |
|---|---|
| **Alvo** | https://www.acessilia3.inf.ufg.br/gestor (VM3) |
| **Testador** | Pedro Alano (testes E2E / homologação) |
| **Datas** | Achados: 2026-09-13/14 · Correções do time + reverificação no código: 2026-09-14 · **Re-teste na VM3: parcial em 14/09, continua em 15/09** |
| **Método** | Caixa-preta (Playwright/Chromium + axe-core 4.9.1) + validação manual + leitura do código-fonte (`main` do `acessilia-ufg`) |

> ⚠️ **Nota:** re-teste ainda **em andamento**. Pedro fará mais testes em **15/09**. Onde estiver ⏳, ainda não foi verificado na VM3.

## Resumo

A 1ª rodada apontou falhas de **controle de acesso (RBAC/IDOR)**, **fluxo de material** sem funcionar, **contraste** abaixo do AAA e bugs de layout. O time aplicou correções (14/09) e publicou na `main` + VM3. Este documento acompanha as correções: o que foi corrigido (confirmado no código), o que segue aberto e o resultado do re-teste.

**Legenda:** ✅ corrigido/confirmado · ⚠️ ainda aberto / a esclarecer · ⏳ a re-testar

---

## 1. De-para — achados x correções

| ID | Achado original | Grav. | Correção aplicada | Confirmado no código | Re-teste VM3 |
|---|---|---|---|---|---|
| S1 | Aluno baixa `relatorios/materiais.csv` institucional | 🔴 | Exportação por escopo: aluno só vê materiais das suas turmas | ✅ (escopo por matrícula) | ⚠️ **CSV ainda baixou — esclarecer se é o dump completo ou só as turmas do aluno** |
| S3 | **IDOR** `/materiais/:id` (aluno abre material de terceiros) | 🔴 | `canUserViewMaterial()` + `isStudentInClass()`; 403 se fora de escopo | ✅ `material.service.js:63` | ✅ **acesso negado (corrigido)** |
| — | Download sem verificação de turma/status | 🔴 | Download só se turma confere **e** versão `APROVADO` | ✅ | ⏳ |
| F1 | Upload preso em `PROCESSANDO` / sem multipart | 🔴 | `@fastify/multipart` (stream 50MB) → envia pro Core, captura `task_id` | ✅ `app.js:51` | ⏳ |
| F2 | 6 downloads acessíveis davam 404 | 🔴 | Rota `GET /materiais/:id/download?format=` (TXT/DOCX/HTML/MP3/PDF-UA/ZIP) | ✅ | ⏳ |
| A1/A2 | Contraste abaixo do AAA (7:1) | 🟠 | Paleta reajustada (`#004b99`, `#0b5e28`, `#495057`) + dark mode | ⏳ *(confirmar c/ axe)* | ⏳ |
| U1 | Título longo esticava a tela | 🟠 | `overflow-wrap`/`word-break` | ✅ | ⏳ |
| U2 | Botão do modal fora da tela em 720p | 🟠 | `max-height:90vh; overflow-y:auto` | ✅ | ⏳ |
| A3 | Skip link não focava o conteúdo | 🟡 | `tabindex="-1"` no `<main>` do login | ✅ | ⏳ |
| V1 | Upload aceitava `.exe` | 🟡 | Whitelist de extensões | ✅ `materials.routes.js:80` | ⏳ |
| V4 | CSV sem BOM | 🟢 | BOM UTF-8 (`﻿`) | ✅ | ⏳ |

## 2. Itens que parecem seguir ABERTOS (atenção)

| ID | Item | Situação no código | Sugestão |
|---|---|---|---|
| S8 | Sem trava dedicada de **força bruta no login** | ⚠️ Só o limite global `max:100/min` (`app.js:95`) | Bloqueio/atraso progressivo após ~5 falhas no login |
| S7 | Flag `Secure` no cookie | ✅ Configurável (`COOKIE_SECURE`, default `auto`) | Confirmar que na VM3 o cookie sai com `Secure` |
| S6 | `/healthz` público expõe infos | ⚠️ Segue público | Considerar reduzir detalhes expostos |
| F5 | `/monitoramento` dava 500 (`no such table: conversion_jobs`) | ⏳ | Re-testar; garantir migração da tabela |

## 3. Resultado do re-teste na VM3 (parcial — 14/09)

| Verificação | Resultado | Observação |
|---|---|---|
| Aluno abre `/materiais/1,2,3` de terceiros (S3) | ✅ **acesso negado** | corrigido |
| Aluno baixa `materiais.csv` (S1) | ⚠️ **CSV baixou** | esclarecer se é o dump completo (falha) ou só as turmas do aluno (ok) |
| Downloads (TXT/HTML) funcionam (F2) | ⏳ | 15/09 |
| Upload processa e sai de PROCESSANDO (F1) | ⏳ | 15/09 |
| Leitor mostra conteúdo real (não placeholder) | ⏳ | 15/09 |
| Título longo não estica (U1) | ⏳ | 15/09 |
| Contraste / vazamento de texto | ⏳ | 15/09 |
| `/monitoramento` sem 500 (F5) | ⏳ | 15/09 |
| Login trava após senhas erradas (S8) | ⏳ | 15/09 |

---

*Documento de teste/homologação. As "sugestões" são para o time de desenvolvimento decidir; nenhum código foi alterado pelo testador. Estes `.md` estão no repo core temporariamente — destino final: `acessilia-ufg` (aguardando acesso de escrita do Pedro).*
