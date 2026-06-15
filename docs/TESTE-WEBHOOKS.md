# Guia de Teste - Webhooks (Melhoria 4)

## Pré-requisitos

- AWS CLI configurado com profile `mutualizo`
- Região: `sa-east-1`
- Lambda FipeSomaNotifier deployada
- Acesso a https://webhook.site

## Teste 1: Webhook Sucesso ✅

### Objetivo
Validar que webhook é disparado com sucesso e dados chegam no endpoint.

### Passo a Passo

```bash
# 1. Executar script de teste
./test_webhook_manual.sh

# 2. Quando solicitado, colar URL do webhook.site
#    (Abra https://webhook.site em outro navegador)

# 3. Aguardar Lambda ser invocada (~5 segundos)

# 4. Voltar para webhook.site e validar POST recebido
```

### Validações Esperadas

**Em webhook.site:**
- ✓ POST recebido
- ✓ Header `X-API-Key` presente
- ✓ Body JSON com:
  ```json
  {
    "type": "WEBHOOK_NOTIFY",
    "pipeline": "fipe_monthly_load",
    "reference_month": "2026-06",
    "records_total": 45230,
    "timestamp": "2026-06-15T14:30:00Z",
    "stage": "sa-east-1"
  }
  ```

**Em CloudWatch Logs:**
```
NOTIFIER - Webhook 'test-webhook' disparado com sucesso (status 200)
NOTIFIER - Métrica 'webhook_success_count' emitida para CloudWatch
```

**Em CloudWatch Metrics:**
- Métrica `webhook_success_count` = 1
- Dimensões: `WebhookName=test-webhook`, `Stage=sa-east-1`

## Teste 2: Webhook Falha com Retry ⚠️

### Objetivo
Validar que webhook falha, retenta com backoff, e métrica de falha é emitida.

### Passo a Passo

```bash
# 1. Executar script de teste de falha
./test_webhook_failure.sh

# 2. Aguardar ~150 segundos para retries completarem
#    (Script mostra progresso)

# 3. Validar logs e métricas
```

### Validações Esperadas

**Cronograma de tentativas:**
- Tentativa 1: Imediato
- Tentativa 2: +5 segundos
- Tentativa 3: +10 segundos  
- Tentativa 4: +20 segundos
- Tentativa 5: +40 segundos
- Tentativa 6: +80 segundos

**Em CloudWatch Logs:**
```
NOTIFIER - Tentativa 1/5 para webhook 'failing-webhook'
NOTIFIER - Erro ao chamar webhook 'failing-webhook': ...
NOTIFIER - Aguardando 5s antes de retentar...
NOTIFIER - Tentativa 2/5 para webhook 'failing-webhook'
...
NOTIFIER - Webhook 'failing-webhook' falhou após 5 tentativas
NOTIFIER - Métrica 'webhook_failure_count' emitida para CloudWatch
```

**Em CloudWatch Metrics:**
- Métrica `webhook_failure_count` = 1
- Dimensões: `WebhookName=failing-webhook`, `Stage=sa-east-1`

## Teste 3: Múltiplos Webhooks (Opcional)

### Objetivo
Validar que Lambda dispara múltiplos webhooks em sequência.

### Passo a Passo

```bash
# 1. Criar 2 webhooks em webhook.site
#    URL1: https://webhook.site/abc123
#    URL2: https://webhook.site/def456

# 2. Configurar Parameter Store manualmente
aws ssm put-parameter \
  --name /fipe/webhooks/sa-east-1 \
  --value '{
    "webhooks": [
      {
        "name": "webhook-1",
        "url": "https://webhook.site/abc123",
        "api_key": "key1"
      },
      {
        "name": "webhook-2",
        "url": "https://webhook.site/def456",
        "api_key": "key2"
      }
    ]
  }' \
  --overwrite \
  --type String \
  --region sa-east-1 \
  --profile mutualizo

# 3. Invocar Lambda manualmente
aws lambda invoke \
  --function-name FipeSomaNotifier \
  --payload '{"reference_month": "2026-06", "records_total": 45230}' \
  --region sa-east-1 \
  --profile mutualizo \
  response.json

# 4. Validar em ambos webhooks.site que POSTs chegaram
```

### Validações Esperadas

**Em CloudWatch Logs:**
```
NOTIFIER - 2/2 webhooks disparados com sucesso
```

**Em CloudWatch Metrics:**
- `webhook_success_count` = 2 (1 por webhook)
- Dimensões diferentes por webhook

## Teste 4: Métricas CloudWatch

