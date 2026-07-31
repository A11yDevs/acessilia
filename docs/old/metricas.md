# Métricas e observabilidade

A ideia aqui é ter visibilidade do sistema sem depender do painel do os.agno.com. Rodando tudo local e open-source, e sem mensalidade.

Como não existe uma tela só que mostra tudo, há a necessidade de integrar diferentes ferramentas, com diferentes funcionalidades, para atingir o melhor resultado possível.

## Propostas

- **Langfuse:** é a dos agentes de IA em si (trace de LLM); o que o modelo recebeu, o que respondeu, quantos tokens gastou, quanto custou e quanto tempo levou cada chamada. Cada execução do VisionAgent ou do DataAgent vira um registro que dá pra abrir e inspecionar.

- **Prometheus:** é o da máquina e da operação, métricas numéricas ao longo do tempo; uso de CPU, memória, quantas requisições por segundo, a latência no percentil 95, quantos erros...

- **Grafana:** desenha os gráficos do Prometheus

- **Loki:** é o dos logs; junta todas aquelas mensagens que o loguru já escreve (processando página tal, erro na região X...) num lugar só e pesquisável, em vez de ficar abrindo arquivo na mão. O Grafana lê ele e mostra os logs na mesma tela dos gráficos, então dá pra ver um pico de erro e ir direto nas linhas daquele momento.

- **Locust:** é o dos testes de carga; dispara tráfego no sistema pra ver quanto ele aguenta, medindo tempo de resposta e quantas requisições falham. Ele já tem uma tela própria ao vivo durante o teste; e, se quiser ver junto com o resto, dá pra exportar essas métricas pro Prometheus e desenhar no Grafana (isso é um passo à parte). Vale lembrar que o tempo que o Locust mede é o do lado cliente (com rede), diferente da latência de dentro do app que o Prometheus pega.

Um não substitui o outro. O Langfuse não sabe nada sobre CPU, e o Grafana não mostra o prompt de uma chamada específica. Então o normal é ter as duas telas: Grafana+Prometheus pro lado operacional, Langfuse pro lado de LLM.

## Como o Agno se conecta nisso

O Agno emite traces via OpenTelemetry, então a integração é direta. Basta instrumentar o runtime uma vez, no startup, com o AgnoInstrumentor apontando pro Langfuse. A partir daí toda execução de agente é capturada automaticamente, tanto no pipeline real quanto no painel, sem mexer na lógica de nenhum agente.

## O que o runtime já entrega de graça

Antes de pensar em ferramenta, vale saber que uma boa parte das métricas o próprio Agno já calcula sozinho, em toda execução, sem precisar instalar nada. Cada run volta com um objeto de métricas que traz: tokens de entrada e de saída, total de tokens, custo estimado, tempo até o primeiro token, duração total, tokens de cache e qual modelo/provedor foi usado. Exemplo do que sai numa chamada:

```
input_tokens=6, output_tokens=1, total_tokens=7, cost=4.3e-06, time_to_first_token=2.09s, duration=2.09s, model=google/gemini-2.5-flash
```

E o runtime guarda isso no banco junto de cada run. Ou seja, aquelas métricas de LLM (tokens, custo, latência, contagem de execuções) que o os.agno.com mostra, dá pra ler os runs pela API do próprio runtime e desenhar numa interface nossa, que é exatamente o que o painel deles faz.

Então a régua fica assim: tokens, custo e latência por chamada já são nossos, é só ler e mostrar. O Langfuse entra quando a gente quer o que o básico não dá, tipo histórico retido por muito tempo, evals de qualidade e filtros mais pesados. E o Prometheus/Loki são pra um dado diferente (servidor e logs), que nem o os.agno.com cobre.

## Na prática

Quando roda um teste de carga dá pra olhar as duas telas ao mesmo tempo: o Locust dispara o tráfego, o Grafana mostra CPU e latência subindo ao vivo, e o Langfuse mostra o custo e os traces das chamadas naquele intervalo. Aí dá pra cruzar as coisas, tipo ver que quando a carga subiu a latência do Vision disparou e o custo por minuto triplicou.

## Workflow x agentes soltos

Se um dia a gente envelopar o pipeline como um Workflow do Agno (em vez de rodar os agentes soltos), ele passa a retornar métricas em três níveis: o run inteiro (custo/tokens/duração totais do documento), a quebra por etapa (Reader, Vision, Data, Editor) e o acumulado por sessão. Isso entrega de graça aquele "custo por documento" e "duração por estágio" que hoje só sai somando na mão.

O porém no nosso caso: como as regiões são processadas em paralelo dentro de um step-function (fan-out dinâmico), os tokens desse estágio não somam sozinhos ali, esse pedaço a gente ainda juntaria na mão. Então vale a pena se observabilidade do pipeline por documento importar.
