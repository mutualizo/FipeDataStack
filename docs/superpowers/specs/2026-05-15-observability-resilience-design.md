# Observabilidade e Resiliência com Alarmes + Reprocessamento Inteligente

**Data:** 2026-05-15  
**Autor:** Alexandre Defendi  
**Status:** Design Aprovado

---

## 1. Visão Geral

### Motivador
Atualmente, quando mensagens falham e vão para DLQs, não há alarmes configurados e o reprocessamento é manual. Isso resulta em:
- Falta de visibilidade sobre falhas
- Latência entre falha e detecção
- Sem notificações automáticas
- Reprocessamento manual demorado e propenso a erros

### Objetivo
Implementar um sistema completo de observabilidade com:
1. **Alarmes CloudWatch** para DLQs e erros de Lambda
2. **Notificações automáticas** por Email e Slack
3. **Reprocessamento inteligente** com health check de FIPE
4. **Auditoria completa** de todas as falhas e retries

### Escopo
- CloudWatch Alarms (DLQs + Erros de Lambda)
- SNS Topics (crítico + warning)
- Lambda `RedriveDLQLambda-Scheduled` (hourly cron com health check FIPE)
- Lambda `SNSToSlack` (formatação de notificações)
- EventBridge Rule (cron a cada hora)
- Notificações Email + Slack
- Ambientes: **STG + PRD**

---

## 2. Arquitetura

### Fluxo Completo de Observabilidade

```
┌──────────────────────────┐
│   Lambda Execution       │
│   (Manufacturer/Model/   │
│    Price/Ingestor)       │
└────────┬─────────────────┘
         │
         ├─ ✅ Success → RDS
         │
         └─ ❌ Failure (Retry 1-10)
            │
            └─ Max retries reached
               │
               └─ → Dead Letter Queue (DLQ)
                  │
                  ├─ CloudWatch Alarm
                  │  ├─ FipeManufacturer: CRÍTICO (1+ msgs)
                  │  └─ Outras: WARNING (5+ msgs)
                  │
                  └─ SNS Topic (Critical/Warning)
                     │
                     ├─ Email Notification
                     └─ Slack via Lambda SNSToSlack
                        │
                        ├─ Format: Color + Emoji
                        └─ Include: Status, Action Items
```

### Fluxo de Reprocessamento

```
EventBridge Cron (a cada hora)
         │
         └─ Lambda: RedriveDLQLambda-Scheduled
            │
            ├─ Health Check FIPE API
            │  ├─ Request: HEAD /api/veiculos
            │  ├─ Timeout: 5s
            │  └─ Validar status code < 500
            │
            ├─ Se FIPE OK ✅
            │  └─ Para cada DLQ:
            │     ├─ Receive messages (max 10)
            │     ├─ Send to main queue
            │     ├─ Delete from DLQ
            │     └─ Log: "Reprocessadas N mensagens"
            │
            └─ Se FIPE DOWN ❌
               ├─ NÃO move mensagens
               ├─ Log: "FIPE indisponível"
               ├─ CloudWatch Alarm: "FIPE-API-Down"
               └─ Aguardar próxima hora

Nota: SQS nativo garante MAX 10 tentativas
      (mensagens não ficam em loop infinito)
```

---

## 3. CloudWatch Alarms

### 3.1 Alarmes de DLQ

#### FipeManufacturerDLQ (CRÍTICO)
```
Alarm Name: FipeManufacturerDLQ-Messages-Critical-{stage}
Metric: AWS/SQS → ApproximateNumberOfMessagesVisible
Threshold: >= 1
Period: 1 minute (300 seconds)
Statistic: Average
Actions:
  - SNS: fipe-alerts-critical-{stage}
Treat Missing Data: as notBreaching (não alertar se fila vazia)
Severity: CRITICAL
Description: 1+ mensagens em DLQ do FipeManufacturerLoader
```

