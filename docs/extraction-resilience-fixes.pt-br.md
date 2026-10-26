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

## Validação e conclusão

As regressões foram exercitadas antes e depois das alterações. Passaram os
81 testes direcionados do Core e os 250 testes do SDK. Isso não constitui
avaliação da qualidade da extração. Nenhum benchmark de dataset ou rollout foi
executado. Na suíte completa do Core, passaram 1.771 testes, 51 E2E foram excluídos e
permaneceu uma divergência de manifesto que também ocorre na revisão-base sem
alterações. Essa falha preexistente está fora destas correções; a suíte completa
ainda não está totalmente aprovada.

As mudanças evitam extrações desnecessárias, preservam resultados úteis diante
de falhas recuperáveis e retiram a dependência de artefatos entre implantações
independentes na entrada inicial. Elas não tornam armazenamentos independentes
compartilhados nem garantem disponibilidade quando todos os provedores falham.
O PR permanece em rascunho para revisão, com o resultado completo dos testes na descrição.
