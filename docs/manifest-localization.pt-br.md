# As mensagens do manifesto devem seguir o idioma da requisição

## Problema

O teste de referência do manifesto falhava no ambiente em português, embora os
campos estruturais coincidissem. Havia seis diferenças textuais: `message` e
`rationale` para tabelas, imagens e fórmulas. O arquivo de referência espera
inglês nessas mensagens.

A tabela `OBLIGATION_BY_TYPE` chamava `t()` durante a importação de `builder.py`
e guardava as traduções globalmente. Requisições em outro idioma continuavam
recebendo os textos do momento da importação, inclusive na reclassificação de
elementos. Trocar o idioma depois da importação não atualizava essas strings.

## Correção

A tabela global agora guarda os identificadores canônicos das mensagens. A
criação das necessidades de processamento e a reclassificação traduzem esses
identificadores no momento da chamada, conforme a requisição atual. Esquema,
identificadores, métodos do planejador e arquivo de referência não mudaram.

A suíte de caracterização fixa `en_US` explicitamente e restaura o idioma anterior
depois de cada teste. Assim, o idioma do arquivo de referência fica declarado e
não depende do terminal. Outros testes alternam inglês, português e inglês sem
reimportar o módulo, verificam as traduções e comprovam que os demais campos do
manifesto permanecem iguais. A reclassificação também é testada nos dois idiomas.

## Escopo da validação

O novo teste de alternância de requisições falhou antes da correção. Os testes
de idioma e caracterização passaram com o processo iniciado tanto com
`LOCALE=pt_BR` quanto com `LOCALE=en_US` (40 verificações em cada execução).
A mudança corrige o defeito de tradução em execução e a suposição implícita do
teste; não apenas substitui o arquivo esperado nem força inglês em produção.

São verificações funcionais com fixtures sintéticas, não avaliação de dataset.
Esta correção não inclui implantação nem atualização de PR. O resultado da
suíte completa fica registrado no relatório consolidado após a validação.

Validação completa do Core após a correção: **1.775 testes aprovados, 51 E2E
excluídos**, sem falhas. Os arquivos JSON de referência não foram modificados.