#### FipeModelDLQ (WARNING)
```
Alarm Name: FipeModelDLQ-Messages-Warning-{stage}
Metric: AWS/SQS → ApproximateNumberOfMessagesVisible
Threshold: >= 5
Period: 5 minutes (300 seconds)
Statistic: Average
Actions:
  - SNS: fipe-alerts-warning-{stage}
Severity: WARNING
Description: 5+ mensagens em DLQ do FipeModelLoader
```

#### FipePriceDLQ (WARNING)
```
Alarm Name: FipePriceDLQ-Messages-Warning-{stage}
Metric: AWS/SQS → ApproximateNumberOfMessagesVisible
Threshold: >= 5
Period: 5 minutes
Actions:
  - SNS: fipe-alerts-warning-{stage}
Severity: WARNING
```

#### FipeSomaDLQ (WARNING)
```
Alarm Name: FipeSomaDLQ-Messages-Warning-{stage}
Metric: AWS/SQS → ApproximateNumberOfMessagesVisible
Threshold: >= 5
Period: 5 minutes
Actions:
  - SNS: fipe-alerts-warning-{stage}
Severity: WARNING
```

### 3.2 Alarmes de Erros de Lambda

#### Timeout Errors
```
Alarm Name: {LambdaName}-Errors-Timeout-{stage}
Metric: AWS/Lambda → Duration (quando > timeout)
Threshold: > 300000ms (para timeout de 5 min)
Period: 1 minute
Actions:
  - SNS: fipe-alerts-warning-{stage}
Description: Lambda demorando muito (timeout iminente)
```

#### Permission Denied Errors
```
Alarm Name: {LambdaName}-Errors-PermissionDenied-{stage}
Metric: CloudWatch Logs → Invocations com "AccessDenied"
Threshold: >= 1
Period: 1 minute
Actions:
  - SNS: fipe-alerts-critical-{stage}
Description: Erro de permissão em Lambda
```

#### Connection Errors
```
Alarm Name: {LambdaName}-Errors-ConnectionFailed-{stage}
Metric: CloudWatch Logs → Invocations com "Connection refused" ou "Timeout"
Threshold: >= 3
Period: 5 minutes
Actions:
  - SNS: fipe-alerts-warning-{stage}
Description: Falha de conexão em Lambda
```

#### High Error Rate
```
Alarm Name: {LambdaName}-Errors-HighErrorRate-{stage}
Metric: AWS/Lambda → Error Rate (Errors / Invocations)
Threshold: >= 0.05 (5%)
Period: 10 minutes
Actions:
  - SNS: fipe-alerts-warning-{stage}
Description: Taxa de erro alta em Lambda (>5%)
```

### 3.3 Alarme para FIPE API Down

```
Alarm Name: FIPE-API-Health-Check-Failure-{stage}
Metric: CloudWatch Logs → RedriveDLQLambda-Scheduled log group
         Pesquisar por "FIPE_UNAVAILABLE"
Threshold: >= 2 consecutivas (2 horas)
Period: 1 hour
Actions:
  - SNS: fipe-alerts-critical-{stage}
Description: FIPE API indisponível por 2+ horas
```

---

## 4. SNS Topics e Notificações

### 4.1 SNS Topics

#### Critical Topic
```
Topic Name: fipe-alerts-critical-{stage}
Display Name: FIPE Alerts - Critical
Region: us-east-1 (PRD) / us-east-2 (STG)

Subscriptions:
  1. Email: alexandre.defendi@mutualizo.com
  2. Lambda: SNSToSlack (processamento para Slack)
```

#### Warning Topic
```
Topic Name: fipe-alerts-warning-{stage}
Display Name: FIPE Alerts - Warning
Region: us-east-1 (PRD) / us-east-2 (STG)

Subscriptions:
  1. Email: alexandre.defendi@mutualizo.com
  2. Lambda: SNSToSlack (processamento para Slack)
```

### 4.2 Formatos de Notificação

#### Email (CRÍTICO - FipeManufacturerLoader)

**Subject:**
```
[CRÍTICO] FIPE Pipeline - Falha no FipeManufacturerLoader (STG)
```

