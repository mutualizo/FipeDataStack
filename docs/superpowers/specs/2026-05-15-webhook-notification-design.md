# FipeSoma Webhooks: Notificação de Dados Disponíveis

**Data:** 2026-05-15  
**Autor:** Alexandre Defendi  
**Status:** Design Aprovado

---

## 1. Visão Geral

### Motivador
Atualmente, quando a pipeline FIPE completa e dados são inseridos no banco, aplicações consumidoras não têm forma de saber que novos dados estão disponíveis. Precisam fazer polling ou ser notificadas manualmente. Isso resulta em:
- Latência na atualização de dados nas aplicações
- Sem notificação automática de disponibilidade
- Aplicações precisam fazer polling (caro/ineficiente)

### Objetivo
Implementar um sistema de webhooks que notifica aplicações consumidoras **assim que** os dados FIPE são processados e disponibilizados no banco de dados. A notificação inclui metadata útil para logging e monitoramento.

### Escopo
- Lambda `FipeSomaNotifier` que dispara webhooks
- SQS FIFO para fila de webhooks + DLQ
- Parameter Store para armazenar URLs dos webhooks
- CloudWatch Metrics para monitoramento
- CloudWatch Alarms + SNS para alertas
- Retry inteligente com exponential backoff
- Autenticação via API Key
- Ambientes: **STG + PRD**

---

## 2. Arquitetura

### Fluxo Completo

```
Pipeline FIPE (Mensal)
    ├─ EventBridge cron → FipeManufacturerLoader
    ├─ Manufacturer → Model → Price (via SQS)
    └─ FipeSomaIngestor (insere no RDS)

FipeSomaIngestor (Última etapa)
    ├─ Processa mensagens de preços
    ├─ Ao receber END_OF_RECORDS:
    │  ├─ Conta registros processados
    │  ├─ Valida inserção no RDS (SELECT COUNT)
    │  ├─ Se validação OK: coloca em fipe-soma-webhook-queue-{stage}
    │  └─ Se falhar: apenas log (não notifica)
    
FipeSomaNotifier (Lambda separada)
    ├─ Event Source: fipe-soma-webhook-queue-{stage} (SQS FIFO)
    ├─ Para cada webhook registrado em Parameter Store:
    │  ├─ POST com payload + X-API-Key header
    │  ├─ Timeout: 10 segundos
    │  ├─ Retry: 5s, 10s, 20s, 40s, 80s (max 5 tentativas)
    │  ├─ Sucesso: emite métrica webhook_success_count
    │  └─ Falha: emite métrica webhook_failure_count
    │
    ├─ Falhas após retries: SQS move para DLQ
    └─ DLQ dispara Alarm → SNS (Email + Slack)

Aplicações Consumidoras
    ├─ Recebem POST com payload
    ├─ Validam X-API-Key
    └─ Fazem refresh de dados/cache FIPE
```

### Payload do Webhook

```json
{
  "type": "WEBHOOK_NOTIFY",
  "pipeline": "fipe_monthly_load",
  "reference_month": "2026-05",
  "records_total": 12500,
  "duration_minutes": 15,
  "timestamp": "2026-05-15T14:30:00Z",
  "stage": "stg"
}
```

---

## 3. Componentes Detalhados

### 3.1 Modificação: FipeSomaIngestor

**Lógica adicionada ao final do lambda_handler:**

