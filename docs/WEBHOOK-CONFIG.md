# Configuração de Webhooks - Melhoria 4

## Visão Geral

O FipeDataStack2 dispara webhooks automaticamente quando os dados mensais de preços FIPE são disponibilizados em STG e PRD. As aplicações consumidoras (como Odoo) podem se registrar para receber notificações.

### Arquitetura do Fluxo

```
FipeManufacturerLoader (sa-east-1)
    ↓
FipeModelLoader (sa-east-1)
    ↓
FipePriceLoader (sa-east-1)
    ↓
FipeSomaIngestor (sa-east-1)
    ├─ Insere dados em RDS sa-east-1
    ├─ Encaminha para RDS STG (us-east-2)
    ├─ Encaminha para RDS PRD (us-east-1)
    └─ Invoca FipeSomaNotifier-stg e FipeSomaNotifier-prd
         ↓
    FipeSomaNotifier-stg (us-east-2)
         ├─ Lê webhooks do Parameter Store: /fipe/webhooks/stg
         ├─ Envia POST para cada webhook registrado
         └─ Emite métricas CloudWatch: webhook_success_count, webhook_failure_count
         
    FipeSomaNotifier-prd (us-east-1)
         ├─ Lê webhooks do Parameter Store: /fipe/webhooks/prd
         ├─ Envia POST para cada webhook registrado
         └─ Emite métricas CloudWatch: webhook_success_count, webhook_failure_count
```

## Configuração Inicial

### 1. Deploy CDK (Já Incluído)

As Lambdas FipeSomaNotifier são criadas automaticamente pelo deploy CDK:

```bash
make deploy-stg AWS_PROFILE=mutualizo VPC_ID=vpc-xxxxx ALLOWED_IP=1.2.3.4
make deploy-prd AWS_PROFILE=mutualizo VPC_ID=vpc-xxxxx ALLOWED_IP=1.2.3.4
```

### 2. Configurar Webhooks no Parameter Store

Use o script fornecido para criar a configuração inicial:

```bash
./setup_webhooks.sh stg
./setup_webhooks.sh prd
```

Ou configure manualmente:

```bash
# Para STG (us-east-2)
aws ssm put-parameter \
  --name /fipe/webhooks/stg \
  --value '{
    "webhooks": [
      {
        "name": "odoo-webhook",
        "url": "https://odoo-stg.example.com/api/fipe/webhook",
        "api_key": "token-secreto-stg"
      }
    ]
  }' \
  --type String \
  --region us-east-2

# Para PRD (us-east-1)
aws ssm put-parameter \
  --name /fipe/webhooks/prd \
  --value '{
    "webhooks": [
      {
        "name": "odoo-webhook",
        "url": "https://odoo-prd.example.com/api/fipe/webhook",
        "api_key": "token-secreto-prd"
      }
    ]
  }' \
  --type String \
  --region us-east-1
```

## Estrutura de Configuração

Cada Parameter Store (`/fipe/webhooks/{stage}`) contém um JSON com a seguinte estrutura:

```json
{
  "webhooks": [
    {
      "name": "identificador-unico",
      "url": "https://example.com/webhook/endpoint",
      "api_key": "token-de-autenticacao"
    },
    {
      "name": "segunda-app",
      "url": "https://app2.example.com/api/fipe",
      "api_key": "outro-token"
    }
  ]
}
```

### Campos Obrigatórios

- **name**: Identificador único do webhook (usado em logs e métricas)
- **url**: URL completa do endpoint que receberá o POST
- **api_key**: Token de autenticação (enviado no header `X-Webhook-Token`)

## Adicionar/Remover Webhooks (Sem Redeploy)

### Adicionar um Novo Webhook

```bash
# 1. Buscar configuração atual
aws ssm get-parameter \
  --name /fipe/webhooks/stg \
  --query 'Parameter.Value' \
  --output text \
  --region us-east-2 > webhooks.json

# 2. Editar webhooks.json e adicionar novo webhook
cat webhooks.json
# {
#   "webhooks": [
#     { "name": "...", "url": "...", "api_key": "..." },
#     { "name": "nova-app", "url": "https://...", "api_key": "..." }  ← Adicione aqui
#   ]
# }

# 3. Salvar configuração atualizada
aws ssm put-parameter \
  --name /fipe/webhooks/stg \
  --value file://webhooks.json \
  --overwrite \
  --type String \
  --region us-east-2

# Próxima notificação usará o novo webhook
```