**Body:**
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ALERTA CRÍTICO: Mensagens em Dead Letter Queue
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Lambda: FipeManufacturerLoader-stg
Ambiente: Staging
Timestamp: 2026-05-15 14:30 UTC
Status: 1 mensagem aguardando reprocessamento

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AÇÕES RECOMENDADAS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Verifique os logs da Lambda:
   aws logs tail /aws/lambda/FipeManufacturerLoader-stg --follow

2. Revise a mensagem de erro em DLQ:
   aws sqs receive-message --queue-url <DLQ_URL> --region us-east-1

3. Investigue e corrija a causa do erro

4. Reprocessamento automático será tentado na próxima execução do cron
   (próxima hora exata)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LINKS ÚTEIS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CloudWatch Dashboard: https://console.aws.amazon.com/cloudwatch/...
Lambda Logs: https://console.aws.amazon.com/logs/...
SQS Console: https://console.aws.amazon.com/sqs/...
```

#### Slack (CRÍTICO)

```
[CRÍTICO] 🔴 FipeManufacturerLoader-stg
1 mensagem em DLQ

Lambda: FipeManufacturerLoader-stg
Timestamp: 2026-05-15 14:30 UTC
Status: Aguardando reprocessamento na próxima hora

[View Logs] [Check Queue] [Dashboard]
```

#### Slack (WARNING)

```
[WARNING] 🟡 FipeModelLoader-stg
5+ mensagens em DLQ

Lambda: FipeModelLoader-stg
Messages: 7
Timestamp: 2026-05-15 14:30 UTC
Action: Será reprocessado na próxima execução do cron

[View Logs] [Check Queue]
```

#### Slack (FIPE Down)

```
[CRÍTICO] 🔴 FIPE API Indisponível
Tentando reprocessar mensagens mas FIPE está fora do ar

Status: API returning 5xx errors
Duration: 2+ horas
Mensagens em espera: 12 (DLQs)

Reprocessamento automático aguardando FIPE retornar online
Last check: 2026-05-15 14:30 UTC
Next check: 2026-05-15 15:30 UTC

[Health Status] [Contact FIPE ONG]
```

---

## 5. Lambda: RedriveDLQLambda-Scheduled

### 5.1 Configuração

```python
# CDK Configuration
redrive_lambda = lambda_.Function(
    self, f"RedriveDLQLambda-Scheduled-{stage}",
    function_name=f"RedriveDLQLambda-Scheduled-{stage}",
    runtime=lambda_.Runtime.PYTHON_3_12,
    code=lambda_.Code.from_asset("code_lambdas/src/fipe_api"),
    handler="fipe_redrive_scheduled.lambda_handler",
    timeout=Duration.minutes(5),
    memory_size=256,
    environment={
        "DLQ_URLS": f"{manufacturer_dlq.queue_url},{model_dlq.queue_url},{price_dlq.queue_url}",
        "TARGET_QUEUE_URLS": f"{manufacturer_queue.queue_url},{model_queue.queue_url},{price_queue.queue_url}",
        "FIPE_API_URL": "http://veiculos.fipe.org.br/api/veiculos",
        "FIPE_HEALTH_CHECK_TIMEOUT": "5"
    },
    role=lambda_role,  # Role com SQS permissions
    layers=[lambda_layer],
    description=f"Reprocessar DLQ a cada hora com health check FIPE - {stage}"
)

# EventBridge Rule (cron a cada hora)
hourly_rule = events.Rule(
    self, f"RedriveDLQHourlyRule-{stage}",
    schedule=events.Schedule.cron(
        minute="0",
        hour="*",
        day="*",
        month="*",
        year="*"
    ),
    description=f"Executar reprocessamento de DLQ a cada hora - {stage}"
)
hourly_rule.add_target(targets.LambdaFunction(redrive_lambda))
redrive_lambda.add_permission(
    f"AllowEventBridgeScheduledInvoke-{stage}",
    principal=iam.ServicePrincipal("events.amazonaws.com"),
    source_arn=hourly_rule.rule_arn
)
```

### 5.2 Lógica de Execução

```python
import json
import boto3
import requests
import logging
import os
from datetime import datetime