```python
def lambda_handler(event, context):
    # ... lógica existente de ingestão ...
    
    records_processed = 0
    for record in event['Records']:
        body = json.loads(record['body'])
        
        # Se for END_OF_RECORDS, validar e notificar
        if body.get('type') == 'END_OF_RECORDS':
            reference_month = body.get('reference_month')
            
            # 1. Validar que dados foram inseridos no RDS
            try:
                record_count = validate_records_in_rds(conn, reference_month)
                logger.info(f"INGESTOR-WEBHOOK - Validação OK: {record_count} registros no RDS")
                
                # 2. Se validação passou, coloca na fila de webhooks
                webhook_message = {
                    "type": "WEBHOOK_NOTIFY",
                    "pipeline": "fipe_monthly_load",
                    "reference_month": reference_month,
                    "records_total": record_count,
                    "duration_minutes": calculate_duration(),
                    "timestamp": datetime.utcnow().isoformat(),
                    "stage": os.environ.get("STAGE")
                }
                
                sqs.send_message(
                    QueueUrl=os.environ['WEBHOOK_QUEUE_URL'],
                    MessageBody=json.dumps(webhook_message),
                    MessageGroupId=reference_month,  # FIFO: group by month
                    MessageDeduplicationId=f"{reference_month}-{datetime.utcnow().timestamp()}"
                )
                logger.info("INGESTOR-WEBHOOK - Mensagem enviada para fila de webhooks")
            except Exception as e:
                logger.error(f"INGESTOR-WEBHOOK - Erro ao validar/notificar: {str(e)}")
                # Não lança exception (não deve bloquear pipeline)
            
            continue
        
        # Ingestão normal de preços
        # ... (lógica existente) ...
        records_processed += 1
    
    return {"status": "success", "records_processed": records_processed}

def validate_records_in_rds(conn, reference_month):
    """Valida que registros foram inseridos no RDS"""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT COUNT(*) 
            FROM public.fipe_vehicle_price 
            WHERE reference_month = %s
        """, (reference_month,))
        count = cur.fetchone()[0]
        
        if count == 0:
            raise ValueError(f"Nenhum registro encontrado para {reference_month}")
        
        return count
```

**Environment Variables (adicionar):**
```
WEBHOOK_QUEUE_URL=https://sqs.{region}.amazonaws.com/{account}/fipe-soma-webhook-queue-{stage}.fifo
```

---

### 3.2 Nova Lambda: FipeSomaNotifier

**Configuração CDK:**

```python
webhook_notifier_lambda = lambda_.Function(
    self, f"FipeSomaNotifier-{stage}",
    function_name=f"FipeSomaNotifier-{stage}",
    runtime=lambda_.Runtime.PYTHON_3_12,
    code=lambda_.Code.from_asset("code_lambdas/src/fipe_api"),
    handler="fipe_soma_notifier.lambda_handler",
    timeout=Duration.minutes(5),
    memory_size=256,
    environment={
        "WEBHOOK_PARAMETER_PATH": f"/fipe/webhooks/{stage}",
        "WEBHOOK_TIMEOUT": "10",
        "STAGE": stage
    },
    role=lambda_role,  # Precisa de: SSM GetParameter + SQS receive/delete
    layers=[lambda_layer],
    description=f"Disparar webhooks após pipeline FIPE completa - {stage}"
)

# Event Source: SQS FIFO
webhook_notifier_lambda.add_event_source(
    lambda_event_sources.SqsEventSource(
        webhook_queue,
        batch_size=1,  # Process one message at a time (FIFO guarantee)
        max_batching_window=Duration.seconds(0)
    )
)
```

**Código da Lambda:**

