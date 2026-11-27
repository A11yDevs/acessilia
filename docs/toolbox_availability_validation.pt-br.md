# Validando o gate de disponibilidade da Toolbox antes de ativar `enforce` (#809)

Também disponível em **inglês (EUA)**: [English version](toolbox_availability_validation.md)

- **Objetivo:** permitir que o mantenedor reproduza as evidências de produção
  exigidas pela #809 antes de `enforce` virar o comportamento normal.
- **Responsável:** o mantenedor ou um operador autorizado com acesso aos logs e
  metadados de produção. O autor da mudança não precisa inventar evidências nem
  acessar sistemas sem autorização.
- **Escopo:** jobs desde o deploy do domínio 2.4 (#781), enquanto o gate estava
  em `observe`. Não exponha chaves de API, documentos de origem nem dados
  pessoais.

## 1. O que coletar

Para cada job de produção na janela:

1. **A linha do gate no log.** Antes da #933, toda decisão com método bloqueado
   produzia:
   `Toolbox gate observing (catalogue <revision>): would remove — <method>: <reasons>`.
   Depois da #933 a linha é
   `Toolbox gate (catalogue <revision>): methods the catalogue rules out — ...`.
   Guarde a revisão e o motivo de cada método.
2. **`canonical_metadata.pddl_toolbox_availability`.** Os campos importantes:
   - `mode`, `catalog_revision`, `catalog_error`;
   - `requirements`: os pares `(capability@version, provider)` que cada método
     pediu;
   - `offered` e `offered_source`: o que o snapshot publicou;
   - `blocked_methods`: o que o gate removeria, com motivos;
   - `assumed_runnable_methods`: métodos que o plano usou enquanto os fatos
     eram presumidos (`observe`);
   - `optional` e `degraded_methods`: chamadas opcionais que o snapshot não
     tinha.
3. **Os endpoints em uso.** `TOOLBOX_BASE_URL`, `TOOLBOX_BASE_URLS` e as
   configurações de provider, sem a chave de API. Registre se o deploy usa um
   endpoint (normalmente o balanceador) ou deploys secundários independentes.
4. **O período e o volume.** Início/fim, número de jobs avaliados e número de
   jobs com ao menos um método bloqueado. Um resultado vazio não é evidência
   sem o número de jobs avaliados.

## 2. Verificações reproduzíveis

Use a agregação de logs existente, `jq` ou um pequeno script somente leitura.
Os exemplos abaixo são ilustrativos; adapte caminhos e nomes de campo ao
ambiente.

```bash
# 1. Decisões históricas de observe (antes da #933).
rg -N "Toolbox gate observing .*would remove" <logs> > /tmp/gate-observe.txt
wc -l /tmp/gate-observe.txt

# 2. Novas linhas de relatório (depois da #933).
rg -N "Toolbox gate .*methods the catalogue rules out" <logs> > /tmp/gate-enforce.txt
wc -l /tmp/gate-enforce.txt

# 3. Erros de catálogo na mesma janela.
rg -N "catalog_error|Toolbox gate .*unavailable" <logs> | wc -l
```

Para os metadados canônicos, extraia um registro por job:

```bash
jq -r '
  .canonical_metadata.pddl_toolbox_availability
  | [.mode, .catalog_revision, .catalog_error,
     (.blocked_methods | keys | join(",")),
     (.assumed_runnable_methods | join(","))]
  | @tsv
' <documentos-canonicos>/*.json
```

## 3. Classificar cada método bloqueado

Para cada método em `blocked_methods` e cada entrada de
`assumed_runnable_methods`, responda:

| Pergunta | Lacuna real | Falso positivo |
|---|---|---|
| A capacidade existe no catálogo na versão de contrato que o SDK chama? | Versão/capacidade ausente | Presente; a conferência usa id/versão errados |
| O provider configurado a implementa? | Provider ausente ou incompatível | Provider registrado com outro nome/padrão |
| A conferência lê o deploy que o cliente chama? | O primário é o deploy pretendido | Troca entre primário/secundário, URL ou chave erradas |
| O método conseguiria rodar? | Não | Sim; o gate está restritivo demais |

Registre a causa (`missing capability`, `missing provider`, `wrong version`,
`endpoint mismatch`, `catalogue read failure`, `false positive`) e o método.
Não marque um requisito ausente como oferecido só para deixar o log verde.

## 4. Erros de catálogo e validade do snapshot

- Conte `catalog_error` por tipo (`ToolboxTimeout`, `ToolboxProviderUnavailable`,
  violação de contrato, URL inválida).
- Verifique se a decisão usou um snapshot dentro de
  `TOOLBOX_CATALOG_STALE_SECONDS` ou caiu em falha fechada.
- Correlacione erros com o período do deploy/réplica, não apenas com o
  documento. Falha de leitura do catálogo é problema de disponibilidade da
  Toolbox, não do documento.
- Confirme qual endpoint o gate leu. O gate lê apenas o primário; veja a
  limitação documentada em `toolbox_integration.pt-br.md` e na
  [#938](https://github.com/A11yDevs/acessilia/issues/938).

## 5. Registro da decisão

Adicione à #809 ou ao PR:

- [ ] Janela analisada e número de jobs avaliados.
- [ ] Número de decisões com métodos bloqueados.
- [ ] Cada método bloqueado classificado como lacuna real ou falso positivo.
- [ ] Análise de `assumed_runnable_methods`.
- [ ] Frequência e causas de `catalog_error`, incluindo a janela de validade.
- [ ] Versões/providers efetivamente publicados e endpoints usados.
- [ ] Conclusão explícita: a falha fechada é segura para este deploy?

Se houver falsos positivos relevantes, corrija a conferência e repita a janela.
Se os logs históricos forem insuficientes, o mantenedor precisa aprovar
explicitamente um protocolo alternativo (por exemplo, comparação controlada em
staging) antes do deploy em produção; este documento não substitui essa
decisão.

## 6. Alternativa quando os logs históricos forem insuficientes

1. Use um ambiente de staging com versões, providers e catálogo representativos.
2. Compare o comportamento anterior em `observe` com o candidato em `enforce`
   sobre documentos equivalentes.
3. Confirme que os métodos removidos estão realmente indisponíveis e que os
   planos preservam objetivos críticos, alternativas admissíveis e avisos de
   degradação.
4. Simule catálogo completo, requisito ausente, versão/provider incompatível,
   falha/expiração do catálogo e, quando aplicável, failover multiendpoint.
5. Registre os resultados, os limites de representatividade e os critérios de
   aprovação.
6. Defina implantação controlada e rollback antes de ativar `enforce` em
   produção.

Staging não é automaticamente evidência de produção; substituir o critério
original da #809 é uma decisão do mantenedor.
