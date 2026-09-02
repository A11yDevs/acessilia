# 🐛 <Título curto e específico do bug>

> Copie este arquivo para cada bug novo. Nome sugerido: `NNNN-slug-curto.md`
> (ex.: `0002-cache-imagem-descricao-errada.md`). Anexe a imagem/arquivo usado em `images/`.

## Identificação
| Campo | Valor |
|---|---|
| **ID** | BUG-NNNN |
| **Data** | AAAA-MM-DD |
| **Reportado por** | <seu nome> |
| **Severidade** | 🔴 Crítica · 🟠 Alta · 🟡 Média · 🟢 Baixa |
| **Status** | Aberto · Em análise · Corrigido · Fechado |
| **Link da issue** | <URL do GitHub, se já aberta> |

## Ambiente
| Item | Valor |
|---|---|
| SO | Windows 11 / Linux / … |
| Python | 3.11 |
| Branch / commit | `main` @ `<hash>` |
| Motor (`PIPELINE_ENGINE`) | legacy / pddl |
| Estruturador (`STRUCTURER`) | docling / pymupdf |
| IA (`AI_CLIENT` + modelo) | ollama `llava:7b` / openrouter `…` |
| Interface | web / api / telegram |

## Resumo
<Uma frase: o que quebra ou está errado.>

## Entrada usada (qual arquivo/imagem)
- **Arquivo:** `<nome>` (ou dataset `input/00X`)
- **Tipo / tamanho / páginas:** …
- **Anexo:** salvar em `images/` ao lado deste `.md` (ou referenciar o id do dataset).

## Passos para reproduzir
1. …
2. …
3. …

## Resultado esperado
<O que deveria acontecer.>

## Resultado obtido
<O que aconteceu de fato. Cole o log/erro relevante:>

```
<log ou traceback>
```

## Causa raiz (se identificada)
<Arquivo:linha + explicação curta.>

## Correção sugerida (se houver)
<Trecho de código ou descrição.>

## Impacto em testes / regressão
- **Coberto por teste automatizado?** Sim / Não
- **Se não:** teste sugerido para o CI/CD evitar regressão: <descrição>

## Evidências
- Arquivos gerados: `var/temp/output/<task_id>/`
- Prints / logs / arquivos anexos: …
