# Testes Manuais - Webhooks (Melhoria 4)

## Pré-requisitos

- AWS CLI configurado com profile `mutualizo`
- Python 3.12+
- `jq` para processar JSON
- Acesso a webhook.site para testes (ou outro serviço de webhook)

## Teste 1: Verificar Webhooks Configurados

### Objetivo
Validar que os webhooks estão corretamente configurados no Parameter Store.

### Passos

1. **Verificar STG:**
```bash
aws ssm get-parameter \
  --name /fipe/webhooks/stg \
  --query 'Parameter.Value' \
  --output text \
  --region us-east-2 | jq '.'
```

2. **Verificar PRD:**
```bash
aws ssm get-parameter \
  --name /fipe/webhooks/prd \
  --query 'Parameter.Value' \
  --output text \
  --region us-east-1 | jq '.'
```

### Resultado Esperado

```json
{
  "webhooks": [
    {
      "name": "odoo-webhook",
      "url": "https://webhook.site/...",
      "api_key": "seu-token"
    }
  ]
}
```

---

## Teste 2: Testar Webhook com webhook.site

### Objetivo
Validar que a Lambda FipeSomaNotifier consegue chamar um webhook externo.

### Passos

1. **Criar URL de teste em webhook.site:**
   - Acesse https://webhook.site
   - Clique em "New" ou use uma URL existente
   - Copie a URL (ex: `https://webhook.site/12345678-abcd-efgh-ijkl-mnopqrstuvwx`)

2. **Adicionar URL ao Parameter Store (STG):**
```bash
aws ssm get-parameter \
  --name /fipe/webhooks/stg \
  --query 'Parameter.Value' \
  --output text \
  --region us-east-2 > /tmp/webhooks.json

# Editar arquivo e adicionar/atualizar webhook com URL do webhook.site
cat /tmp/webhooks.json | jq '.webhooks[0].url = "https://webhook.site/seu-uuid-aqui"' > /tmp/webhooks_updated.json

aws ssm put-parameter \
  --name /fipe/webhooks/stg \
  --value file:///tmp/webhooks_updated.json \
  --overwrite \
  --type String \
  --region us-east-2
```

3. **Invocar Lambda FipeSomaNotifier manualmente:**
```bash
aws lambda invoke \
  --function-name FipeSomaNotifier-stg \
  --payload '{"reference_month": "2026-06", "records_total": 45230, "stage": "stg"}' \
  --region us-east-2 \
  /tmp/response.json

cat /tmp/response.json
```

4. **Verificar webhook.site:**
   - Acesse a URL do webhook.site novamente
   - Deve haver 1 POST recebido com:
     - Headers incluindo `Content-Type: application/json` e `X-Webhook-Token`
     - Body com o JSON do webhook

### Resultado Esperado no webhook.site

**Headers:**
```
Content-Type: application/json
X-Webhook-Token: seu-token
```

**Body:**
```json
{
  "type": "WEBHOOK_NOTIFY",
  "pipeline": "fipe_monthly_load",
  "reference_month": "2026-06",
  "records_total": 45230,
  "timestamp": "2026-06-04T01:15:30.123456",
  "stage": "stg"
}
```

### Logs da Lambda

```bash
aws logs tail /aws/lambda/FipeSomaNotifier-stg --follow --region us-east-2
```

Deve mostrar:
```
NOTIFIER - Handler iniciado com evento: ...
NOTIFIER - Config carregada de /fipe/webhooks/stg: 1 webhook(s)
NOTIFIER - Disparando webhooks para stage=stg, reference_month=2026-06, records=45230
NOTIFIER - Tentativa 1/5 para odoo-webhook em stg
NOTIFIER - Webhook odoo-webhook chamado com sucesso (status=200)
NOTIFIER - Métrica webhook_success_count emitida para odoo-webhook
NOTIFIER - Processamento concluído: 1/1 webhooks bem-sucedidos
```

---

## Teste 3: Testar Retry em Caso de Falha

### Objetivo
Validar que o webhook tenta novamente com backoff exponencial em caso de falha.

### Passos

1. **Usar URL inválida no Parameter Store:**
```bash
aws ssm get-parameter \
  --name /fipe/webhooks/stg \
  --query 'Parameter.Value' \
  --output text \
  --region us-east-2 > /tmp/webhooks.json

# Alterar URL para algo inválido
cat /tmp/webhooks.json | jq '.webhooks[0].url = "https://invalid-url-that-does-not-exist.example.com/webhook"' > /tmp/webhooks_updated.json

aws ssm put-parameter \
  --name /fipe/webhooks/stg \
  --value file:///tmp/webhooks_updated.json \
  --overwrite \
  --type String \
  --region us-east-2
```

2. **Invocar Lambda:**
```bash
aws lambda invoke \
  --function-name FipeSomaNotifier-stg \
  --payload '{"reference_month": "2026-06", "records_total": 45230, "stage": "stg"}' \
  --region us-east-2 \
  /tmp/response.json

cat /tmp/response.json
```

3. **Monitorar logs por ~3 minutos:**
```bash
aws logs tail /aws/lambda/FipeSomaNotifier-stg --follow --region us-east-2
```

