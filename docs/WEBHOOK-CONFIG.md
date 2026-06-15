# Configuração de Webhooks - Melhoria 4

## Visão Geral

Webhooks são notificações automáticas enviadas para aplicações consumidoras quando dados FIPE estão prontos após o pipeline mensal.

## Armazenamento: Parameter Store

As configurações de webhooks são armazenadas em **AWS Systems Manager Parameter Store** para permitir atualizações sem redeploy.

### Chaves (Parâmetros)

- **sa-east-1 (Multi-Region):** `/fipe/webhooks/sa-east-1`
- **STG (us-east-2):** `/fipe/webhooks/stg`
- **PRD (us-east-1):** `/fipe/webhooks/prd`

## Formato de Configuração

```json
{
  "webhooks": [
    {
      "name": "app-consumidora-1",
      "url": "https://app1.example.com/webhooks/fipe",
      "api_key": "sk_live_abc123"
    },
    {
      "name": "app-consumidora-2",
      "url": "https://app2.example.com/api/fipe-notification",
      "api_key": "sk_live_xyz789"
    }
  ]
}
```

### Campos

| Campo | Tipo | Obrigatório | Descrição |
|-------|------|-------------|-----------|
| `name` | String | Sim | Identificador único do webhook (usado em logs e métricas) |
| `url` | String | Sim | URL endpoint que receberá o POST |
| `api_key` | String | Não | Chave de API enviada no header `X-API-Key` |

## Criar Webhook Inicial

### Via AWS CLI

```bash
# STG
aws ssm put-parameter \
  --name /fipe/webhooks/stg \
  --value '{
    "webhooks": [
      {
        "name": "test-app",
        "url": "https://webhook.site/seu-id-unico",
        "api_key": "test-key-123"
      }
    ]
  }' \
  --type String \
  --region us-east-2

# PRD
aws ssm put-parameter \
  --name /fipe/webhooks/prd \
  --value '{
    "webhooks": [
      {
        "name": "prod-app",
        "url": "https://api.production.com/webhooks/fipe",
        "api_key": "sk_live_production_key"
      }
    ]
  }' \
  --type String \
  --region us-east-1

# SA-EAST-1
aws ssm put-parameter \
  --name /fipe/webhooks/sa-east-1 \
  --value '{
    "webhooks": [
      {
        "name": "test-webhook",
        "url": "https://webhook.site/seu-id-unico",
        "api_key": "test-key"
      }
    ]
  }' \
  --type String \
  --region sa-east-1
```

## Adicionar Novo Webhook (Sem Redeploy)

### Passo 1: Buscar configuração atual

```bash
aws ssm get-parameter \
  --name /fipe/webhooks/stg \
  --query 'Parameter.Value' \
  --output text > webhooks.json \
  --region us-east-2
```

### Passo 2: Editar arquivo

Adicionar novo webhook ao array:

```json
{
  "webhooks": [
    {
      "name": "existing-app",
      "url": "https://existing.com/webhook",
      "api_key": "existing-key"
    },
    {
      "name": "nova-app",
      "url": "https://nova.com/webhooks/fipe",
      "api_key": "sk_live_nova_key"
    }
  ]
}
```

### Passo 3: Salvar atualizado

```bash
aws ssm put-parameter \
  --name /fipe/webhooks/stg \
  --value file://webhooks.json \
  --overwrite \
  --type String \
  --region us-east-2
```

### Passo 4: Validar

```bash
aws ssm get-parameter \
  --name /fipe/webhooks/stg \
  --query 'Parameter.Value' \
  --output text \
  --region us-east-2 | jq .
```

## Testar Webhook

### Usando webhook.site (para testes)

1. Acesse https://webhook.site
2. Copie a URL única gerada
3. Configure um webhook de teste com essa URL
4. Invoque Lambda manualmente

```bash
aws lambda invoke \
  --function-name FipeSomaNotifier \
  --payload '{"reference_month": "2026-05", "records_total": 45230}' \
  --region sa-east-1 \
  response.json
```

5. Verifique webhook.site - deve ver o POST recebido

## Payload Enviado

Quando webhook é disparado, recebe POST com corpo:

```json
{
  "type": "WEBHOOK_NOTIFY",
  "pipeline": "fipe_monthly_load",
  "reference_month": "2026-05",
  "records_total": 45230,
  "timestamp": "2026-05-15T14:30:00Z",
  "stage": "sa-east-1"
}
```

## Headers

| Header | Valor |
|--------|-------|
| `Content-Type` | `application/json` |
| `X-API-Key` | Valor de `api_key` da configuração |

## Comportamento de Retry

Se webhook falhar:

- **Tentativa 1:** Imediato
- **Tentativa 2:** Espera 5 segundos
- **Tentativa 3:** Espera 10 segundos
- **Tentativa 4:** Espera 20 segundos
- **Tentativa 5:** Espera 40 segundos
- **Tentativa 6:** Espera 80 segundos

**Total:** ~150 segundos (2.5 minutos) para 5 retries

Se falhar após 5 retries:
- Log de erro em CloudWatch Logs
- Métrica `webhook_failure_count` emitida
- **Sem fila de reprocessamento** (manual se necessário reinvocar Lambda)

## Monitoramento

### CloudWatch Metrics

Namespace: `FipeDataStack`

Métricas emitidas:
- `webhook_success_count` (Count)
- `webhook_failure_count` (Count)

Dimensões:
- `WebhookName`: Nome do webhook
- `Stage`: Estágio (sa-east-1, stg, prd)

### CloudWatch Logs

Lambda logs em:
- `/aws/lambda/FipeSomaNotifier`

Buscar por:
- `NOTIFIER - Webhook` para rastrear execuções
- `NOTIFIER - Erro` para falhas

## Remover Webhook

1. Buscar configuração atual
2. Remover webhook do array
3. Salvar atualizado

```bash
# Exemplo: remover "old-app"
aws ssm get-parameter \
  --name /fipe/webhooks/stg \
  --query 'Parameter.Value' \
  --output text > webhooks.json

# Editar: remover entrada de "old-app"

aws ssm put-parameter \
  --name /fipe/webhooks/stg \
  --value file://webhooks.json \
  --overwrite \
  --type String \
  --region us-east-2
```

## Troubleshooting

### Webhook não recebe notificação

1. Verificar logs da Lambda:
   ```bash
   aws logs tail /aws/lambda/FipeSomaNotifier --follow
   ```

2. Validar URL é acessível:
   ```bash
   curl -X POST https://seu-webhook.com/endpoint \
     -H "Content-Type: application/json" \
     -H "X-API-Key: sua-chave" \
     -d '{"test": true}'
   ```

3. Verificar Parameter Store tem configuração:
   ```bash
   aws ssm get-parameter --name /fipe/webhooks/stg
   ```

### Webhook falha com 401 (Unauthorized)

- Verificar `api_key` está correto no Parameter Store
- Verificar app consumidora valida header `X-API-Key`

### Webhook retorna erro 5xx

- Lambda retentará automaticamente com backoff
- Verifique logs da app consumidora
- Se persistir, webhook vai para métrica de failure

## Referências

- [Lambda FipeSomaNotifier](../code_lambdas/src/fipe_api/fipe_soma_notifier.py)
- [Melhoria 4 - Webhooks](../../memory/melhoria_4_webhooks.md)