```python
# code_lambdas/src/fipe_api/fipe_soma_notifier.py

import json
import os
import logging
import requests
import boto3
from datetime import datetime

ssm = boto3.client('ssm')
cloudwatch = boto3.client('cloudwatch')
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    """
    Dispara webhooks para aplicações após pipeline FIPE completa
    """
    stage = os.environ.get('STAGE', 'stg')
    parameter_path = os.environ['WEBHOOK_PARAMETER_PATH']
    timeout = int(os.environ.get('WEBHOOK_TIMEOUT', '10'))
    
    # 1. Parse webhook message
    message_body = json.loads(event['Records'][0]['body'])
    reference_month = message_body.get('reference_month')
    
    logger.info(f"[{stage}] FipeSomaNotifier iniciada para {reference_month}")
    
    # 2. Buscar webhooks do Parameter Store
    try:
        response = ssm.get_parameter(Name=parameter_path, WithDecryption=True)
        webhooks_config = json.loads(response['Parameter']['Value'])
    except Exception as e:
        logger.error(f"[{stage}] Erro ao buscar webhooks do Parameter Store: {str(e)}")
        return {"status": "error", "message": "Failed to fetch webhooks"}
    
    # 3. Disparar cada webhook
    results = []
    for webhook in webhooks_config.get('webhooks', []):
        result = call_webhook(webhook, message_body, timeout, stage)
        results.append(result)
        emit_metric(webhook['name'], result['success'], stage)
    
    logger.info(f"[{stage}] FipeSomaNotifier completada. Resultados: {results}")
    return {"status": "success", "results": results}

def call_webhook(webhook, payload, timeout, stage):
    """Chama webhook com retry exponential backoff"""
    
    webhook_name = webhook.get('name')
    webhook_url = webhook.get('url')
    api_key = webhook.get('api_key')
    
    logger.info(f"[{stage}] Chamando webhook: {webhook_name}")
    
    # Retry configuration: 5s, 10s, 20s, 40s, 80s
    retry_delays = [5, 10, 20, 40, 80]
    last_error = None
    
    for attempt, delay in enumerate(retry_delays, 1):
        try:
            response = requests.post(
                webhook_url,
                json=payload,
                headers={
                    "X-API-Key": api_key,
                    "Content-Type": "application/json"
                },
                timeout=timeout
            )
            
            if 200 <= response.status_code < 300:
                logger.info(f"[{stage}] Webhook {webhook_name} sucesso (tentativa {attempt})")
                return {"name": webhook_name, "success": True, "status_code": response.status_code}
            else:
                last_error = f"HTTP {response.status_code}: {response.text[:100]}"
                logger.warning(f"[{stage}] Webhook {webhook_name} falhou (tentativa {attempt}): {last_error}")
        except requests.exceptions.Timeout:
            last_error = f"Timeout ({timeout}s)"
            logger.warning(f"[{stage}] Webhook {webhook_name} timeout (tentativa {attempt})")
        except Exception as e:
            last_error = str(e)
            logger.error(f"[{stage}] Webhook {webhook_name} erro (tentativa {attempt}): {last_error}")
        
        # Aguardar antes de retry (exceto na última tentativa)
        if attempt < len(retry_delays):
            logger.info(f"[{stage}] Aguardando {delay}s antes de retry...")
            import time
            time.sleep(delay)
    
    # Falha permanente após todas as tentativas
    logger.error(f"[{stage}] Webhook {webhook_name} falhou após {len(retry_delays)} tentativas: {last_error}")
    return {"name": webhook_name, "success": False, "error": last_error}

def emit_metric(webhook_name, success, stage):
    """Emite métrica CloudWatch"""
    metric_name = "webhook_success_count" if success else "webhook_failure_count"
    
    cloudwatch.put_metric_data(
        Namespace='FipeDataStack',
        MetricData=[
            {
                'MetricName': metric_name,
                'Value': 1,
                'Unit': 'Count',
                'Dimensions': [
                    {'Name': 'WebhookName', 'Value': webhook_name},
                    {'Name': 'Stage', 'Value': stage}
                ]
            }
        ]
    )
```

---

### 3.3 SQS Queues (FIFO)

**Configuração CDK:**

```python
# DLQ
webhook_dlq = sqs.Queue(
    self, f"FipeSomaWebhookDLQ-{stage}",
    fifo=True,
    queue_name=f"fipe-soma-webhook-dlq-{stage}.fifo",
    retention_period=Duration.days(14)
)

# Main Queue
webhook_queue = sqs.Queue(
    self, f"FipeSomaWebhookQueue-{stage}",
    fifo=True,
    queue_name=f"fipe-soma-webhook-queue-{stage}.fifo",
    visibility_timeout=Duration.minutes(5),
    retention_period=Duration.days(4),
    dead_letter_queue=sqs.DeadLetterQueue(
        max_receive_count=5,
        queue=webhook_dlq
    )
)

# CloudWatch Alarm para DLQ
webhook_dlq_alarm = cloudwatch.Alarm(
    self, f"FipeSomaWebhookDLQ-Messages-Warning-{stage}",
    metric=webhook_dlq.metric_approximate_number_of_messages_visible(),
    threshold=1,
    evaluation_periods=1,
    alarm_name=f"FipeSomaWebhookDLQ-Messages-Warning-{stage}",
    alarm_description="1+ mensagens em DLQ de webhooks",
    treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING
)

# Adicionar ação SNS ao alarme
webhook_dlq_alarm.add_alarm_action(
    cloudwatch_actions.SnsAction(warning_topic)
)
```

---

### 3.4 Parameter Store: Configuração de Webhooks

**Formato armazenado em `/fipe/webhooks/{stage}`:**

