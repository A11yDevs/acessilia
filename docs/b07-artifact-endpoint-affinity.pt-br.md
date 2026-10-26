# B07 — Upload e extração podem escolher armazenamentos diferentes da Toolbox

## Descrição breve

Os clientes de upload e extração escolhem endpoints separadamente. Entre
implantações independentes, um upload pode funcionar em A, mas a extração pedir
seu identificador a B, que não possui o arquivo. O armazenamento central do B08
não compartilha arquivos entre MinIOs de implantações independentes.

## Sintomas

- O upload funciona, mas a extração retorna HTTP 404 em outro endpoint.
- O upload em A pode falhar e mudar para B, enquanto a extração recomeça em A.
- O upload pode funcionar em A, e a extração mudar para B após uma falha.
- Os dois casos funcionam quando as réplicas realmente compartilham o mesmo armazenamento.

## Solução implementada

Com múltiplas URLs distintas, o Core envia o arquivo original diretamente em
cada tentativa de extração inicial, sem upload separado de artefato. Isso vale
mesmo com `TOOLBOX_USE_ARTIFACT_STORE=true`. Clientes de upload e extração
explicitamente configurados em implantações diferentes também usam envio direto.
Uma implantação única mantém o envio por identificador quando habilitado; um
provedor secundário em outra implantação recebe o arquivo, não o identificador
armazenado somente na implantação primária.

`use_artifact_store` registra o uso efetivo, e o `artifact_id` da origem fica
vazio quando não houve upload separado. Cada tentativa pode transferir o arquivo
novamente. Padrões de reenvio do SDK, esquemas, escolha de provedor e roteamento
de artefatos de saída permanecem iguais. Consulte a
[ADR-0012](adr/0012-source-files-for-independent-toolboxes.pt-br.md).

**Validação:** os dois casos de regressão da política automática falharam antes
da correção; os controles com envio direto explícito passaram. Agora passam
36 testes direcionados do Core e todos os 246 testes do SDK. Os testes HTTP
interceptam requisições dos clientes reais e verificam os bytes do arquivo,
ausência de upload de artefato, execução normal e troca após falha. Os controles
unitários cobrem compatibilidade com endpoint único, fechamento dos clientes e
provedor secundário em outra implantação. São testes funcionais, não avaliação
de dataset nem comprovação de ganho de qualidade.

**Conclusão:** a extração inicial deixa de depender de um identificador guardado
somente em outra implantação configurada. Não houve benchmark de dataset nem
implantação em produção. Downloads de saída (B05) e os demais itens da Trilha B
continuam como trabalhos separados pendentes nos PRs consolidados.

Na suíte completa do Core, passaram 1.754 testes, 51 testes E2E foram excluídos
e houve uma divergência preexistente no manifesto de referência em
`test_manifest_wire_payload_matches_the_golden_file[toolbox-v2-contract]`.
O mesmo teste falha em uma cópia sem alterações do commit-base; o B07 não
introduziu essa falha. O PR permanece em rascunho e não apresenta a suíte
completa como aprovada.
