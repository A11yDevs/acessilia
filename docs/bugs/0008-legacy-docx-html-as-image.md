# 🐛 DOCX e HTML não funcionam no caminho legacy anunciado

## Identificação

| Campo | Valor |
|---|---|
| **ID** | BUG-0008 |
| **Data** | 2026-09-05 |
| **Reportado por** | Wryel Teodoro |
| **Severidade** | 🟠 Alta |
| **Status** | Aberto no legacy · reproduzido em ambiente isolado |

## Ambiente

| Item | Valor |
|---|---|
| SO | Linux |
| Python | 3.12.3 (revalidação isolada) |
| Branch / commit | [release/0.1.0](https://github.com/A11yDevs/acessilia/tree/release/0.1.0) @ `7a5e70f4809dd4bae29cfb772042d12784fc48b6` |
| Motor (`PIPELINE_ENGINE`) | `legacy`; leitura real pelo `ReaderAgent` |
| Estruturador (`STRUCTURER`) | `pymupdf` configurado; DOCX/HTML seguem para Pillow antes da extração estrutural |
| IA (`AI_CLIENT` + modelo) | Não utilizada; a decodificação falha antes do despacho aos agentes de IA |
| Interface | API / motor legacy |

## Resumo

DOCX e HTML não funcionam no caminho legacy anunciado. Formatos anunciados não processam no caminho padrão; A entrada aceita falha antes da extração apropriada.

## Entrada usada (qual arquivo/imagem)

- **Entrada:** `teste.docx` gerado por python-docx e `teste.html` mínimo.
- **Observação:** revalidação isolada com dados sintéticos; não depende de dados de usuários.

## Passos para reproduzir

1. Usar `release/0.1.0` no commit indicado em Ambiente e selecionar `PIPELINE_ENGINE=legacy`.
2. Gerar DOCX válido com python-docx e HTML mínimo; verificar que `validate_file` aceita ambos.
3. Executar `ReaderAgent.analyse_page` para cada entrada, pelo caminho de leitura usado pelo orquestrador legacy.
4. Observar `UnidentifiedImageError` nos dois formatos, antes de qualquer chamada de IA.

## Resultado esperado

Extração apropriada para esses formatos, ou rejeição explícita antes de aceitar job nesse motor.

## Resultado obtido

No `legacy`, a validação aceita os arquivos e o Pillow levanta `UnidentifiedImageError`. A revalidação desta release confirma a falha de leitura; não repetiu a comparação integrada com PDDL/Docling nem avaliou a saída de modelos.

```json
{
  "id": "BUG-0008",
  "engine": "legacy",
  "accepted_inputs_failing_in_reader": [
    {
      "extension": ".docx",
      "exception": "UnidentifiedImageError"
    },
    {
      "extension": ".html",
      "exception": "UnidentifiedImageError"
    }
  ]
}
```

## Causa raiz (se identificada)

A falha reproduzida ocorre na decodificação local do formato, antes de chamar qualquer modelo de IA.

[validators.py](../../backend/tools/validators.py) e configuração aceitam `.docx`/`.html`. [orchestrator.py](../../backend/agents/orchestrator.py) distingue somente PDF de não-PDF. [reader_agent.py](../../backend/agents/reader_agent.py), `analyse_page`, encaminha qualquer não-PDF para decodificação de imagem.

## Correção sugerida (se houver)

Roteamento por formato/capacidade do motor. Trocar somente `STRUCTURER=pymupdf` por `docling` não corrige o roteamento do `legacy`: `analyse_page` envia entradas não PDF para o leitor de imagem sem chamar o estruturador. Essa conclusão vem da inspeção do código; a reprodução atual utilizou PyMuPDF configurado.

## Rastreabilidade

- **Revalidação:** permanece em `release/0.1.0` @ `7a5e70f4809dd4bae29cfb772042d12784fc48b6`, verificado em 2026-09-06.

- **Introdução rastreada:** `a2b9400` (2026-05-19), substituição do pipeline que possuía parsers de DOCX/HTML pelo `AgenteUnico`, que trata qualquer entrada não PDF como imagem, mantendo as extensões permitidas.
- A revalidação da release confirma o encaminhamento indevido ao leitor de imagem no `legacy`. A comparação anterior com PDDL/Docling não constitui uma nova verificação desse motor nesta revisão.

## Evidências

- DOCX válido gerado por python-docx e HTML mínimo passam no validador; o ReaderAgent do legacy levanta UnidentifiedImageError para ambos, antes de usar IA.
- Verificação executada em 2026-09-06 sobre o commit da release indicado em Ambiente, com assertions dos resultados.
- Dados desta execução registrados no bloco JSON acima.