```json
{
  "webhooks": [
    {
      "name": "app1",
      "url": "https://app1.example.com/fipe/notify",
      "api_key": "sk_prod_abc123..."
    },
    {
      "name": "app2",
      "url": "https://app2.example.com/webhooks/fipe",
      "api_key": "sk_prod_xyz789..."
    },
    {
      "name": "app3",
      "url": "https://internal-app.company.com/fipe-update",
      "api_key": "sk_prod_def456..."
    }
  ]
}
```

**Como adicionar novo webhook (manual via AWS CLI):**

```bash
# 1. Buscar configuração atual
aws ssm get-parameter \
  --name /fipe/webhooks/stg \
  --query 'Parameter.Value' \
  --output text > webhooks.json

# 2. Editar webhooks.json e adicionar novo webhook

# 3. Salvar atualizado
aws ssm put-parameter \
  --name /fipe/webhooks/stg \
  --value file://webhooks.json \
  --overwrite \
  --type String \
  --with-decryption
```

---

### 3.5 CloudWatch Metrics

**Métricas emitidas por FipeSomaNotifier:**

```
Namespace: FipeDataStack

Metrics:
├─ webhook_success_count
│  └─ Dimensions: WebhookName, Stage
│  └─ Unit: Count
│
└─ webhook_failure_count
   └─ Dimensions: WebhookName, Stage
   └─ Unit: Count
```

**Exemplos de uso em dashboards:**

```
- webhook_success_count{WebhookName="app1", Stage="stg"} = total webhooks sucesso para app1 em STG
- webhook_failure_count{WebhookName="app2", Stage="prd"} = total webhooks falha para app2 em PRD
```

---

### 3.6 IAM Permissions

**Adicionar à role de Lambda:**

```python
# Para FipeSomaIngestor (existente, apenas adicionar webhook queue)
ingestor_role.add_to_policy(iam.PolicyStatement(
    actions=["sqs:SendMessage"],
    resources=[webhook_queue.queue_arn]
))

# Para FipeSomaNotifier (nova)
notifier_role = iam.Role(
    self, f"FipeSomaNotifierRole-{stage}",
    assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
    managed_policies=[
        iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole")
    ]
)

notifier_role.add_to_policy(iam.PolicyStatement(
    actions=["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"],
    resources=[webhook_queue.queue_arn]
))

notifier_role.add_to_policy(iam.PolicyStatement(
    actions=["ssm:GetParameter"],
    resources=[f"arn:aws:ssm:*:*:parameter/fipe/webhooks/*"]
))

notifier_role.add_to_policy(iam.PolicyStatement(
    actions=["cloudwatch:PutMetricData"],
    resources=["*"]
))
```

---

## 4. Plano de Testes e Validação

### 4.1 Testes Automatizados

**CDK Validation:**
```bash
cdk diff
```
✅ Validar que Lambda FipeSomaNotifier está criada  
✅ Validar que SQS FIFO queues estão configuradas  
✅ Validar que Alarms estão criados  
✅ Validar que IAM permissions estão corretos  

**Unit Tests:**
```bash
python -m pytest tests/
```
✅ Test webhook payload formatting  
✅ Test retry logic (exponential backoff)  
✅ Test timeout handling  
✅ Test Parameter Store parsing  
✅ Test metric emission  

### 4.2 Testes Manuais

**Teste 1: Registrar Webhook em Parameter Store**

```bash
# Atualizar Parameter Store com webhook de teste
aws ssm put-parameter \
  --name /fipe/webhooks/stg \
  --value '{
    "webhooks": [
      {
        "name": "test-app",
        "url": "https://webhook.site/your-unique-id",
        "api_key": "test-key-123"
      }
    ]
  }' \
  --overwrite \
  --type String
```

**Teste 2: Simular END_OF_RECORDS em STG**

```bash
# Colocar mensagem de END_OF_RECORDS na fila de preços
aws sqs send-message \
  --queue-url https://sqs.us-east-1.amazonaws.com/xxx/fipe-soma-price-queue-stg.fifo \
  --message-body '{
    "type": "END_OF_RECORDS",
    "reference_month": "2026-05"
  }' \
  --message-group-id "2026-05" \
  --message-deduplication-id "2026-05-end" \
  --region us-east-1
```

