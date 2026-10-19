# 0006. Disponibilidade por réplicas; failover no SDK como mecanismo secundário

Também disponível em **inglês (EUA)**: [English version](0006-availability-and-failover.md)

- **Status:** Aceito
- **Data:** 2026-10-18
- **Componentes:** core, SDK, Toolbox, infraestrutura
- **Issues:** [#150](https://github.com/A11yDevs/acessilia/issues/150), [#152](https://github.com/A11yDevs/acessilia/issues/152) (P6)

## Contexto

Sem os fallbacks locais
([ADR-0003](0003-remote-only-operational-capabilities.pt-br.md)), o core
depende de a Toolbox estar acessível. A Toolbox já foi pensada para ser
stateless: os artefatos ficam em armazenamento de objetos e os caches no
Valkey (constituição da Toolbox, princípios 2 e 6). Ela também permite
failover técnico entre réplicas equivalentes (princípio 5). O failover do lado
cliente entre deploys independentes da Toolbox foi acrescentado ao SDK no
[#153](https://github.com/A11yDevs/acessilia/pull/153).

## Decisão

**Mecanismo principal: réplicas atrás de um balanceador.**
- Um deploy da Toolbox roda réplicas stateless e compatíveis atrás de um
  único balanceador.
- As réplicas compartilham o armazenamento de artefatos (MinIO/S3) e o cache e
  os locks (Valkey), então todo `ArtifactRef` continua válido qualquer que
  seja a réplica que responda.
- O core e o SDK enxergam um único `base_url` (`TOOLBOX_BASE_URL`), que aponta
  para o balanceador.

**Responsabilidades:**

| Componente | Responsável por |
|---|---|
| Toolbox | Réplicas compatíveis, health checks, execução distribuída, capacidades idempotentes |
| Infraestrutura | Balanceamento, armazenamento compartilhado, recuperação de falhas |
| SDK | Timeouts, retries limitados com backoff (só em chamadas idempotentes), mapeamento uniforme de erros |
| Core | O que fazer quando uma capacidade está indisponível: falhar a etapa ou degradá-la de forma visível, como decisão de negócio |

**Mecanismo secundário: failover no SDK entre deploys independentes.**
- O failover multi-endpoint do SDK (`endpoints=`) fica reservado a deploys
  independentes da Toolbox, por exemplo em outro site.
- Ele só passa para o próximo endpoint quando uma instância não conseguiu
  atender a requisição (timeout, erro de rede, 503, 504). Erros 4xx e
  violações de contrato são levantados na hora.
- Ele só usa um endpoint secundário se o catálogo desse endpoint publicar a
  capacidade na versão de contrato esperada, para o provider pedido.
- Quando todos os endpoints falham, ele reporta todas as causas num único
  erro (`ToolboxUnavailable`).
- O reenvio automático de um artefato desconhecido por outro deploy não é um
  mecanismo de failover. Ele vem desligado por padrão
  (`resend_file_on_missing_artifact`), porque aumenta o tráfego e a
  complexidade e arrisca artefatos inconsistentes.

**Sem fallbacks silenciosos.** Nenhum caminho produz um resultado
silenciosamente por outra implementação. Os failovers são observáveis: o SDK
chama um hook `on_failover` e o core o registra no log.

## Consequências

- **Trabalho de infraestrutura:** é preciso um deploy com réplicas, um
  balanceador e MinIO/Valkey compartilhados. Isso está registrado como issue
  de infraestrutura no backlog da #152.
- **F1 da #150:** mantém o `TOOLBOX_BASE_URL` como único endpoint primário. Um
  `TOOLBOX_BASE_URLS` opcional serve só para deploys independentes.
- **Verificado hoje:** `libs/sdk/tests/test_failover.py` cobre os gatilhos de
  failover, o descarte de secundários incompatíveis, os retries limitados com
  backoff, o erro combinado e o reenvio desligado por padrão.
- **Verificação prevista:** uma verificação ponta a ponta com duas réplicas
  da Toolbox atrás de um balanceador, em que parar uma réplica não pode fazer
  um job falhar.
