# Mapa de responsabilidades e cobertura do benchmark

> English version: [ownership and coverage map](coverage-map.md)

## Responsabilidades

| Tema | Responsável | Contrato do Core |
|---|---|---|
| Comportamento do produto Core e scorecards 036/006 | Acessilia Core | Manter as verificações de produto junto ao pipeline exercitado |
| Execução de estrutura por página | `scripts/bench` no Core | Medir somente extração de estrutura da Toolbox, conversão canônica e exportação Markdown |
| Métricas locais reutilizáveis por página | `libs/docstruct/src/docstruct/evaluation` | Identificar como aproximações locais e versionar o protocolo de pontuação |
| Acesso SDK à Toolbox | Interfaces públicas `acessilia-sdk` | Manter os clientes do benchmark nos contratos públicos conforme a #402 avançar |
| Datasets públicos e orquestração de campanhas | `acessilia-benchmark` | Responsável por datasets públicos, avaliadores oficiais, comparações de campanha e workflows Slurm |
| Captura e replay por etapa | Próximo passo após #381 do Core e instrumentação #370 | Capturar entradas/saídas estáveis sem importar `scripts/bench` no runtime |

O harness de estrutura do Core não implementa um sistema paralelo de campanhas.
O benchmark público deve usar interfaces públicas do Core/SDK; as importações
restantes de módulos privados até a conclusão da #402 ficam como integração entre
repositórios. O CI do Core executa um smoke test da revisão fixada `810c748` do
adaptador externo contra o checkout atual, com stubs locais do cliente de
Toolbox e do serviço de pipeline. Shims temporários no Core preservam a
importação removida `backend.tools.toolbox_client` e criam um snapshot de
`CoreConfig` a partir dos settings quando o adaptador legado não o informa;
chamadas dentro do Core ainda devem passar a configuração do job explicitamente.
O adaptador deve migrar para APIs estáveis do Core/SDK e fornecer essa
configuração por job antes que os shims possam ser removidos. A atualização do
README externo registra essa divisão de responsabilidades.

O `scripts.bench compare` do Core continua como gate local de melhoria para o
harness de estrutura. Ele não é responsável por comparações de campanhas
públicas nem substitui a comparação e a avaliação oficial do benchmark externo.

## Cobertura da execução e da comparação

Cada execução deve identificar a seleção esperada e registrar, por item, hashes
de entrada/referência, estado, durações observadas de chamada e página, e hashes
das saídas obrigatórias. Só fica concluída quando todas as páginas selecionadas
terminarem e os artefatos obrigatórios continuarem com os hashes registrados.

O relatório conta páginas esperadas e executadas, falhas, referências
pontuáveis e ids pontuáveis por métrica local. A comparação exige dataset/revisão,
seleção, referências, unidade, protocolo de avaliação e cobertura de métricas
compatíveis. IDs duplicados de item ou janela documento/página invalidam a
comparação em vez de substituir silenciosamente uma linha. Uma execução parcial
ou legada pode gerar diagnóstico, mas não pode receber aceite.

O gate atual de `scripts.bench compare` é um gate de **melhoria**: tune deve
melhorar, holdout não pode regredir e nenhuma métrica incluída pode exceder a
tolerância de perda configurada. Não é um gate de paridade. Ele inclui texto,
ordem de leitura e TEDS; CDM é reportado para diagnóstico e não participa do
gate. Verificações de paridade de produto, como o caso matemático, continuam
separadas: `math_case compare` identifica o gate de paridade, enquanto a
comparação do caso de slides 006 é apenas diagnóstica. Um gate local não
substitui um avaliador oficial ou resultado de campanha.

O manifesto registra apenas a configuração aplicável ao protocolo medido. Esta
execução de estrutura não chama a pipeline de processamento do Core, então não
usa `processing_cache_configuration()`; um protocolo futuro da pipeline
completa deve reutilizar essa função. Se a árvore materializada não tiver
revisão Git, informe o SHA completo do commit de origem com
`run --dataset-revision`. Nomes mutáveis como `main` são rejeitados. Sem revisão
registrada, a comparação fica apenas diagnóstica e não pode ser aceita.

## Limites da cobertura atual

- O harness atual mede `document.structure.extract`, conversão canônica e
  escrita Markdown, uma página por vez.
- Não mede planner, executor, enriquecimento visual, exportações finais do
  produto nem latência exclusiva do provider.
- O manifesto guarda as versões do provider e dos modelos, a duração e o
  acerto de cache registrados pela Toolbox quando disponíveis. Revisão da
  implantação, tempo de fila, consulta ao cache e tentativas reais seguem
  sem observação.
- Checkpoints por etapa, replay offline e admissão de campanhas distribuídas
  continuam como próximos passos; os pontos de captura dependem da #381 e a
  telemetria compartilhada de runtime da #370.
- O runner de estrutura é serial, mas não reserva capacidade em um gateway
  compartilhado. Prefira replay offline ou execução isolada; um gateway
  compartilhado exige política de admissão, janela de execução e condição de
  parada.

Veja [regiões de medição](regions.pt-br.md) para o contrato proposto de
checkpoint.
