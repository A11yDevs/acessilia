# PMV 2.1 — Agno, manifesto, PDDL, comparação e execução nominal

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
- `agno==2.8.5`;
- Fast Downward opcional.

```bash
poetry lock
poetry install
poetry run python scripts/generate_pmv_schemas.py
poetry run pytest
```

O lock anterior foi produzido antes da inclusão do Agno e não integra o pacote
novo. Gere-o no próprio macOS; as versões críticas do Docling e do Agno já
estão fixadas no `pyproject.toml`.

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
poetry run a11y-pmv manifest documento.pdf \
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

- `core/planning/domains/domain_v2.2.pddl`;
- `core/planning/domains/domain_description_v2.2.md`.

O carregador verifica versão, nome, hashes e cláusulas obrigatórias. O
compilador:

1. escolhe as obrigações-raiz;
2. calcula o fechamento transitivo das predecessoras;
3. projeta estado, tipos, dependências, métodos, tentativas e custos;
4. gera `problem.pddl`;
5. exige `(:metric minimize (total-cost))`;
6. valida a projeção antes de chamar o planner.

```bash
poetry run a11y-pmv plan output/processing-manifest.json \
  -o output
```

Por padrão, obrigações já marcadas como `selected` são raízes. Se nenhuma
estiver marcada, todas as obrigações não satisfeitas são selecionadas. Para
escolher raízes:

```bash
poetry run a11y-pmv plan output/processing-manifest.json \
  -o output \
  --select obligation-describe-image-000012
```

### Backends

Planner interno:

```bash
poetry run a11y-pmv plan output/processing-manifest.json \
  -o output \
  --planner internal
```

Fast Downward:

```bash
poetry run a11y-pmv plan output/processing-manifest.json \
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
poetry run a11y-pmv plan output/processing-manifest.json \
  -o output \
  --planner both \
  --fast-downward /caminho/fast-downward.py \
  --fast-downward-search 'astar(blind())' \
  --preferred-plan internal
```

O domínio é carregado uma vez e o manifesto é compilado uma vez. Portanto,
ambos os backends recebem os mesmos bytes de `domain_v2.2.pddl` e
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
poetry run a11y-pmv execute \
  output/processing-manifest.json \
  output/nominal-plan.json \
  -o output/execution
```

Execução real requer handlers:

```bash
poetry run a11y-pmv execute \
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

## 6. Execução ponta a ponta

```bash
poetry run a11y-pmv pipeline documento.pdf \
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
| `domain_v2.2.pddl` | semântica geral das ações e custos |
| `domain_description_v2.2.md` | contrato humano e regras do compilador |

Os três JSON Schemas são gerados dos modelos Pydantic:

```bash
poetry run python scripts/generate_pmv_schemas.py
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
