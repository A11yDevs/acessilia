# 🐛 Página web gera links para a porta errada

## Identificação

| Campo | Valor |
|---|---|
| **ID** | BUG-0013 |
| **Data** | 2026-09-06 |
| **Reportado por** | Wryel Teodoro |
| **Severidade** | 🟠 Alta |
| **Status** | Aberto · reproduzido em ambiente isolado |

## Ambiente

| Item | Valor |
|---|---|
| SO | Linux |
| Python | 3.12.3 |
| Branch / commit | [release/0.1.0](https://github.com/A11yDevs/acessilia/tree/release/0.1.0) @ `7a5e70f4809dd4bae29cfb772042d12784fc48b6` |
| Motor (`PIPELINE_ENGINE`) | Não executado; página de download e resolução de URL no frontend web |
| Estruturador (`STRUCTURER`) | Não utilizado; a página recebe metadados de um resultado pronto |
| IA (`AI_CLIENT` + modelo) | Não utilizada; metadados da API simulados para verificar o destino dos links |
| Interface | Painel web / download |

## Resumo

No deployment padrão com API e web em portas distintas, o painel lista formatos cujos links retornam 404 na origem web.

## Entrada usada (qual arquivo/imagem)

- **Entrada:** Página de download com token e metadados sintéticos, usando o app web real em HTTP ASGI. A consulta à API é simulada.
- **Observação:** reprodução isolada com dados sintéticos, sem acesso a dados de usuários ou serviços externos reais.

## Passos para reproduzir

1. Obter metadados de download contendo a URL `/download/audit-token/txt`.
2. Abrir `/download/audit-token` na origem web, equivalente à porta 8001.
3. Seguir o link `/api/v1/download/audit-token/txt` renderizado na página.

## Resultado esperado

Baixar o arquivo ou encaminhar a solicitação a uma rota pública válida da API.

## Resultado obtido

A página responde 200; o link aponta para a mesma origem web e responde 404.

```json
{
  "id": "BUG-0013",
  "page_status": 200,
  "link": "/api/v1/download/audit-token/txt",
  "download_status": 404
}
```

## Causa raiz (se identificada)

[frontend/web/app.py](../../frontend/web/app.py), linhas 215–220, prefixa o link com `/api/v1`, mas esse app não expõe nem encaminha essa rota. [frontend/run.py](../../frontend/run.py) inicia API e web em portas distintas. O Compose não fornece um proxy para essas rotas. Um proxy externo configurado para `/api/v1` pode mascarar o problema; esse cenário não foi assumido na reprodução.

## Correção sugerida (se houver)

Implementar proxy de download no frontend ou usar uma URL pública configurável para a API.

## Rastreabilidade

- **Revalidação:** permanece em `release/0.1.0` @ `7a5e70f4809dd4bae29cfb772042d12784fc48b6`, verificado em 2026-09-06.

- **Origem rastreada:** A geração atual de URLs relativas foi introduzida em `38525d8` (2026-09-01). A arquitetura com servidores separados vem de `a728607` (2026-07-31). A revisão atual preserva os dois comportamentos.
- **Auditoria anterior:** `AUD-08`; restaurado com o ID `BUG-0013` na sequência dos registros atuais.

## Evidências

- Página web acessada por ASGI com metadados de token simulados; o link relativo retorna 404 na própria aplicação web.
- Verificação executada em 2026-09-06 sobre o commit da release indicado em Ambiente, com assertions dos resultados.
- Dados desta execução registrados no bloco JSON acima.
