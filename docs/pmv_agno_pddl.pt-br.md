# PMV 2.1 — Agno, manifesto, PDDL, comparação e execução nominal

> English version: [English](pmv_agno_pddl.md)

## Objetivo

Esta versão valida o ciclo mínimo:

```text
documento
  → Agente Informacional-Estrutural (Agno + Docling)
  → processing-manifest.json
  → Agente Planejador (Agno + ferramentas PDDL)
  → problem.pddl
  → nominal-plan.json
  → Agente Executor (Agno Workflow)
  → execution-report.json + manifesto revisado
```

O Agno coordena ferramentas e o workflow. Extração, compilação do problema,
validação de contratos e aplicação de efeitos são funções determinísticas.
Nenhum LLM escreve PDDL diretamente.

## Compatibilidade do macOS

- Python 3.11 ou 3.12;
- `docling==2.0.0`;
- `docling-core==2.0.0`;
- `agno==3.0.5`;
- Fast Downward opcional.

```bash
uv sync --extra dev
uv run python scripts/generate_pmv_schemas.py
uv run pytest
```

O Agno está fixado no `pyproject.toml` e travado no `uv.lock`. O Docling não é
dependência do projeto; instale-o no ambiente com
`uv pip install docling==2.0.0 docling-core==2.0.0`.

O Fast Downward só é necessário ao usar `--planner fast-downward` ou
`--planner both`. O backend `internal` é o planner de referência do PMV e
funciona sem binário externo.

## 1. Agente Informacional-Estrutural

`InformationalStructuralAgent` constrói um `agno.agent.Agent` com a ferramenta
`extract_processing_manifest`. O método Python `process()` usa a mesma
implementação determinística e permite testes sem uma chamada a LLM.
Um modelo Agno pode ser injetado pelo argumento `model`; o CLI não precisa de
chave de API porque chama a ferramenta determinística diretamente.

```bash
uv run python scripts/pmv.py manifest documento.pdf \
  -o output/processing-manifest.json \
  --no-ocr
```

O manifesto 1.1 acrescenta a cada obrigação:

- métodos admissíveis;
- custos inteiros não negativos por método;
- tentativas observadas;
- resultado de cada tentativa.

O arquivo só é persistido depois de passar pelo modelo Pydantic e pelo JSON
Schema Draft 2020-12.

## 2. Agente Planejador e processador PDDL

`PlannerAgent` carrega um par inseparável:

- `core/planning/domains/domain_v2.3.pddl`;
- `core/planning/domains/domain_description_v2.3.md`.

O carregador verifica versão, nome, hashes e cláusulas obrigatórias. O
compilador:

1. escolhe as obrigações-raiz;
2. calcula o fechamento transitivo das predecessoras;
3. projeta estado, tipos, dependências, métodos, tentativas e custos;
4. gera `problem.pddl`;
5. exige `(:metric minimize (total-cost))`;
6. valida a projeção antes de chamar o planner.

```bash
uv run python scripts/pmv.py plan output/processing-manifest.json \
  -o output
```

Por padrão, obrigações já marcadas como `selected` são raízes. Se nenhuma
estiver marcada, todas as obrigações não satisfeitas são selecionadas. Para
escolher raízes:

```bash
uv run python scripts/pmv.py plan output/processing-manifest.json \
  -o output \
  --select obligation-describe-image-000012
```

### Backends

Planner interno:

```bash
uv run python scripts/pmv.py plan output/processing-manifest.json \
  -o output \
  --planner internal
```

Fast Downward:

```bash
uv run python scripts/pmv.py plan output/processing-manifest.json \
  -o output \
  --planner fast-downward \
  --fast-downward /caminho/fast-downward.py \
  --fast-downward-search 'astar(blind())'
```

`astar(blind())` é o padrão conservador porque preserva custos e suporta
axiomas/predicados derivados. Um alias pode ser informado explicitamente com
`--fast-downward-alias`, desde que suas heurísticas suportem os recursos do
domínio 2.2.

O backend interno não pretende substituir um planner geral. Ele explora a
estrutura específica do domínio 2.2: ordena o DAG de obrigações e escolhe o
método admissível não tentado de menor custo. É um oráculo simples e
reprodutível para validar o PMV.

### Execução dos dois backends

Para estudos diferenciais:

```bash
uv run python scripts/pmv.py plan output/processing-manifest.json \
  -o output \
  --planner both \
  --fast-downward /caminho/fast-downward.py \
  --fast-downward-search 'astar(blind())' \
  --preferred-plan internal
```

O domínio é carregado uma vez e o manifesto é compilado uma vez. Portanto,
ambos os backends recebem os mesmos bytes de `domain_v2.3.pddl` e
`problem.pddl`, identificados por SHA-256.

As saídas são:

```text
output/
├── problem.pddl
├── nominal-plan.internal.json
├── nominal-plan.fast-downward.json
├── nominal-plan.json
└── planning-comparison.json
```

