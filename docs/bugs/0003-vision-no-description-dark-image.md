# 🐛 Modelo de visão retorna recusa ("não há imagem"/"não posso descrever") para imagens válidas, de forma inconsistente — e o pipeline entrega sem validar

## Identificação
| Campo | Valor |
|---|---|
| **ID** | BUG-0003 |
| **Data** | 2026-09-01 |
| **Reportado por** | Pedro Alano |
| **Severidade** | 🟠 Alta (falha silenciosa de acessibilidade em entrada válida) |
| **Status** | Aberto · **confirmado como questão de modelo** (ver comparativo) |
| **Link da issue** | <preencher ao abrir no GitHub> |

## Ambiente
| Item | Valor |
|---|---|
| SO | Windows 11 · Python 3.11 |
| Branch / commit | `main` @ `5c7cf41` |
| Motor / estruturador | legacy / docling |
| IA | ollama `llava:7b` (CPU) |
| Interface | API REST |

## Resumo
Com o `llava:7b`, imagens **válidas** às vezes recebem como "descrição" uma **recusa do modelo** — ex.: *"Não há imagem anexada para descrever"*, *"Desculpe, não posso fornecer uma descrição…"*. O comportamento é **inconsistente**: a mesma imagem ora é descrita, ora recusada. O pipeline **aceita e entrega** essa recusa como descrição final — inclusive no **TXT e no áudio (MP3)**, degradando silenciosamente a acessibilidade.

## Entrada usada
- `yoga.jpg` (silhueta ao entardecer) e `penguins.png` (controle). Anexar em `images/`.
- **Não depende da imagem** — ver evidência de inconsistência abaixo.

## Passos para reproduzir
1. App com `AI_CLIENT=ollama`, `OLLAMA_MODEL=llava:7b`.
2. Enviar uma imagem (API `POST /api/v1/jobs` ou painel). **Repetir algumas vezes.**
3. Em parte das execuções, o TXT sai apenas com uma recusa ("não há imagem"/"não posso…").

## Resultado esperado
Sempre uma descrição textual da imagem.

## Resultado obtido — inconsistente (mesma imagem, resultados opostos)
- **yoga:** no pipeline → recusou; em teste direto → 1x descreveu bem, 2x recusou.
- **pinguins:** no pipeline → descreveu; em teste direto → 1x meia-recusa, 1x descreveu.

A frase de recusa **não existe no código-fonte** (busca em `backend/`) — é a **saída literal do modelo**, não um fallback do sistema.

## Causa raiz
1. **Modelo `llava:7b` não-confiável:** produz **recusas espúrias/aleatórias** em imagens válidas. **Confirmado** pelo [comparativo de modelos](comparativo-modelos-visao.md): modelos melhores (`dots-3-note-preview`, `minimax-m3`) descreveram as **mesmas** imagens — inclusive a yoga — de forma **consistente e detalhada**.
2. **Falta de validação (gap de código):** o pipeline não detecta a recusa e a entrega como resultado final.

## Correção sugerida
- **Modelo:** trocar por um de visão mais capaz/confiável (ver [comparativo](comparativo-modelos-visao.md)).
- **Robustez (independe do modelo):** validar a saída de visão e **re-tentar/sinalizar** quando indicar recusa — heurísticas: resposta muito curta; contém "não há imagem"/"não posso"/"no image"/"cannot see"; tempo de inferência anormalmente baixo. Nunca embutir uma recusa no alt-text/áudio final.

## Impacto em testes / regressão
- **Coberto por teste?** Não.
- **Sugestão para o CI/CD:** conjunto de imagens validando descrição **não-vazia e não-recusa**; rodar 2-3x por imagem para captar o não-determinismo.

## Evidências
- Execução E2E de 2026-09-01 (`e2e_cache_test.py`), job `e770e338`: yoga → recusa.
- Comparativo de modelos ([comparativo-modelos-visao.md](comparativo-modelos-visao.md)): llava inconsistente; dots-3 e minimax-m3 descreveram ambas as imagens.
