# Acessília na shared task Dr.DocBench (DocInsights 2026)

> English version: [English guide](README.md)

Este diretório é o ponto de entrada permanente da participação da Acessília na shared task
[Dr.DocBench](https://huggingface.co/datasets/2077AIDataFoundation/DrDocBench) da DocInsights 2026:
parsing de documentos por página para Markdown, pontuado no EvalAI por distância de edição de texto,
TEDS de tabelas, CDM de fórmulas e ordem de leitura (Overall = média por página dos componentes
disponíveis).

Ele guarda congelados os dois resultados abaixo, um script para conferi-los e reproduzi-los
(`run.sh`) e as versões de software por trás deles ([VERSIONS.md](VERSIONS.md)). O código dos
experimentos está preservado, exatamente como rodou, na tag
[`drbench-2026-snapshot`](https://github.com/A11yDevs/acessilia/tree/drbench-2026-snapshot/scripts/drbench);
o que cada script faz e para onde foi seu algoritmo no produto está em
[docs/drbench/experiments/CODE.pt-br.md](../../docs/drbench/experiments/CODE.pt-br.md).

## Resultados

| | Execução | Método | EvalAI Overall | Text ED ↓ | Table TEDS | Formula CDM | Ordem de leitura |
|---|---|---|---|---|---|---|---|
| **Melhor submissão** | `hyb-v29-judge2-televm-adf-tj3-20261009` | além do artigo: múltiplas fontes com juiz VLM (abaixo) | **71.01** | 0.2708 | 56.16 | 0.16 | 75.87 |
| **Experimento do artigo** | *pendente* | Docling × MinerU (Tree Differ) | *pendente* | | | | |

Split de teste: 509 páginas (34 documentos × até 15 páginas contíguas, 28 assuntos).

## Melhor submissão (71.01)

### Artefatos congelados — [`submissions/best/`](submissions/best/)

| Arquivo | O quê | SHA-256 |
|---|---|---|
| `submission.zip` | o zip submetido ao EvalAI (baixado como `6d9f2b09-19a3-4e5d-8483-56e1854f49c.zip`) | `08ec980d4bc9ec27acdd494c5c676830169c5506085f9f445bbc327470353a64` |
| `predictions.jsonl` (dentro do zip) | 509 linhas `{subject, document_id, page, markdown}` | `2b83be1409b50a4051e2081dffc401cf501631b018c7f56b2d31513a883b11e3` |
| `evalai-result.json` | o resultado do EvalAI para esse zip (baixado como `a7f14c6c-c408-467f-9191-add3d582ab.json`; um literal Python, guardado byte a byte) | `6b4d9e81dfff9168b8fc992a09eafdd8cfee360f375f8e49e80c3c76e534ee13` |

### Como foi produzida

Todas as execuções estão em [SUBMISSIONS-LEADERBOARD.pt-br.md](../../docs/drbench/experiments/SUBMISSIONS-LEADERBOARD.pt-br.md);
as decisões, com os números de tune/holdout, em [LOOP.pt-br.md](../../docs/drbench/experiments/LOOP.pt-br.md).
Os jobs rodaram na partição Slurm `h100n2` (1 × H100); os scripts dos jobs estão na tag em
`scripts/drbench/experiments/slurm/`.

1. **Extração pelos provedores**, com páginas rotacionadas detectadas (RapidOCR) e re-inferidas
   endireitadas: Docling (`docling-serve` 1.32) e MinerU 3.4 `hybrid-engine` (as fontes do `differ-v15-hyb`).
2. **Linha base `differ-v29-adf`**:
   fusão block-level dos dois provedores pelo `tree_differ_v2.py` com os argumentos do `differ-v15-hyb`,
   depois adjudicação de texto e seleção de ordem de leitura pelo Qwen3-VL-32B (`differ-v24-AOs`, job 34364);
   `loop_post --split-lines 150 --smallcaps` (v25); seleção de página inteira pelo Qwen3-VL-32B onde os
   provedores discordam, com filtro de comentários (v26b, job 34373); seleção de página do dots.ocr e
   `rep_guard` (v28c, job 34413); `pagenum_add` (v29-pn); e um documento rotacionado de 15 páginas refeito
   com o dots.ocr numa cópia endireitada e ampliada 3× (v29-adf, job 34433).
3. **Linha Tele `teleocr-up2m2-vm-fb-adf`**: parsing de página inteira pelo TeleOCR com páginas < 800 px e
   de 800–1200 px ampliadas 2× (job 34448), blocos unidos guiados pela v29-pn (LOOP #42), fallback para a
   v29 onde o Tele é curto (razão 0.3, 24 páginas) e o mesmo documento do dots.ocr.
4. **Escolha de página `hyb-v29-judge2-televm-adf`** (LOOP #45): um juiz pareado Qwen3-VL-32B
   (`vlm_page_judge.py`, nas duas ordens, probabilidade do primeiro token) nas páginas em que as duas
   linhas divergem. Usa a página do Tele quando `pB > 0.5` no julgamento v29-adf vs Tele-vm-fb (job 34458)
   ou, nas páginas que esse julgamento não cobriu, quando `pB > 0.2` no julgamento anterior (LOOP #44):
   87 de 509 páginas.
5. **Tail-join `tj3`** (LOOP #51): o `pnpos.py` pega a posição do número de página no layout do TeleOCR
   (dots.ocr como reserva); o `tailjoin3.py SRC OUT POS 50 3 hdr` junta os blocos finais curtos ou, com o
   número no rodapé, mantém os blocos e põe o número por último.
6. **Submissão**: `build_submission_manifest.py` (linhas na ordem do manifesto oficial).

**Modelos externos.** Além do Docling e do MinerU, este resultado usa Qwen/Qwen3-VL-32B-Instruct-FP8
(adjudicação, seleção de página, juiz), XingChen-AGI/TeleOCR, dots-studio/dots.ocr e RapidOCR
(orientação). Ele vai além do método do artigo e precisa ser reportado com esses modelos declarados.

**Dev vs teste.** O mesmo pipeline fez 87.33 no análogo do dev (tune 90.60, holdout 83.11) e 71.01 no
teste: uma diferença de 16.3 pontos, contra 7.7 do `differ-v15-hyb` (dev 78.1, teste 70.37). Parte dela
vem da janela do teste (15 páginas contíguas por documento contra páginas isoladas no dev).

### Reproduzir

```bash
scripts/drbench/run.sh best verify              # hashes, 509 páginas únicas, scores do EvalAI
scripts/drbench/run.sh best replay INPUTS_DIR   # passos 4–6 a partir das entradas congeladas, conferência byte a byte
scripts/drbench/run.sh best full                # passos 1–3: aponta para os jobs de GPU (não é bit a bit)
```

- **verify** precisa só deste diretório.
- **replay** refaz os passos 4–6, que não usam modelo, com o código da tag e apenas Python 3, a partir
  das saídas intermediárias dos passos 1–3 e dos dois julgamentos, e compara byte a byte o
  `predictions.jsonl` resultante com o congelado. Essas entradas estão no cluster; o
  [`collect_inputs.sh`](collect_inputs.sh) as empacota (junto com as versões) e roda o replay lá.
  **Situação: o pacote de entradas ainda não foi arquivado.**
- **full** roda de novo os passos de GPU. A inferência em GPU não é determinística: compare scores,
  não hashes.

## Experimento do artigo

*Pendente.* Esta seção vai trazer a execução do artigo, sua submissão congelada e o resultado do
EvalAI em `submissions/paper/`, e o `run.sh paper`. Dentro do método do artigo (Docling × MinerU), a
melhor submissão confirmada nos registros é a `differ-v15-hyb-20260922`, EvalAI 70.37.

## Veja também

- [Runbook de reprodução](../../docs/drbench/experiments/RUNBOOK.pt-br.md) — ambiente, replay congelado, custos de GPU
- [RESULTS.json](../../docs/drbench/experiments/RESULTS.json) — números e hashes dos zips de todas as submissões
- [Harness de benchmark](../../docs/bench.pt-br.md) — como o core é medido no Dr.DocBench hoje