### Consultar métricas

```bash
# Sucesso
aws cloudwatch get-metric-statistics \
  --namespace FipeDataStack \
  --metric-name webhook_success_count \
  --dimensions Name=WebhookName,Value=test-webhook Name=Stage,Value=sa-east-1 \
  --statistics Sum \
  --start-time 2026-06-15T00:00:00Z \
  --end-time 2026-06-16T00:00:00Z \
  --period 3600 \
  --region sa-east-1 \
  --profile mutualizo

# Falha
aws cloudwatch get-metric-statistics \
  --namespace FipeDataStack \
  --metric-name webhook_failure_count \
  --dimensions Name=WebhookName,Value=failing-webhook Name=Stage,Value=sa-east-1 \
  --statistics Sum \
  --start-time 2026-06-15T00:00:00Z \
  --end-time 2026-06-16T00:00:00Z \
  --period 3600 \
  --region sa-east-1 \
  --profile mutualizo
```

## Teste 5: Logs CloudWatch

### Ver logs em tempo real

```bash
aws logs tail /aws/lambda/FipeSomaNotifier \
  --follow \
  --since 10m \
  --region sa-east-1 \
  --profile mutualizo
```

### Filtrar por eventos específicos

```bash
# Webhooks disparados com sucesso
aws logs filter-log-events \
  --log-group-name /aws/lambda/FipeSomaNotifier \
  --filter-pattern "webhook_success_count" \
  --region sa-east-1 \
  --profile mutualizo

# Webhooks que falharam
aws logs filter-log-events \
  --log-group-name /aws/lambda/FipeSomaNotifier \
  --filter-pattern "webhook_failure_count" \
  --region sa-east-1 \
  --profile mutualizo

# Erros gerais
aws logs filter-log-events \
  --log-group-name /aws/lambda/FipeSomaNotifier \
  --filter-pattern "ERROR\|Erro\|Error" \
  --region sa-east-1 \
  --profile mutualizo
```

## Checklist de Validação

### Teste 1: Sucesso
- [ ] POST recebido em webhook.site
- [ ] Headers corretos (X-API-Key, Content-Type)
- [ ] Body JSON válido
- [ ] Log: "webhook disparado com sucesso (status 200)"
- [ ] Métrica `webhook_success_count` = 1

### Teste 2: Falha com Retry
- [ ] Tentativas 1-6 aparecem nos logs
- [ ] Backoff correto (5s, 10s, 20s, 40s, 80s)
- [ ] Total de ~150 segundos
- [ ] Log final: "falhou após 5 tentativas"
- [ ] Métrica `webhook_failure_count` = 1

### Teste 3: Múltiplos Webhooks
- [ ] Ambos webhooks recebem POST
- [ ] Ordem: webhook 1 → webhook 2
- [ ] 2/2 disparados com sucesso
- [ ] 2 métricas de sucesso registradas

### Teste 4: Métricas
- [ ] Métricas em CloudWatch com valores corretos
- [ ] Dimensões corretas (WebhookName, Stage)
- [ ] Namespace: FipeDataStack

### Teste 5: Logs
- [ ] Logs fluem em tempo real
- [ ] Filtros funcionam
- [ ] Timestamps corretos

## Troubleshooting

### Lambda não encontra Parameter Store

```bash
# Verificar se Parameter Store existe
aws ssm get-parameter \
  --name /fipe/webhooks/sa-east-1 \
  --region sa-east-1 \
  --profile mutualizo

# Se não existir, criar:
./setup_webhooks.sh sa-east-1
```

### Webhook não recebe POST

1. Verificar URL em webhook.site está acessível
2. Verificar logs da Lambda em CloudWatch
3. Verificar IAM permissions da Lambda para SSM e CloudWatch
4. Validar JSON em Parameter Store com `jq`

### Métricas não aparecem

- Aguardar ~1-2 minutos após Lambda ser invocada
- Validar dimensões estão corretas
- Consultar período de tempo correto

### Lambda timeout

- Aumentar timeout se webhooks são lentos
- Atual: 5 minutos
- Com retries: até ~3 minutos (150s retries + chamadas)

## Próximas Etapas

1. Deploy em STG (us-east-2)
2. Deploy em PRD (us-east-1)
3. Integração com apps consumidoras
4. Monitoramento em produção

## Referências

- [Código Lambda](../code_lambdas/src/fipe_api/fipe_soma_notifier.py)
- [Configuração Webhooks](./WEBHOOK-CONFIG.md)
- [Melhoria 4](../memory/melhoria_4_webhooks.md)
