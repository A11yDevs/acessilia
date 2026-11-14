# Política de segurança

Você também pode ler este documento em **inglês**: [English version](SECURITY.md).

## Versões suportadas

Apenas a versão mais recente implantada do core recebe correções de segurança.

| Versão | Suportada |
|---|---|
| 0.2.x | ✅ |
| Anterior à 0.2 | ❌ |

O SDK, o docstruct e a Toolbox seguem a release com que são distribuídos.

## Como relatar uma vulnerabilidade

**Não abra issue pública com detalhes de exploração ou prova de conceito.**

Use o **relato privado de vulnerabilidades** do GitHub:

1. Abra a aba **Security** do repositório.
2. Escolha **Report a vulnerability**.
3. Descreva o problema, o componente e a versão afetados, e os passos para reproduzir. Inclua o impacto e uma sugestão de correção, se tiver.

Se o botão **Report a vulnerability** não estiver disponível, abra uma issue mínima pedindo aos mantenedores um canal privado; não inclua detalhes técnicos nessa issue.

Um bom relato inclui uma reprodução mínima, o commit ou a tag da imagem testada e se o problema é explorável sem credenciais. Nunca inclua credenciais reais, documentos pessoais ou dados de terceiros; use amostras sintéticas.

## O que está no escopo

- a API e o pipeline de processamento do core (`backend/`, `frontend/`, `schemas/`);
- o SDK público (`libs/sdk`), o docstruct (`libs/docstruct`) e seus artefatos de release;
- a imagem Docker, os arquivos compose e os scripts de implantação deste repositório;
- problemas de dependências e de cadeia de suprimentos nos artefatos publicados por este repositório.

A Toolbox é um repositório separado; relate os problemas dela lá, ou aqui se o problema estiver no modo como este repositório a consome. Vulnerabilidades de serviços de terceiros e da plataforma Telegram estão fora do escopo.

## Nosso processo

- Confirmamos o recebimento em até **3 dias úteis**.
- Fazemos a triagem e confirmamos a severidade e as versões afetadas em até **10 dias úteis**.
- Mantemos quem reportou informado enquanto a correção é preparada e coordenamos a divulgação após uma release.
- Damos crédito nos advisories, a menos que a pessoa prefira anonimato.

A CI executa auditoria de dependências, CodeQL e varredura da imagem do container; um novo achado de severidade alta falha o build, a menos que uma exceção revisada esteja registrada. Espera-se que secret scanning e push protection estejam habilitados nas configurações do repositório.