`nominal-plan.json` é uma cópia lógica do backend definido por
`--preferred-plan` e pode ser fornecido diretamente ao Executor. O padrão é
`internal`; use `--preferred-plan fast-downward` para executar o plano do Fast
Downward.

Se apenas um backend resolver o problema, seu plano ainda é preservado e o
relatório recebe o veredito `inconclusive`. O comando só deixa de produzir o
plano canônico quando justamente o backend preferido falha.

## 3. Comparação para estudos

Antes da comparação, cada plano passa por validação independente de:

- hashes e identidade do domínio e problema;
- fechamento de obrigações selecionadas;
- precondições e ordem causal;
- método admissível, disponível e ainda não tentado;
- tipo e custo de cada obrigação;
- término em `complete-job`.

O relatório distingue quatro vereditos:

| Veredito | Significado |
|---|---|
| `identical` | mesmas ações, parâmetros, métodos, custos e ordem |
| `equivalent` | mesmo conteúdo semântico e custo, com ordem diferente apenas entre ações independentes |
| `different` | ambos resolvem, mas custo, métodos, ações ou fechamento divergem |
| `inconclusive` | ao menos um backend não produziu um plano válido |

Além do veredito, `planning-comparison.json` registra:

- tempo de parede de cada backend;
- configuração e estatísticas publicadas pelo Fast Downward;
- custo total e quantidade de passos;
- igualdade do fechamento e das obrigações executadas;
- igualdade da seleção de métodos;
- igualdade da sequência e do multiconjunto de ações;
- diferença de custo no sentido Fast Downward menos interno;
- passos exclusivos de cada resultado;
- tipo e mensagem de erro, quando houver.

Coincidência de custo isolada não é tratada como equivalência. Por outro lado,
uma diferença de ordem entre obrigações causalmente independentes não é
classificada erroneamente como divergência.

## 4. Plano nominal JSON

O plano contém:

- identidade e hashes do domínio e da descrição;
- identidade, revisão e hash do manifesto;
- hash do `problem.pddl`;
- backend de planejamento;
- fechamento selecionado;
- custo total esperado;
- ações tipadas e ordenadas.

O efeito de `execute-obligation` significa sucesso no modelo nominal. O
Executor só confirma esse efeito depois que o handler retorna
`success=true` e `validated=true`.

## 5. Agente Executor com Agno Workflow

Cada ação do plano torna-se um `agno.workflow.Step`. O `Workflow` executa os
passos em sequência e interrompe no primeiro erro.

Dry-run, sem confirmar efeitos:

```bash
uv run python scripts/pmv.py execute \
  output/processing-manifest.json \
  output/nominal-plan.json \
  -o output/execution
```

Execução real requer handlers:

```bash
uv run python scripts/pmv.py execute \
  output/processing-manifest.json \
  output/nominal-plan.json \
  -o output/execution \
  --live \
  --handler-module meu_projeto.handlers
```

O módulo deve fornecer:

```python
from core.execution.models import MethodResult


def describe_image(manifest, obligation_id):
    # chama a ferramenta, valida o resultado e produz artefatos
    return MethodResult(
        success=True,
        validated=True,
        message="Descrição validada",
        artifacts=[],
    )


def register_handlers(registry):
    registry.register("vision-description", describe_image)
```

`examples.demo_handlers` permite exercitar o caminho `--live`, mas é
explicitamente simulado e não deve ser usado em produção.

Em caso de falha:

- a tentativa é registrada no manifesto;
- o efeito `satisfied` não é confirmado;
- o relatório indica falha ou `replan-required`;
- uma nova compilação emite `(tried obrigação método)`;
- o planner escolhe outra alternativa, quando houver.

### 5.1 Método `dual-provider-fusion`

O método `dual-provider-fusion` (Fase 5) representa a extração fundida de dois
providers de toolbox (por padrão `docling` + `mineru`) via `docstruct.fusion`.
O handler registrado em `PddlAccessibilityOrchestrator._build_executor`
reutiliza `backend.pipeline.fusion.extract_fused`, persiste o payload fundido
em `data_dir/artifacts/fusion/<obligation_id>.json` e o retorna em
`MethodResult.artifacts`. O `ExecutorAgent` incorpora o artefato ao manifesto
e associa seu `artifact_id` à tentativa executada (proveniência).

O handler é **estrito**: se só um provider participou (o fallback
single-provider dentro de `extract_fused`), a ação `dual-provider-fusion`
planejada é tratada como **falha**, registrando `(tried ...)` e permitindo
replanejamento para um método single-provider. Isso mantém a semântica
planejada alinhada com o que realmente foi executado.

Regras de compilação:

- só é emitido como admissível quando `FUSION_MODE=dual`;
- custo maior que o equivalente single-provider, de modo que o planner o
  prefira só quando a qualidade do texto é crítica ou o método single não
  está disponível;