### Resultado Esperado

Logs devem mostrar retries com delays exponenciais:
```
NOTIFIER - Tentativa 1/5 para odoo-webhook em stg
NOTIFIER - Erro ao chamar webhook odoo-webhook: ...
NOTIFIER - Aguardando 5s antes de retry...
NOTIFIER - Tentativa 2/5 para odoo-webhook em stg
NOTIFIER - Erro ao chamar webhook odoo-webhook: ...
NOTIFIER - Aguardando 10s antes de retry...
NOTIFIER - Tentativa 3/5 para odoo-webhook em stg
...
NOTIFIER - Webhook odoo-webhook falhou após 5 tentativas
NOTIFIER - Métrica webhook_failure_count emitida para odoo-webhook
```

**Timing esperado:**
- Tentativa 1: ~0s
- Tentativa 2: ~5s
- Tentativa 3: ~15s
- Tentativa 4: ~35s
- Tentativa 5: ~75s
- **Total: ~150 segundos**

### CloudWatch Metrics

Verificar que a métrica de falha foi registrada:

```bash
aws cloudwatch get-metric-statistics \
  --namespace "FipeWebhooks" \
  --metric-name "webhook_failure_count" \
  --dimensions Name=WebhookName,Value=odoo-webhook Name=Stage,Value=stg \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S)Z \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S)Z \
  --period 300 \
  --statistics Sum \
  --region us-east-2
```

Resultado esperado: `Sum: 1.0`

---

## Teste 4: Testar Múltiplos Webhooks

### Objetivo
Validar que a Lambda dispara para múltiplos webhooks configurados.

### Passos

1. **Criar dois webhooks diferentes em webhook.site:**
   - URL 1: `https://webhook.site/webhook-1-uuid`
   - URL 2: `https://webhook.site/webhook-2-uuid`

2. **Configurar ambos no Parameter Store:**
```bash
aws ssm put-parameter \
  --name /fipe/webhooks/stg \
  --value '{
    "webhooks": [
      {
        "name": "webhook-1",
        "url": "https://webhook.site/webhook-1-uuid",
        "api_key": "token-1"
      },
      {
        "name": "webhook-2",
        "url": "https://webhook.site/webhook-2-uuid",
        "api_key": "token-2"
      }
    ]
  }' \
  --overwrite \
  --type String \
  --region us-east-2
```

3. **Invocar Lambda:**
```bash
aws lambda invoke \
  --function-name FipeSomaNotifier-stg \
  --payload '{"reference_month": "2026-06", "records_total": 45230, "stage": "stg"}' \
  --region us-east-2 \
  /tmp/response.json

cat /tmp/response.json | jq '.'
```

### Resultado Esperado

**Response:**
```json
{
  "statusCode": 200,
  "body": "{\"successful_webhooks\": 2, \"total_webhooks\": 2, \"reference_month\": \"2026-06\"}"
}
```

**Logs:**
```
NOTIFIER - Config carregada de /fipe/webhooks/stg: 2 webhook(s)
NOTIFIER - Tentativa 1/5 para webhook-1 em stg
NOTIFIER - Webhook webhook-1 chamado com sucesso (status=200)
NOTIFIER - Tentativa 1/5 para webhook-2 em stg
NOTIFIER - Webhook webhook-2 chamado com sucesso (status=200)
NOTIFIER - Processamento concluído: 2/2 webhooks bem-sucedidos
```

**webhook.site:**
- Ambas URLs devem ter recebido 1 POST cada

---

## Teste 5: Testar Integração com FipeSomaIngestor

### Objetivo
Validar que o FipeSomaIngestor dispara automaticamente FipeSomaNotifier após processar dados.

### Pré-requisitos

- Ter dados na fila `fipe-price-queue-sa-east-1` (ou enviar manualmente)
- Ter webhook configurado em `/fipe/webhooks/stg`

### Passos

1. **Confirmar que `fipe-price-queue-sa-east-1` tem mensagens:**
```bash
aws sqs get-queue-attributes \
  --queue-url https://sqs.sa-east-1.amazonaws.com/YOUR_ACCOUNT_ID/fipe-price-queue-sa-east-1 \
  --attribute-names ApproximateNumberOfMessages \
  --region sa-east-1
```

2. **Monitorar logs do FipeSomaIngestor:**
```bash
aws logs tail /aws/lambda/FipeSomaIngestor-sa-east-1 --follow --region sa-east-1
```

3. **Quando a Lambda terminar, verificar:**
   - Logs mostram invocação de FipeSomaNotifier:
     ```
     INGESTOR - Disparando webhooks para STG e PRD
     INGESTOR - Webhook notifier invocado para stage=stg
     INGESTOR - Webhook notifier invocado para stage=prd
     ```

4. **Verificar logs de FipeSomaNotifier:**
```bash
aws logs tail /aws/lambda/FipeSomaNotifier-stg --follow --region us-east-2
aws logs tail /aws/lambda/FipeSomaNotifier-prd --follow --region us-east-1
```

5. **Verificar webhook.site para POST recebido**

### Resultado Esperado

