# Vereditos das capacidades da Toolbox

Este documento registra se cada capacidade da Toolbox é acionável no núcleo
Acessilia, com base no contrato ao vivo de homologação, nos caminhos de chamada
de produção e na suíte E2E. Estar exposta pela Toolbox, por si só, não significa
que a capacidade esteja integrada. A falta de acionamento de uma capacidade
Dr.DocBench, porém, deve ser investigada na trilha evidência → obrigação →
`problem.pddl` → método → handler → efeito verificável, não tratada como motivo
para descartá-la.

## Snapshot do contrato ao vivo

Verificado contra `https://www.acessilia3.inf.ufg.br/toolbox` em 2026-10-14:

- 26 capacidades e 25 providers estão expostos.
- Permanecem cinco divergências conhecidas: três clientes do core apontam para
  capacidades ausentes na Toolbox ao vivo e dois defaults apontam para providers
  não registrados.
- Seis capacidades expostas pela Toolbox não têm cliente no core.
- A suíte E2E ao vivo passou nos 42 testes selecionados. Ela cobre os caminhos
  de produção representados pela suíte atual, não todas as capacidades do
  catálogo ao vivo.

## Vereditos

| Capacidade / família | Evidência no Acessilia | Veredito | Próxima ação |
|---|---|---|---|
| `document.structure.extract` | Usada por `ToolboxManifestExtractor`; exercitada nos E2E de comparação e fusão | Integrada | Manter contrato e cobertura E2E |
| `document.layout.analyze` | `ToolboxLayoutStructurer`; cobertura E2E direta e em fluxo | Integrada | Manter contrato e cobertura E2E |
| `document.ocr` | Wrapper Agno e cliente; E2E remoto de OCR | Integrada | Manter contrato e cobertura E2E |
| `math.recognize`, `math.convert`, `math.verbalize` | Ferramentas/cliente de matemática; E2E de reconhecimento, conversão, verbalização e fluxo encadeado | Integradas | Manter contrato e cobertura E2E |
| `pdf.split`, `pdf.render` | Cliente do SDK com E2E direto e encadeado. O `pdf.render@2` renderiza todas as páginas e regiões do orquestrador (`pymupdf-region`, `vision-page-inspection`, `vlm-pairwise-judge` e o enriquecimento de imagens/tabelas, F5 da #150); o `pdf.split` não tem chamador de produção desde a remoção de `toolbox_pdf_tools.py` (F4 da #150) | Contrato mantido | Manter contrato e cobertura E2E, incluindo o `clip`, o `max_side` e as recusas do `pdf.render@2` de que o core depende |
| `media.inspect` | Chamador de produção em `backend/tools/media_inspect.py`; configuração opt-in | Integrada, opt-in | Manter o gate explícito |
| `document.export.pdf_ua` | Chamador de produção em `backend/export/pandoc_exporter.py`; ativo por padrão; só na Toolbox desde a F2 da #150, sem fallback local. Incluída após o snapshot acima: verificada ao vivo em 2026-10-17, depois do merge de acessilia-toolbox#53 | Integrada | Todo deploy precisa rodar o `pdf-ua-render`: sem ele, os jobs reportam o PDF/UA como erro de exportação opcional |
| `artifact.store`, `artifact.retrieve` | Cliente Toolbox compartilhado; usado nos caminhos de upload/extração | Infraestrutura integrada | Manter cobertura de contrato do cliente |
| `dataset.*` | Ferramentas usadas pelos scripts Dr.DocBench, não pelo runtime de documentos | Integradas ao benchmark; fora do runtime de documentos | Preservar o caminho dos scripts e seus testes |
| `image.page.orient` | Cliente/provider válidos; falta gatilho PDDL de produção | Pendente de modelagem/acionamento | Derivar obrigação por evidência de orientação e validar a rotação aplicada |
| `document.ocr.page` | Cliente/default existem; faltam capacidade/provider ao vivo e gatilho PDDL | Pendente; divergência de contrato conhecida | Alinhar contrato/provider e ligar a obrigação a evidência real de OCR de página |
| `document.adjudicate.page`, `document.adjudicate.region` | Clientes/defaults existem; faltam capacidades/providers ao vivo e gatilhos PDDL | Pendente; divergência de contrato conhecida | Alinhar contratos/providers e ligar a adjudicação às evidências de divergência/recorte |
| `accessibility.mark` | Exposta pela Toolbox; falta cliente e caminho obrigação/método/handler | Pendente de integração PDDL | Mapear evidência, obrigação, chamada e efeito acessível verificável |
| `chem.convert`, `chem.recognize` | Expostas pela Toolbox; falta cliente e caminho obrigação/método/handler | Pendente de integração PDDL | Ligar regiões químicas observadas à conversão e validar a saída |
| `code.normalize` | Exposta pela Toolbox; falta cliente e caminho obrigação/método/handler | Pendente de integração PDDL | Ligar blocos de código observados à normalização e validar preservação semântica |
| `text.postprocess` | Exposta pela Toolbox; falta cliente e caminho obrigação/método/handler | Pendente de integração PDDL | Ligar sinais de ruído textual à pós-correção e validar o texto resultante |
| `music.omr` | Exposta pela Toolbox; falta cliente e caminho obrigação/método/handler | Pendente de integração PDDL | Ligar partituras detectadas à transcrição OMR e validar o artefato musical |
| `cache.get`, `cache.put` | Detalhes de implementação internos da Toolbox | Não são capacidades do core | Manter internas; não é necessário cliente no core |

## Decisão para release

Os fluxos existentes Acessilia–Toolbox foram verificados contra a imagem de
homologação. A integração **ainda não está totalmente sem divergências de
contrato** enquanto as cinco pendências conhecidas existirem. As capacidades
Dr.DocBench sem acionamento continuam no escopo e exigem fechar a trilha PDDL e
os contratos/providers ausentes, não removê-las por falta de um fluxo
convencional de produto. A especificação REST própria para OCR de página e
adjudicação ainda é necessária antes de implementar os adapters correspondentes
na Toolbox.