**Teste 3: Validar Webhook foi Disparado**

```bash
# Verificar logs da Lambda FipeSomaNotifier
aws logs tail /aws/lambda/FipeSomaNotifier-stg --follow

# Verificar se webhook foi recebido em webhook.site
# https://webhook.site/your-unique-id

# Verificar métricas CloudWatch
aws cloudwatch get-metric-statistics \
  --namespace FipeDataStack \
  --metric-name webhook_success_count \
  --dimensions Name=WebhookName,Value=test-app Name=Stage,Value=stg \
  --statistics Sum \
  --start-time 2026-05-15T00:00:00Z \
  --end-time 2026-05-16T00:00:00Z \
  --period 3600
```

**Teste 4: Simular Webhook Falhando**

```bash
# Configurar webhook com URL inválida
aws ssm put-parameter \
  --name /fipe/webhooks/stg \
  --value '{
    "webhooks": [
      {
        "name": "failing-app",
        "url": "https://invalid-url-that-does-not-exist.example.com/webhook",
        "api_key": "test-key"
      }
    ]
  }' \
  --overwrite \
  --type String

# Trigger pipeline (ou invoke lambda manualmente)
# Aguardar 5 tentativas + retries (total ~150s)

# Validar que mensagem foi para DLQ
aws sqs receive-message \
  --queue-url https://sqs.us-east-1.amazonaws.com/xxx/fipe-soma-webhook-dlq-stg.fifo \
  --region us-east-1

# Validar que Alarm foi disparado
# Email + Slack devem ter notificação
```

**Teste 5: Métrica de Falha**

```bash
# Verificar métrica de falha
aws cloudwatch get-metric-statistics \
  --namespace FipeDataStack \
  --metric-name webhook_failure_count \
  --dimensions Name=WebhookName,Value=failing-app Name=Stage,Value=stg \
  --statistics Sum \
  --start-time 2026-05-15T00:00:00Z \
  --end-time 2026-05-16T00:00:00Z \
  --period 3600
```

### 4.3 Critérios de Sucesso

| Teste | Critério |
|-------|----------|
| Webhook registrado | Parameter Store contém webhook config |
| END_OF_RECORDS processado | Mensagem aparece em fila webhook-queue |
| Webhook disparado | Payload recebido em webhook.site |
| Métrica de sucesso | webhook_success_count incrementa |
| Webhook falha | Mensagem vai para DLQ após 5 tentativas |
| Métrica de falha | webhook_failure_count incrementa |
| Alarm disparado | Email + Slack notificam quando DLQ tem msgs |

---

## 5. Tratamento de Erros

### 5.1 Cenário: Webhook URL Inválida

**Sintomas:** Webhook nunca responde com sucesso, sempre vai para DLQ  
**Ação:**
1. Verificar URL em Parameter Store (typo?)
2. Testar URL manualmente: `curl -H "X-API-Key: ..." https://webhook-url/...`
3. Atualizar Parameter Store com URL correta
4. Mover mensagem de DLQ de volta para queue (manual)

---

### 5.2 Cenário: API Key Expirada

**Sintomas:** Webhook retorna 401/403 Unauthorized  
**Ação:**
1. Gerar novo API Key na aplicação consumidora
2. Atualizar Parameter Store com nova key
3. Mover mensagem de DLQ de volta para queue (manual)

---

### 5.3 Cenário: Webhook Lento (Timeout)

**Sintomas:** Webhook sempre faz timeout (> 10s)  
**Ação:**
1. Aumentar timeout em FipeSomaNotifier (modificar env var)
2. Ou pedir à aplicação consumidora para otimizar seu webhook
3. Redeploy Lambda com novo timeout

---

### 5.4 Cenário: Parameter Store Inacessível

**Sintomas:** Lambda erro "Access Denied" ao buscar Parameter Store  
**Ação:**
1. Validar IAM permissions (ssm:GetParameter)
2. Validar que Parameter `/fipe/webhooks/{stage}` existe
3. Testar acesso: `aws ssm get-parameter --name /fipe/webhooks/stg`

---

### 5.5 Cenário: FipeSomaIngestor Falha ao Validar RDS