### Remover um Webhook

```bash
# Seguir passos 1-3 acima, mas remover o webhook do JSON
```

## Payload do Webhook

Quando o FipeSomaNotifier dispara um webhook, envia um POST com o seguinte JSON:

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

### Campos do Payload

- **type**: Sempre `"WEBHOOK_NOTIFY"` - permite filtrar por tipo em aplicações consumidoras
- **pipeline**: Sempre `"fipe_monthly_load"` - identifica qual pipeline enviou
- **reference_month**: Mês de referência FIPE no formato `YYYY-MM`
- **records_total**: Número de registros processados neste mês
- **timestamp**: Timestamp ISO 8601 UTC quando o webhook foi disparado
- **stage**: `"stg"` ou `"prd"` - identifica qual ambiente

### Headers Enviados

```
Content-Type: application/json
X-Webhook-Token: <api_key_configurada>
```

## Requisitos para o Endpoint Webhook

### 1. Responder com Status 200

```python
# Exemplo em Flask
@app.route('/api/fipe/webhook', methods=['POST'])
def fipe_webhook():
    token = request.headers.get('X-Webhook-Token')
    
    # Validar token
    if token != os.environ['FIPE_WEBHOOK_TOKEN']:
        return jsonify({"error": "Unauthorized"}), 401
    
    # Procesar payload
    data = request.json
    reference_month = data.get('reference_month')
    records_total = data.get('records_total')
    
    # ... processar dados ...
    
    return jsonify({"status": "received"}), 200
```

### 2. Ser Idempotente

Como o webhook pode ser chamado múltiplas vezes em caso de retries, o endpoint deve ser idempotente:

```python
# ❌ ERRADO: Pode duplicar registros
def fipe_webhook():
    create_new_record(data)  # Será chamado 5x em caso de retries
    
# ✅ CORRETO: Verifica se já foi processado
def fipe_webhook():
    key = f"{data['reference_month']}-{data['stage']}"
    if WebhookLog.exists(key):
        return {"status": "already_processed"}, 200
    create_new_record(data)
    WebhookLog.create(key)
    return {"status": "received"}, 200
```

### 3. Responder Rapidamente

O timeout para webhooks é **10 segundos**. Processe dados de forma assíncrona:

```python
# ❌ ERRADO: Processamento síncrono pode timeout
def fipe_webhook():
    sync_large_dataset(data)  # Pode demorar minutos
    return 200

# ✅ CORRETO: Enfileirar para processamento assíncrono
def fipe_webhook():
    queue.enqueue(sync_large_dataset, data)  # Retorna imediatamente
    return {"status": "queued"}, 200
```

## Comportamento de Retry

O FipeSomaNotifier implementa retry automático com backoff exponencial:

1. **Tentativa 1**: Falha → espera 5 segundos
2. **Tentativa 2**: Falha → espera 10 segundos
3. **Tentativa 3**: Falha → espera 20 segundos
4. **Tentativa 4**: Falha → espera 40 segundos
5. **Tentativa 5**: Falha → registra como falha permanente

**Total de tempo para 5 tentativas:** ~150 segundos (2.5 minutos)

Casos que acionam retry:
- Timeout (10 segundos)
- Conexão recusada
- Erro 5xx do servidor
- Qualquer exceção de rede

Casos que **não** acionam retry:
- Status 200 OK
- Status 4xx (cliente) - indicam erro configuração

## Monitoramento

### CloudWatch Logs

Verificar logs da Lambda FipeSomaNotifier:

```bash
# STG
aws logs tail /aws/lambda/FipeSomaNotifier-stg --follow --region us-east-2

# PRD
aws logs tail /aws/lambda/FipeSomaNotifier-prd --follow --region us-east-1
```

Exemplos de logs:
```
NOTIFIER - Config carregada de /fipe/webhooks/stg: 2 webhook(s)
NOTIFIER - Tentativa 1/5 para odoo-webhook em stg
NOTIFIER - Webhook odoo-webhook chamado com sucesso (status=200)
NOTIFIER - Métrica webhook_success_count emitida para odoo-webhook
```

### CloudWatch Metrics

Verificar métricas de sucesso/falha:

