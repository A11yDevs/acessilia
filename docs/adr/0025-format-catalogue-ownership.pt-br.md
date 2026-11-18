# 0025. Compartilhar identidade e entrega de formatos com plano do worker

Inglês, versão normativa: [English version](0025-format-catalogue-ownership.md).

- **Status:** Accepted (aceito)
- **Data:** 2026-11-17
- **Componentes:** docstruct, Core, serviço, frontend web
- **Issue:** [#371, E1.9](https://github.com/A11yDevs/acessilia/issues/371)

## Contexto

O despacho de exportação, worker, descoberta por token e interfaces de download
repetiam nomes de formatos, MIME types e sufixos. Seus papéis são diferentes:
`pdf` continua baixável para jobs antigos, apenas `pdf_ua` é produzido hoje, ZIP
é um pacote e o Markdown de benchmark é interno. A revisão aprovada rejeita
igualar esses conjuntos. D3/D9 da issue #161 atribuem identidade, política de
entrega e política de execução a responsáveis diferentes.

## Decisão

- O docstruct é responsável por
  `docstruct.export.formats.FormatSpec(id, version, media_type, extension, execution)`,
  registro imutável que usa apenas a biblioteca padrão. Não contém registro de
  capacidades, renderer, tradução ou I/O. `extension` é o tipo do arquivo (`pdf`
  para PDF/UA); sufixos de entrega são separados. `version` identifica a revisão
  da vinculação, não a especificação do formato binário.
- O Core é responsável por `acessilia_core.export.catalog`: registros imutáveis
  `FormatDelivery` em um catálogo somente de leitura. Os metadados descrevem
  status, produção, download, participação no pacote, despacho canônico,
  identidade legada, sufixo, msgid e níveis de detalhe intrínsecos. DOCX/PDF/UA
  referenciam clientes públicos e o registro de capacidades do SDK para id,
  revisão e MIME, sem copiar esse registro. O gate existente entre SDK e Toolbox
  continua responsável por detectar divergências no contrato remoto.
- O serviço é responsável por `backend.api.export_plan.ExportStep`: ordem,
  obrigatoriedade, flags, msgids de etapa e progresso. O worker usa esse plano e
  o catálogo preservando ordem serial, verificações de cancelamento, limpeza de
  falhas opcionais, concorrência áudio/auditoria e ordem dos itens do ZIP. O ZIP
  não emite atualização adicional de etapa/progresso hoje: esses campos são
  `None`. A ordem do pacote é explícita, pois difere da produção; o relatório de
  auditoria existente é anexado por último e não vira novo formato público.
- `execution` descreve as rotas atuais: `local_pure` para serializadores puros,
  `remote` para renderers via SDK, `local` para áudio/empacotamento do consumidor
  e `None` para PDF legado sem produtor. Os dois últimos ampliam o enum proposto
  em D3 para representar o comportamento real. Não autorizam novo executor ou
  fallback local: edge-tts mantém o desvio registrado em ADR-0003 / Toolbox #73;
  ZIP é empacotamento da aplicação, nunca provider operacional no docstruct.
- Tokens, downloads da API e painel web derivam metadados comuns do catálogo.
  Preservam as sete identidades de download, ordem, MIME types, sufixos
  `pdf_ua.pdf` / `_acessivel.zip` e tokens históricos de `label` da API (`texto`,
  `word`, `pdf`, `pdf/ua`, `html`, `audio`, `completo`). Esses tokens são contrato
  de transporte, não msgids. Os msgids e traduções existentes do painel passam
  ao Core; imports `WEB_FORMAT_*` permanecem como aliases. O e-mail mantém seus
  rótulos textuais específicos e recebe do worker apenas formatos públicos
  concluídos.
- Entradas estáveis podem ser oferecidas; experimentais exigem opt-in explícito;
  internas nunca são oferecidas. As interfaces atuais oferecem apenas entradas
  estáveis baixáveis. Não há formato especulativo ou nova flag para o usuário.
- Níveis de detalhe descrevem a capacidade de representação, não a seleção
  atual de perfis. Filtros, auditoria, assinaturas e ordem de AST/erros continuam
  iguais. E1.11/comportamento dos perfis e ativação estrita E1.2b exigem revisões
  de compatibilidade separadas.

## Consequências

Uma alteração de metadados de entrega tem uma fonte para as interfaces de
download; novo produtor ainda exige vinculação explícita de renderer e plano do
worker. Nenhum consumidor precisa igualar os conjuntos de produção, despacho
canônico, pacote e download. A identidade adicional é versionada no docstruct
0.5.4; o catálogo público do Core, em 0.1.1, com mínimo do docstruct elevado a
0.5.4. Não há nova dependência, pin externo, publicação, alteração de schema ou
snapshot de exportação.

Testes de contrato fixam nomes, labels, MIME, papéis, referências ao SDK, flags,
falhas obrigatórias/opcionais e ordem do arquivo. Os gates de caracterização,
wheel isolado, pureza e container fixado continuam aplicáveis. Substituir PDF
legado, ativar formatos experimentais ou mudar política de falha exige outra
alteração revisada.
