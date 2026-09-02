# Comparativo de modelos de visão — descrição acessível de imagens

**Data:** 2026-09-01 · **Autor:** Pedro Alano
**Relacionado:** [0003 — modelo de visão retorna recusa para imagem válida](0003-vision-no-description-dark-image.md)

## Objetivo
Verificar se a falha do [0003](0003-vision-no-description-dark-image.md) (imagem válida recebendo uma "não-descrição") é **questão do modelo** e comparar a qualidade das descrições entre modelos.

## Metodologia
- Mesmas **2 imagens** para todos: `yoga.jpg` (silhueta escura ao pôr do sol — a que falhou) e `penguins.png` (foto/ilustração de pinguins — controle).
- Mesmo **prompt**: *"Descreva esta imagem de forma detalhada e acessível, em português, para uma pessoa com deficiência visual."*
- Chamada **direta aos modelos** (fora do pipeline), via script `model_comparison.py` / `openrouter_free_vision.py`.
- Local: **Ollama `llava:7b`** (CPU). Remotos: modelos **gratuitos** via OpenRouter.

## Resultado

| Modelo | Origem | yoga (silhueta) | pinguins | Observação |
|---|---|---|---|---|
| **llava:7b** | Ollama (local) | ❌/✅ **inconsistente** | ⚠️ **inconsistente** | recusa espúria ("Desculpe, não posso…"); qualidade fraca quando funciona ("pingos") |
| **dots-studio/dots-3-note-preview:free** | OpenRouter | ✅ excelente | ✅ excelente | descrição rica: identificou a *Pose do Guerreiro II*, cores do céu, montanhas |
| **minimax/minimax-m3:free** | OpenRouter | ✅ ótima | ✅ ótima | descrição estruturada e precisa |
| thinkingmachines/inkling(-small):free | OpenRouter | ⛔ 403 | ⛔ 403 | "only available on agentic harnesses" |
| nvidia/nemotron-3.5-content-safety:free | OpenRouter | ⚠️ não descreve | ⚠️ não descreve | é modelo de **moderação** (retorna "User Safety: safe") |
| llama-3.2-11b-vision:free · qwen2.5-vl-72b:free · nemotron-nano-vl:free | OpenRouter | ⛔ 404 | ⛔ 404 | slug `:free` **indisponível** no momento |

### Inconsistência do `llava:7b` (a mesma imagem, resultados opostos)
- **yoga:** no pipeline → recusou; em teste direto → 1x descreveu bem, 2x recusou.
- **pinguins:** no pipeline → descreveu; em teste direto → 1x meia-recusa, 1x descreveu.

➡️ A falha **não depende da imagem** — é uma **recusa aleatória** do modelo.

## Amostras (imagem da yoga)

**llava:7b (local)** — *recusa:*
> "Desculpe, mas não posso fornecer uma descrição detalhada ou acessível de imagens para pessoas com deficiência visual."

**minimax/minimax-m3:free** — *descrição real:*
> "A fotografia mostra uma mulher em silhueta… praticando o que parece ser uma postura de yoga… semelhante à posição do 'guerreiro'. […] as pernas estão afastadas, com a perna direita estendida para trás e a esquerda à frente… Um braço está estendido horizontalmente para frente… O céu… apresenta uma rica tonalidade em tons de azul, roxo, lilás e cinza… Na parte inferior esquerda, a luz do entardecer aquece o cenário com tons dourados e alaranjados."

**dots-3-note-preview:free** — *descrição real (trecho):*
> "…a silhueta de uma mulher praticando ioga… a clássica **Pose do Guerreiro II**… O céu ocupa a maior parte do quadro… tons de azul profundo, roxo vibrante e lilás… No fundo, distante, vemos a silhueta de uma cordilheira de montanhas…"

## Conclusão
1. **O 0003 é confirmado como questão de modelo.** `llava:7b` produz **recusas espúrias e inconsistentes**; modelos melhores (**dots-3-note-preview** e **minimax-m3**) descreveram **as mesmas imagens — inclusive a yoga — de forma consistente e com alta qualidade**.
2. **Recomendação:** adotar um modelo de visão mais capaz. Entre os gratuitos testados, `minimax/minimax-m3:free` e `dots-studio/dots-3-note-preview:free` foram os melhores.
3. **Ressalva importante:** a disponibilidade dos modelos **gratuitos** no OpenRouter é **volátil** (vários deram 404/403). Para **produção**, não depender de um slug `:free` específico — preferir um modelo pago estável ou um modelo forte auto-hospedado.
4. **Independe do modelo:** o pipeline ainda deve **validar/re-tentar** a saída de visão (ver 0003, parte 2) — nunca embutir uma recusa no alt-text/áudio final.

## Reprodução
Scripts (na pasta de trabalho): `model_comparison.py` (llava + modelos fixos) e `openrouter_free_vision.py` (descobre e testa modelos de visão gratuitos disponíveis). Requer `OPENROUTER_API_KEY` no `.env`.