**Sintomas:** END_OF_RECORDS é recebido mas webhook não é disparado  
**Ação:**
1. Validar que registros foram realmente inseridos no RDS
2. Verificar logs de FipeSomaIngestor
3. Se validação falhar legitimamente: webhook não será disparado (esperado)
4. Verificar porque ingestão não completou

---

## 6. Cronograma de Implementação

### Timeline

| Tarefa | Duração | Ordem |
|--------|---------|-------|
| Modificar FipeSomaIngestor (validação + colocar na fila) | 1h | 1 |
| Implementar FipeSomaNotifier Lambda | 2h | 2 |
| Configurar SQS FIFO queues + DLQ | 0.5h | 3 |
| Configurar Parameter Store + webhooks teste | 0.5h | 4 |
| Configurar IAM permissions | 0.5h | 5 |
| Testes automatizados + manuais | 1.5h | 6 |
| Deploy em STG | 0.5h | 7 |
| Deploy em PRD | 0.5h | 8 |

**Total: ~6.5 horas de desenvolvimento**

### Recomendação de Agendamento

- **STG:** Deploy em dia útil, horário comercial
- **PRD:** Deploy após validação em STG (1-2 dias depois)

---

## 7. Componentes Afetados

### Arquivos Novos

```
code_lambdas/src/fipe_api/
└── fipe_soma_notifier.py          (Nova)

tests/
└── test_webhook_notifier.py        (Nova)
```

### Arquivos Modificados

```
code_lambdas/src/fipe_api/
└── fipe_soma_ingestor.py           (Adicionar validação + webhook queue)

fipe_api_stack.py
├── Adicionar SQS FIFO webhook queues + DLQ
├── Adicionar Lambda FipeSomaNotifier
├── Adicionar CloudWatch Alarm para webhook DLQ
└── Adicionar IAM permissions

app.py
├── Env vars para webhook queue URL
```

---

## 8. Integração com Aplicações Consumidoras

### Para Aplicações Integrar com Webhook

**1. Gerar API Key (no Parameter Store):**
```bash
# Exemplo: gerar UUID como API Key
python -c "import uuid; print(f'sk_prod_{uuid.uuid4().hex}')"
# Output: sk_prod_a1b2c3d4e5f6...
```

**2. Registrar Webhook no Parameter Store:**
```json
{
  "name": "minha-app",
  "url": "https://minha-app.example.com/webhooks/fipe",
  "api_key": "sk_prod_a1b2c3d4e5f6..."
}
```

**3. Implementar Endpoint no Webhook:**

```python
# Exemplo em Flask
from flask import request, jsonify
import hmac
import hashlib

@app.route('/webhooks/fipe', methods=['POST'])
def fipe_webhook():
    # 1. Validar API Key
    api_key = request.headers.get('X-API-Key')
    if api_key != os.environ['FIPE_API_KEY']:
        return jsonify({"error": "Unauthorized"}), 401
    
    # 2. Parse payload
    payload = request.json
    reference_month = payload.get('reference_month')
    records_total = payload.get('records_total')
    
    # 3. Fazer algo útil
    logger.info(f"FIPE data available: {reference_month}, {records_total} records")
    
    # Ex: refresh cache, trigger data import, etc.
    trigger_fipe_data_refresh(reference_month)
    
    # 4. Return success
    return jsonify({"status": "received"}), 200
```

---

## 9. Métricas de Sucesso

**Pós-Implementação:**

- ✅ 100% de webhooks entregues com sucesso (métrica webhook_success_count)
- ✅ Webhooks disparados em < 1 minuto após END_OF_RECORDS recebido
- ✅ Falhas de webhook rastreadas em DLQ
- ✅ Alarmes disparados quando há mensagens em DLQ
- ✅ Auditoria completa em CloudWatch Logs
- ✅ Aplicações consumidoras notificadas automaticamente

---

## 10. Próximos Passos

1. ✅ Design aprovado e documentado
2. ⏳ Revisão da spec por stakeholder
3. ⏳ Criação do plano de implementação (skill: writing-plans)
4. ⏳ Implementação em STG
5. ⏳ Testes completos em STG
6. ⏳ Integração de aplicações consumidoras
7. ⏳ Implementação em PRD
8. ⏳ Monitoramento pós-deployment
