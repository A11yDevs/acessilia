# 🐛 Limite de upload aplicado somente depois de gravar no frontend

## Identificação

| Campo | Valor |
|---|---|
| **ID** | BUG-0016 |
| **Data** | 2026-09-06 |
| **Reportado por** | Wryel Teodoro |
| **Severidade** | 🟡 Média |
| **Status** | Aberto · reproduzido em ambiente isolado |

## Ambiente

| Item | Valor |
|---|---|
| SO | Linux |
| Python | 3.12.3 |
| Branch / commit | [release/0.1.0](https://github.com/A11yDevs/acessilia/tree/release/0.1.0) @ `7a5e70f4809dd4bae29cfb772042d12784fc48b6` |
| Motor (`PIPELINE_ENGINE`) | Não executado; upload gravado no frontend antes de enviar à API |
| Estruturador (`STRUCTURER`) | Não utilizado; a cópia do upload precede a extração |
| IA (`AI_CLIENT` + modelo) | Não utilizada; o consumo de disco ocorre antes do processamento |
| Interface | Painel web / upload |

## Resumo

O frontend grava o upload inteiro em disco antes de reenviá-lo à API, sem aplicar o limite de tamanho configurado nessa gravação.

## Entrada usada (qual arquivo/imagem)

- **Entrada:** Upload em memória de 1 MiB + 1 byte com limite reduzido para 1 MiB no objeto settings.
- **Observação:** reprodução isolada com dados sintéticos, sem acesso a dados de usuários ou serviços externos reais.

## Passos para reproduzir

1. Configurar `settings.max_file_size_mb=1` em ambiente de teste.
2. Fornecer um `UploadFile` com 1.048.577 bytes ao helper `_save_upload` do painel.
3. Verificar o tamanho do arquivo gravado antes de qualquer reenvio à API.

## Resultado esperado

Interromper a gravação ao ultrapassar o limite e remover o arquivo parcial.

## Resultado obtido

O frontend grava os 1.048.577 bytes, ultrapassando o limite de 1.048.576 bytes.

```json
{
  "id": "BUG-0016",
  "limit_bytes": 1048576,
  "saved_bytes": 1048577
}
```

## Causa raiz (se identificada)

[frontend/web/app.py](../../frontend/web/app.py), linhas 84–90, usa `shutil.copyfileobj` sem contador de bytes. `_submit_via_api` só chama a API depois dessa cópia. A validação posterior da API não evita o consumo anterior de disco no frontend; a prova não afirma bypass do limite da API.

## Correção sugerida (se houver)

Copiar em blocos com verificação do limite e limpar o parcial em caso de erro.

## Rastreabilidade

- **Revalidação:** permanece em `release/0.1.0` @ `7a5e70f4809dd4bae29cfb772042d12784fc48b6`, verificado em 2026-09-06.

- **Origem rastreada:** O helper de upload do frontend cliente da API foi introduzido em `a728607` (2026-07-31), incluindo a cópia sem contador de bytes.
- **Auditoria anterior:** `AUD-17`; restaurado com o ID `BUG-0016` na sequência dos registros atuais.

## Evidências

- Gravação real do upload web em diretório temporário; arquivo de 1 MiB + 1 byte salvo com limite configurado em 1 MiB.
- Verificação executada em 2026-09-06 sobre o commit da release indicado em Ambiente, com assertions dos resultados.
- Dados desta execução registrados no bloco JSON acima.