sqs = boto3.client('sqs')
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    """
    Verifica saúde da FIPE API e reprocessa DLQs se estiver OK
    """
    stage = os.environ.get('STAGE', 'stg')
    fipe_url = os.environ['FIPE_API_URL']
    timeout = int(os.environ.get('FIPE_HEALTH_CHECK_TIMEOUT', '5'))
    
    # 1. Health check FIPE
    fipe_available = check_fipe_health(fipe_url, timeout)
    
    if not fipe_available:
        logger.warning(f"[{stage}] FIPE API indisponível, aguardando próxima tentativa")
        return {
            "status": "FIPE_UNAVAILABLE",
            "messages_redriven": 0,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    # 2. Se FIPE OK, processar DLQs
    dlq_urls = os.environ['DLQ_URLS'].split(',')
    target_queue_urls = os.environ['TARGET_QUEUE_URLS'].split(',')
    
    total_redriven = 0
    for dlq_url, target_url in zip(dlq_urls, target_queue_urls):
        redriven = redrive_dlq_to_main_queue(dlq_url, target_url)
        total_redriven += redriven
    
    logger.info(f"[{stage}] Reprocessadas {total_redriven} mensagens de DLQs")
    return {
        "status": "SUCCESS",
        "messages_redriven": total_redriven,
        "timestamp": datetime.utcnow().isoformat()
    }

def check_fipe_health(url, timeout):
    """Verifica se FIPE API está disponível"""
    try:
        response = requests.head(url, timeout=timeout)
        is_available = response.status_code < 500
        status_code = response.status_code
        
        logger.info(f"FIPE health check: {status_code} - {'OK' if is_available else 'DOWN'}")
        return is_available
    except requests.exceptions.Timeout:
        logger.error(f"FIPE health check TIMEOUT após {timeout}s")
        return False
    except Exception as e:
        logger.error(f"FIPE health check error: {str(e)}")
        return False

def redrive_dlq_to_main_queue(dlq_url, target_url):
    """Move mensagens de DLQ de volta para fila principal"""
    redriven_count = 0
    
    try:
        while True:
            # Receive até 10 mensagens
            response = sqs.receive_message(
                QueueUrl=dlq_url,
                MaxNumberOfMessages=10,
                WaitTimeSeconds=0
            )
            
            messages = response.get('Messages', [])
            if not messages:
                break
            
            # Enviar cada mensagem para fila principal
            for message in messages:
                try:
                    # Send to main queue
                    sqs.send_message(
                        QueueUrl=target_url,
                        MessageBody=message['Body'],
                        MessageAttributes=message.get('MessageAttributes', {})
                    )
                    
                    # Delete from DLQ
                    sqs.delete_message(
                        QueueUrl=dlq_url,
                        ReceiptHandle=message['ReceiptHandle']
                    )
                    
                    redriven_count += 1
                except Exception as e:
                    logger.error(f"Error redriving message: {str(e)}")
    except Exception as e:
        logger.error(f"Error processing DLQ: {str(e)}")
    
    return redriven_count
```

---

## 6. Lambda: SNSToSlack

### 6.1 Configuração

```python
slack_lambda = lambda_.Function(
    self, f"SNSToSlack-{stage}",
    function_name=f"SNSToSlack-{stage}",
    runtime=lambda_.Runtime.PYTHON_3_12,
    code=lambda_.Code.from_asset("code_lambdas/src/fipe_api"),
    handler="sns_to_slack.lambda_handler",
    timeout=Duration.seconds(30),
    memory_size=128,
    environment={
        "SLACK_WEBHOOK_CRITICAL": os.environ.get("SLACK_WEBHOOK_CRITICAL", ""),
        "SLACK_WEBHOOK_WARNING": os.environ.get("SLACK_WEBHOOK_WARNING", "")
    },
    role=lambda_role,
    layers=[lambda_layer],
    description=f"Converter SNS para Slack format - {stage}"
)

# Subscribe to both SNS topics
critical_topic.add_subscription(subscriptions.LambdaSubscription(slack_lambda))
warning_topic.add_subscription(subscriptions.LambdaSubscription(slack_lambda))
```

### 6.2 Lógica de Execução

```python
import json
import requests
import os
import time

def lambda_handler(event, context):
    """Converte SNS message para formato Slack"""
    
    try:
        # Parse SNS
        sns_message = json.loads(event['Records'][0]['Sns']['Message'])
        subject = event['Records'][0]['Sns']['Subject']
        
        # Determinar tipo de alerta
        is_critical = "CRÍTICO" in subject or "CRITICAL" in subject
        
        # Obter webhook URL
        webhook_key = "SLACK_WEBHOOK_CRITICAL" if is_critical else "SLACK_WEBHOOK_WARNING"
        webhook_url = os.environ.get(webhook_key)
        
        if not webhook_url:
            print(f"Webhook URL not configured: {webhook_key}")
            return {"statusCode": 400}
        
        # Formatar para Slack
        color = "#FF0000" if is_critical else "#FFA500"  # Vermelho ou Laranja
        emoji = "🔴" if is_critical else "🟡"
        
        slack_payload = {
            "attachments": [
                {
                    "color": color,
                    "title": f"{emoji} {subject}",
                    "text": sns_message,
                    "ts": int(time.time())
                }
            ]
        }
        
        # Enviar para Slack
        response = requests.post(webhook_url, json=slack_payload, timeout=10)
        
        return {
            "statusCode": response.status_code,
            "body": json.dumps({"message": "Sent to Slack"})
        }
    except Exception as e:
        print(f"Error: {str(e)}")
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}
```

---

## 7. Plano de Testes e Validação

### 7.1 Testes Automatizados

**CDK Validation:**
```bash
cdk diff
```
✅ Validar que Alarms estão criados  
✅ Validar que SNS Topics estão configurados  
✅ Validar que EventBridge Rule está criada  
✅ Validar que Lambdas estão deployadas  

**Unit Tests:**
```bash
python -m pytest tests/
```
✅ Test health check FIPE (mock down/up)  
✅ Test DLQ message movement  
✅ Test SNS to Slack conversion  
✅ Test when FIPE is down  

### 7.2 Testes Manuais

**Teste 1: DLQ Alarm CRÍTICO**
- Colocar 1 mensagem na DLQ do FipeManufacturerLoader
- Aguardar 1 minuto
- Validar: Email + Slack recebidos, Alarm status = ALARM

**Teste 2: DLQ Alarm WARNING**
- Colocar 5 mensagens na DLQ do FipeModelLoader
- Aguardar 5 minutos
- Validar: Email + Slack recebidos, Alarm status = ALARM

**Teste 3: Health Check FIPE Down**
- Mock FIPE API retornando 500
- Invocar Lambda RedriveDLQLambda-Scheduled
- Validar: Status = FIPE_UNAVAILABLE, messages_redriven = 0, mensagens em DLQ

**Teste 4: Reprocessamento com FIPE OK**
- Colocar 3 mensagens na DLQ
- Invocar Lambda (FIPE OK)
- Validar: Status = SUCCESS, messages_redriven = 3, DLQ vazio, mensagens na fila principal

**Teste 5: Cron Automático**
- Aguardar próxima hora exata (ou criar EventBridge rule de teste)
- Validar: Lambda executou automaticamente, mensagens reprocessadas

**Teste 6: FIPE Down 2+ Horas**
- Mock FIPE down
- Executar Lambda 2x manualmente (ou aguardar 2 horas)
- Validar: Alarm "FIPE-API-Down" dispara, notificação CRÍTICA enviada

### 7.3 Critérios de Sucesso

| Teste | Critério |
|-------|----------|
| Alarm CRÍTICO | Email + Slack em < 2 min, Alarm = ALARM |
| Alarm WARNING | Email + Slack em < 6 min, Alarm = ALARM |
| Health Check | Status correto (OK/DOWN), mensagens não movidas se DOWN |
| Reprocessamento | 100% das mensagens movidas se FIPE OK |
| Cron | Executa automaticamente cada hora exata |
| FIPE Down Alert | Dispara após 2 tentativas consecutivas |

---

## 8. Tratamento de Erros

### 8.1 Cenário: Webhook Slack Inválido

**Sintomas:** Email chega, Slack não recebe  
**Ação:**
1. Verificar SLACK_WEBHOOK_URL em env vars
2. Testar manualmente: `curl -X POST -H 'Content-type: application/json' --data '{"text":"test"}' <WEBHOOK>`
3. Se webhook expirou, gerar novo no Slack workspace

### 8.2 Cenário: Health Check Timeout

**Sintomas:** Health check sempre retorna False  
**Ação:**
1. Aumentar timeout (default 5s)
2. Testar conectividade: `curl -I http://veiculos.fipe.org.br/api/veiculos`
3. Revisar Lambda logs

