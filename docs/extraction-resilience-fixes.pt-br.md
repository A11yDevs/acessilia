# Extração de documentos e recuperação de artefatos mais resilientes

## Problemas e sintomas

- PDFs acima do limite podiam passar pela extração estrutural antes da rejeição.
- Uma falha temporária no upload podia impedir uma extração direta disponível.
- Um download podia parar no primeiro 404, embora outro endpoint tivesse o arquivo.
- O modo dual podia terminar na falha do primário sem tentar o secundário.
- Clientes independentes de upload e extração podiam enviar o identificador à implantação errada.

## Soluções implementadas

A contagem de páginas PDF do `media.inspect` passa a ser verificada antes da
extração. Somente a contagem confirmada pelo parser `pymupdf` permite rejeição
antecipada; contagens desconhecidas ou estimadas mantêm a checagem posterior.

Falhas temporárias no upload permitem extração direta do arquivo, com aviso
traduzido e categoria da falha registrada. Autenticação, entrada inválida e erros
de contrato não são contornados. Implantações independentes também usam envio
direto como política; uma implantação única mantém o envio por identificador.

Somente o download de artefatos procura no próximo endpoint compatível após um
404. Outras operações e erros preservam seu comportamento. Se todos retornarem
404, o resultado continua sendo artefato ausente. A verificação do conteúdo e a
substituição atômica do arquivo permanecem obrigatórias.

Os provedores do modo dual são tentados independentemente. Se ambos funcionam,
a fusão existente é preservada. Um único sucesso fornece o resultado com
degradação explícita e proveniência/cache correspondentes. Se ambos falham,
o erro preserva as duas causas. Erros inesperados de programação não são ocultados.

## Compatibilidade durante falhas do armazenamento

O envio direto evita o upload inicial, mas a extração ainda pode falhar se a
Toolbox exigir armazenamento para o JSON de saída. A continuidade depende da
alteração complementar no
[PR #100 da Toolbox](https://github.com/A11yDevs/acessilia-toolbox/pull/100):
em uma falha temporária do armazenamento, uma extração com saída inline devolve
o JSON sem anunciar um download persistido nem armazenar esse resultado no
cache. Saídas binárias obrigatórias e capacidades por referência continuam
dependendo do armazenamento; erros permanentes de entrada ou contrato não são
contornados.

Uma regressão entre projetos na Toolbox executa o extrator real do Core e o
SDK contra um servidor HTTP local real da Toolbox, em ambientes Python
separados. O upload inicial e a persistência do JSON falham, enquanto um
extrator simulado funciona. O Core recebe o documento inline e registra a
falha do upload. Isso verifica transporte e orquestração, sem avaliar a
qualidade da extração ou toda a conversão de produção.

## Validação e revisão

A [execução 40422442942 do GitHub Actions](https://github.com/MatheusMuniz23/acessilia/actions/runs/40422442942)
validou o commit `d8751d03c5e8eaf55080463a4311893536a3f7f8`: passaram 1.775
testes do Core, 796 do Docstruct e 250 do SDK. O workflow normal excluiu 51
E2E e não encontrou testes ignorados inesperadamente. Essas contagens se
referem àquela execução específica, não a commits posteriores.

As alterações estão em revisão no
[PR #309 do Core](https://github.com/A11yDevs/acessilia/pull/309). A divergência
anterior do manifesto foi corrigida com tradução por requisição e idioma
explícito no teste de referência; consulte a
[nota de localização](manifest-localization.pt-br.md).

Nenhum benchmark de dataset ou rollout de produção foi realizado. Os
armazenamentos independentes não se tornam compartilhados, e não há garantia
de disponibilidade quando todos os provedores falham. A continuidade durante
a falha do armazenamento exige implantar a alteração complementar da Toolbox
junto ao fallback do Core.