- FipeSomaIngestor processa mensagens e invoca FipeSomaNotifier
- FipeSomaNotifier-stg dispara webhooks em us-east-2
- FipeSomaNotifier-prd dispara webhooks em us-east-1
- webhook.site recebe POST em ambas URLs (ou apenas uma, se configurada para um ambiente)

---

## Teste 6: Verificar Métricas CloudWatch

### Objetivo
Validar que as métricas são emitidas corretamente.

### Passos

1. **Listar métricas disponíveis:**
```bash
aws cloudwatch list-metrics \
  --namespace "FipeWebhooks" \
  --region us-east-2
```

2. **Consultar métrica de sucesso:**
```bash
aws cloudwatch get-metric-statistics \
  --namespace "FipeWebhooks" \
  --metric-name "webhook_success_count" \
  --dimensions Name=WebhookName,Value=odoo-webhook Name=Stage,Value=stg \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S)Z \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S)Z \
  --period 300 \
  --statistics Sum \
  --region us-east-2
```

3. **Criar dashboard CloudWatch:**
```bash
aws cloudwatch put-dashboard \
  --dashboard-name "FIPE-Webhooks-Test" \
  --dashboard-body '{
    "widgets": [
      {
        "type": "metric",
        "properties": {
          "metrics": [
            ["FipeWebhooks", "webhook_success_count", {"stat": "Sum"}],
            [".", "webhook_failure_count", {"stat": "Sum"}]
          ],
          "period": 300,
          "stat": "Sum",
          "region": "us-east-2",
          "title": "Webhook Calls - STG"
        }
      }
    ]
  }' \
  --region us-east-2
```

4. **Abrir dashboard no console AWS:**
   - https://console.aws.amazon.com/cloudwatch/home?region=us-east-2#dashboards:name=FIPE-Webhooks-Test

### Resultado Esperado

- Métrica `webhook_success_count` aumenta em 1 para cada webhook bem-sucedido
- Métrica `webhook_failure_count` aumenta em 1 para cada webhook que falhou após retries

---

## Teste 7: Simular Erro de Processamento (Sem Webhook)

### Objetivo
Validar que webhook NÃO é disparado se houver falhas no processamento.

### Passos

1. **Enviar mensagem inválida para `fipe-price-queue-sa-east-1`:**
```bash
aws sqs send-message \
  --queue-url https://sqs.sa-east-1.amazonaws.com/YOUR_ACCOUNT_ID/fipe-price-queue-sa-east-1 \
  --message-body '{"invalid": "message"}' \
  --region sa-east-1
```

2. **Monitorar logs do FipeSomaIngestor:**
```bash
aws logs tail /aws/lambda/FipeSomaIngestor-sa-east-1 --follow --region sa-east-1
```

3. **Verificar que webhook NÃO é disparado:**
   - Logs devem mostrar:
     ```
     INGESTOR - Mensagem ... marcada para reprocessamento
     INGESTOR - {total_failures} mensagens falharam
     ```
   - Mas NÃO deve mostrar:
     ```
     INGESTOR - Disparando webhooks para STG e PRD
     ```

### Resultado Esperado

- Webhook não é disparado quando há falhas no processamento
- Mensagem é enviada para DLQ (Dead Letter Queue)

---

## Troubleshooting

### "Parameter not found"

```
NOTIFIER - Parameter /fipe/webhooks/stg não encontrado no SSM
```

**Solução:**
```bash
./setup_webhooks.sh stg
```

### "Timeout connecting to webhook"

Logs mostram tentativas mas sempre falham:
```
NOTIFIER - Tentativa 1/5 para ... em stg
NOTIFIER - Erro ao chamar webhook: HTTPSConnectionPool(host='...') Read timed out
```

**Verificar:**
- URL está correta? (`https://` em vez de `http://`?)
- Endpoint consegue responder?
- Firewall bloqueia conexão?

### "Webhook nunca é disparado"

**Verificar checklist:**
1. ✅ Lambda FipeSomaIngestor terminou com sucesso?
   ```bash
   aws logs tail /aws/lambda/FipeSomaIngestor-sa-east-1 --follow
   ```
2. ✅ Webhooks estão configurados?
   ```bash
   aws ssm get-parameter --name /fipe/webhooks/stg --region us-east-2
   ```
3. ✅ Lambda FipeSomaNotifier foi invocada?
   ```bash
   aws logs tail /aws/lambda/FipeSomaNotifier-stg --follow
   ```
4. ✅ Há registros processados (records_total > 0)?

---

## Checklist de Testes (Para Validação Final)

- [ ] Teste 1: Webhooks configurados corretamente
- [ ] Teste 2: Webhook via webhook.site funciona
- [ ] Teste 3: Retry exponencial funciona
- [ ] Teste 4: Múltiplos webhooks funcionam
- [ ] Teste 5: Integração com FipeSomaIngestor funciona
- [ ] Teste 6: Métricas CloudWatch são emitidas
- [ ] Teste 7: Webhook não dispara em caso de erro

**Quando todos os testes passarem:**
- ✅ Melhoria 4 está pronta para produção
- ✅ Pronto para notificar aplicações consumidoras