### 8.3 Cenário: Mensagens em Loop

**Sintomas:** Mensagem reentra na fila, volta para DLQ indefinidamente  
**Ação:**
1. SQS nativo garante max 10 tentativas (max_receive_count=10)
2. Se ainda há loop: revisar lógica da Lambda que processa
3. Adicionar detecção de erros permanentes

### 8.4 Cenário: Alarmes Disparando Muito

**Sintomas:** Muitas notificações mesmo após reprocessamento  
**Ação:**
1. Aumentar threshold (ex: 2 em vez de 1 para CRÍTICO)
2. Aumentar período de avaliação (ex: 5 min em vez de 1 min)
3. Criar alarme composite que aguarda reprocessamento

---

## 9. Cronograma de Implementação

### Timeline

| Tarefa | Duração | Ordem |
|--------|---------|-------|
| CloudWatch Alarms (DLQ + Erros) | 2h | 1 |
| SNS Topics + Subscriptions | 1h | 2 |
| Lambda SNSToSlack | 1.5h | 3 |
| Lambda RedriveDLQLambda-Scheduled | 2h | 4 |
| EventBridge Rule (cron) | 0.5h | 5 |
| Testes automatizados + manuais | 2h | 6 |
| Deploy em STG | 0.5h | 7 |
| Deploy em PRD | 0.5h | 8 |

