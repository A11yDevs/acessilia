# 0014. Procurar downloads de artefatos ausentes em endpoints compatíveis

- **Status:** Accepted (aceito após revisão e merge)
- **Data:** 26/10/2026
- **Componentes:** SDK

## Contexto

Uma implantação independente pode não possuir um artefato presente em outra.
A regra geral para erros 4xx da ADR-0006 interrompe a busca no primeiro 404.

O consumidor afetado é a interface pública `ToolboxArtifactClient.download`
do SDK, para clientes que recuperam um artefato por ID. O Core atualmente não
chama esse método: seus clientes de capacidades buscam as saídas no endpoint
produtor. A mudança corrige o contrato público do SDK.

## Decisão

Somente no download de artefatos por identificador, um 404 avança ao próximo
endpoint compatível, sem repetir a busca no mesmo endpoint. Se todos retornarem
404, o erro continua `ToolboxArtifactNotFound`. Falhas mistas preservam os erros
combinados existentes. Outras operações e códigos 4xx permanecem iguais.

Em particular, 404 seguido de timeout gera `ToolboxUnavailable`, preservando
as duas causas. Não se pode afirmar que o artefato está ausente em todos os
endpoints, pois o segundo não respondeu. Esse erro não deve disparar uma
política de reenvio restrita a arquivos ausentes. Há testes para o caso misto,
todos os endpoints com 404 e conteúdo corrompido.

## Consequências

Downloads ausentes podem exigir mais requisições. Verificações de hash/assinatura
e substituição atômica continuam obrigatórias; conteúdo corrompido não provoca
failover. Esta exceção restrita à ADR-0006 não habilita reenvio de arquivos.