```bash
# Listar métricas
aws cloudwatch list-metrics \
  --namespace "FipeWebhooks" \
  --region us-east-2

# Consultar específica
aws cloudwatch get-metric-statistics \
  --namespace "FipeWebhooks" \
  --metric-name "webhook_success_count" \
  --dimensions Name=WebhookName,Value=odoo-webhook Name=Stage,Value=stg \
  --start-time 2026-06-01T00:00:00Z \
  --end-time 2026-07-01T00:00:00Z \
  --period 3600 \
  --statistics Sum \
  --region us-east-2
```

### Dashboard CloudWatch

Criar dashboard com métricas:

```bash
aws cloudwatch put-dashboard \
  --dashboard-name "FIPE-Webhooks" \
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
          "title": "Webhook Success/Failure"
        }
      }
    ]
  }' \
  --region us-east-2
```

## Troubleshooting

### Webhook nunca é disparado

**Verificar:**
1. FipeSomaIngestor processou com sucesso? Ver logs:
   ```bash
   aws logs tail /aws/lambda/FipeSomaIngestor-sa-east-1 --follow --region sa-east-1
   ```
2. Parameter Store existe?
   ```bash
   aws ssm get-parameter --name /fipe/webhooks/stg --region us-east-2
   ```
3. Há webhooks configurados?
   ```bash
   aws ssm get-parameter --name /fipe/webhooks/stg --query 'Parameter.Value' --output text --region us-east-2 | jq '.webhooks'
   ```

### Webhook falha constantemente

**Verificar:**
1. URL está correta?
2. Endpoint responde com status 200?
3. Token (X-Webhook-Token) está correto?
4. Endpoint processa em menos de 10 segundos?

**Testar manualmente:**
```bash
curl -X POST https://seu-endpoint.com/api/fipe/webhook \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Token: seu-token" \
  -d '{
    "type": "WEBHOOK_NOTIFY",
    "pipeline": "fipe_monthly_load",
    "reference_month": "2026-06",
    "records_total": 45230,
    "timestamp": "2026-06-04T01:15:30Z",
    "stage": "stg"
  }'
```

### Webhook foi disparado múltiplas vezes

Isso é normal em caso de retries. Certifique-se de que seu endpoint é **idempotente** (ver seção acima).

## Exemplos de Integração

### Odoo v19

Ver documento: [EXEMPLO-ODOO-WEBHOOK.md](./EXEMPLO-ODOO-WEBHOOK.md)

### FastAPI

```python
from fastapi import FastAPI, HTTPException, Header
import os

app = FastAPI()

@app.post("/api/fipe/webhook")
async def fipe_webhook(
    payload: dict,
    x_webhook_token: str = Header(None)
):
    # Validar token
    if x_webhook_token != os.getenv("FIPE_WEBHOOK_TOKEN"):
        raise HTTPException(status_code=401, detail="Invalid token")
    
    # Processar
    reference_month = payload.get("reference_month")
    records_total = payload.get("records_total")
    stage = payload.get("stage")
    
    # Enfileirar processamento assíncrono
    background_tasks.add_task(process_fipe_data, reference_month, records_total)
    
    return {"status": "queued"}
```

### Django

```python
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
import os

@csrf_exempt
@require_http_methods(["POST"])
def fipe_webhook(request):
    # Validar token
    token = request.META.get("HTTP_X_WEBHOOK_TOKEN")
    if token != os.getenv("FIPE_WEBHOOK_TOKEN"):
        return JsonResponse({"error": "Unauthorized"}, status=401)
    
    # Processar
    data = json.loads(request.body)
    celery_app.send_task("tasks.process_fipe_data", args=[data])
    
    return JsonResponse({"status": "queued"})
```

## FAQ

**P: Posso ter múltiplos webhooks?**
R: Sim! Adicione quantos precisar no Parameter Store. Cada um será disparado independentemente.

**P: O webhook pode ser chamado mais de uma vez?**
R: Sim. Em caso de falhas, há retries. Implemente idempotência no seu endpoint.

**P: Quanto tempo leva para disparar?**
R: Imediatamente após FipeSomaIngestor terminar (< 1 segundo), ou até 150 segundos se houver retries.

**P: Preciso fazer redeploy para adicionar webhook?**
R: Não. Atualize o Parameter Store e a próxima notificação já usará o novo webhook.

**P: Qual timezone é usado no timestamp?**
R: UTC (Coordinated Universal Time). Ajuste seu timezone localmente se necessário.