**Total: ~10 horas de desenvolvimento**

### Recomendação de Agendamento

- **STG:** Deploy em dia útil, horário comercial
- **PRD:** Deploy após validação em STG (1-2 dias depois)

---

## 10. Componentes Afetados

### Arquivos Novos

```
code_lambdas/src/fipe_api/
├── fipe_redrive_scheduled.py      (Nova)
└── sns_to_slack.py                (Nova)

tests/
└── test_redrive_dlq.py            (Nova)
```

### Arquivos Modificados

```
fipe_api_stack.py
├── Adicionar CloudWatch Alarms
├── Adicionar SNS Topics
├── Adicionar Lambda RedriveDLQLambda-Scheduled
├── Adicionar Lambda SNSToSlack
└── Adicionar EventBridge Rule

app.py
├── Env vars para Slack webhooks
```

### Configuração

```
.env (ou AWS Systems Manager)
├── SLACK_WEBHOOK_CRITICAL
└── SLACK_WEBHOOK_WARNING
```

---

## 11. Métricas de Sucesso

**Pós-Implementação:**

- ✅ 100% de alertas chegam por Email < 2 minutos
- ✅ 100% de alertas chegam por Slack < 2 minutos
- ✅ Reprocessamento automático a cada hora exata
- ✅ Zero mensagens em loop (max 10 tentativas)
- ✅ FIPE down detection em < 2 horas
- ✅ Auditoria completa de falhas em CloudWatch Logs

---

## 12. Próximos Passos

1. ✅ Design aprovado e documentado
2. ⏳ Revisão da spec por stakeholder
3. ⏳ Criação do plano de implementação (skill: writing-plans)
4. ⏳ Implementação em STG
5. ⏳ Testes completos em STG
6. ⏳ Implementação em PRD
7. ⏳ Monitoramento pós-deployment