- o domínio PDDL em si não muda — `dual-provider-fusion` é apenas outro
  símbolo `method` com seus próprios `supports`/`admissible`/`execution-cost`.

O `FusionAgent` (`backend/core/agents/fusion_agent.py`) expõe as ferramentas
determinísticas `fuse_providers`, `audit_document`, `classify_block` e
`needs_reinfer` sobre a biblioteca pura `docstruct`, seguindo o mesmo padrão de
núcleo determinístico + envelope Agno opcional que o agente
Informacional-Estrutural. Veja [docstruct_algorithms.pt-br.md](docstruct_algorithms.pt-br.md)
para saber como funcionam os algoritmos subjacentes.

### 5.3 Agentes adicionados para o Dr.DocBench (PR #125)

Mais quatro agentes seguem o mesmo padrão (método `process_*` puro + envelope
JSON), cada um envolvendo uma política determinística do `docstruct`:

| Agente | Ferramentas | Biblioteca |
|---|---|---|
| `AdjudicationAgent` | `route_page`, `decide_from_transcription`, `filter_decisions`, `judge_pair`, `should_judge`, `select_page`, `swap_low_agreement`, `oracle_headroom` | `fusion.adjudication`, `fusion.judge`, `fusion.page_select`, `fusion.oracle` |
| `PageLevelAgent` | `fuse_page`, `select_page`, `swap_low_agreement`, `page_agreement`, `join_tail`, `move_header_footer_to_end`, `upscale_factor`, `decide_orientation` | `fusion.page_select`, `fusion.tailjoin`, `fusion.hf_end`, `imaging.policy` |
| `OrderAdjudicationAgent` | `parse_order`, `kendall_tau`, `complete_order`, `adjudicate_order`, `refine_reading_order` | `fusion.xycut` |
| `TableSpecialistAgent` | `extract_table`, `normalize_table`, `is_valid_table`, `build_candidates`, `select_table`, `select_greedy` | `fusion.table_specialist` |

O `FusionAgent` também ganhou as ferramentas de pós-processamento determinístico
(`chunk_verse`, `extract_line_numbers`, `join_tail`, `guard_repetition`,
`normalize_text`, `normalize_formula`, `refine_reading_order`,
`move_header_footer_to_end`).

O domínio v2.3 adiciona as obrigações correspondentes (`adjudicate-page`,
`fuse-providers`, `refine-reading-order`, `normalize-formula`,
`rescue-omitted-block`, `guard-repetition`, `join-tail-blocks`,
`select-table-source`, `chunk-verse`, `extract-line-numbers`,
`normalize-text`). A estrutura PDDL não muda: cada uma é um símbolo comum de
`obligationkind` com `supports`/`admissible`/`execution-cost` próprios. Métodos
determinísticos custam 5–15; os que consomem modelo custam 40–60, então o
planner só recorre a eles quando o caminho determinístico não está disponível.

## 6. Execução ponta a ponta

```bash
uv run python scripts/pmv.py pipeline documento.pdf \
  -o output/job-001 \
  --no-ocr \
  --planner both \
  --fast-downward /caminho/fast-downward.py \
  --preferred-plan internal \
  --execute-dry-run
```

Saídas principais:

```text
output/job-001/
├── processing-manifest.json
├── problem.pddl
├── nominal-plan.json
├── nominal-plan.internal.json
├── nominal-plan.fast-downward.json
├── planning-comparison.json
├── manifest-after-execution.json
└── execution-report.json
```

## 7. Contratos versionados

| Arquivo | Contrato |
|---|---|
| `processing_manifest.schema.json` | estrutura, observações, obrigações, custos e tentativas |
| `nominal_plan.schema.json` | plano nominal auditável |
| `planning_comparison.schema.json` | resultados e comparação normalizada dos dois planners |
| `execution_report.schema.json` | passos observados e decisão de replanejamento |
| `domain_v2.3.pddl` | semântica geral das ações e custos |
| `domain_description_v2.3.md` | contrato humano e regras do compilador |

Os três JSON Schemas são gerados dos modelos Pydantic:

```bash
uv run python scripts/generate_pmv_schemas.py
```

O CI deve falhar se os arquivos gerados divergirem dos schemas versionados.

## Limites do PMV

- o domínio trata um documento/job por instância;
- o planner interno só cobre o domínio de obrigações 2.2;
- a comparação cobre planos e métricas publicadas pelos backends, não mede a
  qualidade dos artefatos produzidos na execução;
- os métodos reais de descrição, linearização, verbalização e exportação
  ainda precisam ser registrados;
- o workflow interrompe após falha e devolve o estado para uma nova chamada
  ao Planejador; o laço automático de replanejamento fica para a próxima
  iteração;
- credenciais e caminhos de ferramentas permanecem fora do PDDL.
