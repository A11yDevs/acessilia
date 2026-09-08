# Constituição Arquitetural

Também disponível em **inglês (EUA)**: [English version](constitution.md)

## 1. Propósito
Entregar a conversão de documentos e imagens para formatos acessíveis por meio de:
- **Extração e planejamento determinísticos** (ordenação e validação de tarefas baseada em PDDL)
- **Processamento de IA multiagente** (agentes especializados coordenados pelo Agno para visão, dados e descrições)
- Descrições de alta qualidade em inglês (EUA) ou português brasileiro (determinadas pelo locale do usuário)
- Simples experiência de usuário baseada no Telegram, com degradação progressiva em falhas de IA

## 2. Princípios inegociáveis
1. Alinhamento ao código-fonte: cada regra desta constituição deve ser rastreável até módulos reais.
2. Acessibilidade em primeiro lugar: todas as saídas devem suportar leitores de tela e estrutura semântica.
3. Tolerância a falhas: o sistema deve se degradar graciosamente com fallback textual quando a IA falha.
4. Operação local e configurável: o comportamento deve ser dirigido por variáveis de ambiente e pastas locais.
5. Extração local primeiro: PDFs com base textual devem preferir extração local determinística antes de invocar IA.
6. Determinismo e inteligência híbridos: o sistema combina planejamento determinístico (processamento PDDL, geração do manifesto) com execução dirigida por IA para garantir confiabilidade e flexibilidade. Funções determinísticas são a fonte de verdade; LLMs fornecem interpretação e descrição.
7. Validação com container em primeiro lugar: a suíte de testes deve passar no container Docker (ambiente equivalente ao de produção) antes do merge. Testes no ambiente nativo são secundários e específicos de ambiente.