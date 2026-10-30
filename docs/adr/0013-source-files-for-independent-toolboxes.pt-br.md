# 0013. Enviar arquivos de origem para implantações independentes da Toolbox

- **Status:** Accepted (aceito após a revisão e o merge)
- **Data:** 26/10/2026
- **Componentes:** Core; transportes existentes do SDK e da Toolbox permanecem iguais
- **Referência:** [PR #309](https://github.com/A11yDevs/acessilia/pull/309)

Antes da implantação, é necessário confirmar o valor efetivo de
`TOOLBOX_BASE_URLS` em staging e produção. O valor vazio de `.env.example` não
comprova a topologia real. Com URLs independentes, fusão e text spans podem
reenviar o arquivo completo; valide PDFs grandes em staging. A política agora
registra em log quando dispensa o artifact store apesar de estar habilitado.

## Contexto

Upload e extração escolhem endpoints separadamente. Um arquivo enviado a uma
implantação independente não necessariamente existe em outra. A ADR-0006 reserva
múltiplas URLs para implantações independentes; uma URL pode representar réplicas
com armazenamento central comum. O SDK já aceita o arquivo diretamente e mantém
o reenvio automático após 404 desabilitado por padrão.

## Decisão

Na extração estrutural inicial, o Core envia o arquivo diretamente quando os
clientes de upload/extração abrangem mais de uma URL distinta. O upload separado
é dispensado, mesmo quando o uso do armazenamento de artefatos foi solicitado.
Uma implantação única mantém o envio por referência quando habilitado, conforme
a ADR-0005. Um provedor secundário configurado em outra implantação recebe o
arquivo original, não o identificador guardado na implantação primária.

Essa é uma política de transporte da entrada inicial, não um reenvio automático
após erro de artefato ausente. Padrões do SDK, tentativas, checagem de catálogo,
escolha de provedor, esquemas e roteamento de artefatos de saída não mudam.
Nenhum executor de extração é transferido para o Core.

## Consequências

Cada tentativa/provedor pode transferir o arquivo novamente. Na extração com
múltiplos endpoints, o identificador inicial da origem fica vazio, e
`use_artifact_store` registra o uso efetivo. O arquivo precisa continuar disponível
até o término das chamadas. Downloads de saída e etapas posteriores ainda exigem
suas próprias garantias de roteamento (ADR-0014).

Os testes reproduzem a escolha independente dos clientes e verificam envio direto
normal/com falha do primário, ausência de cliente de upload desnecessário,
compatibilidade de referências no endpoint único e provedor secundário em outra
implantação. Esta decisão não inclui avaliação de dataset nem implantação.
