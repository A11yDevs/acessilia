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
8. **Documentação com prioridade ao inglês e português brasileiro como língua oficial secundária**: todo o código-fonte (identificadores, comentários, docstrings, mensagens de log), documentação Markdown, issues, pull requests e mensagens de commit devem ser escritos em inglês — a língua obrigatória e autoritativa. O português brasileiro é a língua oficial secundária: desejável para toda a documentação, e todo espelho `*.pt-br.md` deve ser atualizado no mesmo PR sempre que sua fonte em inglês mudar. Em caso de divergência, a versão em inglês é autoritativa. Tradução e suporte a outras línguas é um objetivo secundário importante (internacionalização/i18n), voltado a uma audiência-alvo ampla e inclusiva; conteúdo localizado em outras línguas é bem-vindo, mas nunca bloqueia um merge. Conteúdo voltado ao usuário (mensagens do Telegram, saída renderizada, prompts para os modelos de IA) deve ser localizado conforme o locale do usuário — incluindo inglês e português brasileiro, e estendido a outras línguas conforme o esforço de i18n avança. Materiais educacionais são um domínio prioritário para a internacionalização: devem ser produzidos na língua da audiência sempre que possível, com inglês e português brasileiro como as línguas primárias suportadas.