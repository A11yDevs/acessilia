# Chamada remota de capacidade com retentativas e failover

> Esta é a tradução para português brasileiro de
> [remote_failover_sequence.md](remote_failover_sequence.md). A versão em inglês é a fonte
> autoritativa em caso de divergência.

Diagrama: [remote_failover_sequence.puml](remote_failover_sequence.puml). Esta página o descreve em texto. O comportamento está em `libs/sdk/src/acessilia_sdk/toolbox/client.py`; as decisões são a [ADR-0003](../adr/0003-remote-only-operational-capabilities.pt-br.md) e a [ADR-0006](../adr/0006-availability-and-failover.pt-br.md).

1. **O core pede uma capacidade ao SDK**, por exemplo `math.convert`. O cliente do SDK vem do `make_toolbox_client`, configurado a partir das settings do core.
2. **O endpoint 1 é o `TOOLBOX_BASE_URL`, normalmente um balanceador** na frente de réplicas da Toolbox sem estado, que compartilham MinIO e Valkey. A disponibilidade vem dessas réplicas. O SDK envia a requisição sem consultar o catálogo antes.
3. **As retentativas acontecem no mesmo endpoint.** Timeout, erro de rede ou `503`/`504` são repetidos até `TOOLBOX_RETRIES` vezes, esperando `TOOLBOX_RETRY_BACKOFF_SECONDS` × 2ⁿ, com jitter, entre as tentativas.
4. **Qualquer outro erro sobe na hora:** um `4xx`, outro `5xx` como `500` ou `502`, ou uma violação de contrato. O SDK o trata como resposta de uma Toolbox alcançável, que seria igual em qualquer endpoint, então não há retentativa nem failover.
5. **O endpoint 2 é opcional.** Ele vem do `TOOLBOX_BASE_URLS`, que lista deploys **independentes** da Toolbox, e só é tentado depois que o endpoint 1 falhou. Antes, o SDK lê o catálogo desse endpoint (`/v1/capabilities` e `/v1/providers`, em cache). Se a capacidade, a versão do contrato ou o provider não estiverem publicados ali, o endpoint é pulado. Caso contrário, a mesma requisição é enviada, com as mesmas retentativas.
6. **No sucesso, o resultado volta com o cliente HTTP do endpoint que o atendeu.** Um artefato produzido pela capacidade é baixado e verificado nesse mesmo endpoint.
7. **Quando todos os endpoints falham**, o SDK levanta a falha única, ou `ToolboxUnavailable` com todas as causas quando dois ou mais endpoints falharam. **Não há fallback local**: o core decide o que a falha significa.
   - A extração estrutural faz o job falhar, com mensagem explícita.
   - PDF/UA e DOCX viram erros de exportação opcionais; os demais formatos são entregues.
   - O enriquecimento de fórmulas e a inspeção de mídia degradam com um aviso registrado, e um método PDDL que falhou pode ser replanejado.
