# Melhoria 4: Webhooks para Notificação de Dados - Checklist de Implementação

**Data:** 2026-05-15  
**Objetivo:** Implementar sistema de webhooks para notificar aplicações quando dados FIPE são disponibilizados  
**Duração Estimada:** 6.5 horas de desenvolvimento

---

## Preparação

### PASSO 0: Preparação de Ambiente

- [ ] Validar acesso AWS (aws sts get-caller-identity)
- [ ] Confirmar que Melhoria 3 foi deployada com sucesso (SNS Topics, Alarms)
- [ ] Fazer backup de todos os arquivos que serão modificados:
  - [ ] `fipe_api_stack.py`
  - [ ] `code_lambdas/src/fipe_api/fipe_soma_ingestor.py`
  - [ ] `app.py`
- [ ] Confirmar Python 3.12 instalado
- [ ] Executar testes: `python -m pytest tests/`
- [ ] Criar nova branch: `git checkout -b melhoria-4-webhooks`

### PASSO 1: Validar Webhook de Teste (Prerequisito)

- [ ] Acessar https://webhook.site e gerar URL única
- [ ] Salvar URL para testes: `https://webhook.site/your-unique-id`
- [ ] Confirmar que consegue receber POSTs em webhook.site

---

## STG: Staging Deployment

### Etapa 1: Modificar FipeSomaIngestor - Validação + Webhook Queue (1h)

#### 1.1: Modificar arquivo `code_lambdas/src/fipe_api/fipe_soma_ingestor.py`

- [ ] Localizar função `lambda_handler(event, context)` 
- [ ] No topo do arquivo, adicionar imports:
  ```python
  from datetime import datetime
  ```

- [ ] Ao final do `lambda_handler()`, antes do `return`, adicionar:
  ```python
  # Processar END_OF_RECORDS e notificar webhooks
  if body.get('type') == 'END_OF_RECORDS':
      reference_month = body.get('reference_month')
      
      try:
          record_count = validate_records_in_rds(conn, reference_month)
          logger.info(f"INGESTOR-WEBHOOK - Validação OK: {record_count} registros no RDS")
          
          webhook_message = {
              "type": "WEBHOOK_NOTIFY",
              "pipeline": "fipe_monthly_load",
              "reference_month": reference_month,
              "records_total": record_count,
              "duration_minutes": 15,  # TODO: calcular dinamicamente
              "timestamp": datetime.utcnow().isoformat(),
              "stage": os.environ.get("STAGE")
          }
          
          sqs.send_message(
              QueueUrl=os.environ['WEBHOOK_QUEUE_URL'],
              MessageBody=json.dumps(webhook_message),
              MessageGroupId=reference_month,
              MessageDeduplicationId=f"{reference_month}-{datetime.utcnow().timestamp()}"
          )
          logger.info("INGESTOR-WEBHOOK - Mensagem enviada para fila de webhooks")
      except Exception as e:
          logger.error(f"INGESTOR-WEBHOOK - Erro ao validar/notificar: {str(e)}")
          # Não lança exception (não deve bloquear pipeline)
      
      continue
  ```

- [ ] Adicionar função de validação (antes de `lambda_handler`):
  ```python
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

#### 1.2: Adicionar Env Var ao Ingestor

- [ ] No CDK `fipe_api_stack.py`, localizar a configuração de `soma_ingestor_lambda`
- [ ] Adicionar ao `environment`:
  ```python
  "WEBHOOK_QUEUE_URL": os.environ.get('WEBHOOK_QUEUE_URL', ''),
  ```

#### 1.3: Adicionar Permission SQS ao Ingestor

- [ ] No CDK, localizar as permissions da Lambda
- [ ] Adicionar (será criada em próxima etapa):
  ```python
  # Permission será adicionado após criar webhook queue em 1.4
  ```

#### 1.4: Validação

- [ ] Sintaxe Python: `python -m py_compile code_lambdas/src/fipe_api/fipe_soma_ingestor.py`
- [ ] Commit: "modify: FipeSomaIngestor - adicionar validação e webhook queue (Melhoria 4)"

---

### Etapa 2: Criar SQS FIFO Queues para Webhooks (0.5h)

#### 2.1: Adicionar SQS Queues no CDK

- [ ] Adicionar imports:
  ```python
  from aws_cdk import aws_sqs as sqs
  ```

- [ ] Adicionar ao `fipe_api_stack.py` (final da classe `__init__`):
  ```python
  # DLQ para webhooks
  webhook_dlq = sqs.Queue(
      self, f"FipeSomaWebhookDLQ-{stage}",
      fifo=True,
      queue_name=f"fipe-soma-webhook-dlq-{stage}.fifo",
      retention_period=Duration.days(14),
      encryption=sqs.QueueEncryption.KMS_MANAGED
  )
  
  # Main Queue para webhooks (FIFO)
  webhook_queue = sqs.Queue(
      self, f"FipeSomaWebhookQueue-{stage}",
      fifo=True,
      queue_name=f"fipe-soma-webhook-queue-{stage}.fifo",
      visibility_timeout=Duration.minutes(5),
      retention_period=Duration.days(4),
      dead_letter_queue=sqs.DeadLetterQueue(
          max_receive_count=5,
          queue=webhook_dlq
      ),
      encryption=sqs.QueueEncryption.KMS_MANAGED
  )
  ```

#### 2.2: Adicionar CloudWatch Alarm para Webhook DLQ

- [ ] Adicionar (após criar webhook_queue):
  ```python
  webhook_dlq_alarm = cloudwatch.Alarm(
      self, f"FipeSomaWebhookDLQAlarm-{stage}",
      metric=webhook_dlq.metric_approximate_number_of_messages_visible(),
      threshold=1,
      evaluation_periods=1,
      alarm_name=f"FipeSomaWebhookDLQ-Messages-Warning-{stage}",
      alarm_description=f"1+ mensagens em DLQ de webhooks - {stage}",
      treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING
  )
  webhook_dlq_alarm.add_alarm_action(
      cloudwatch_actions.SnsAction(warning_topic)  # usar warning_topic já criada em Melhoria 3
  )
  ```

#### 2.3: Adicionar Permission de SQS ao Ingestor

- [ ] Localizar IAM role do soma_ingestor_lambda
- [ ] Adicionar:
  ```python
  soma_ingestor_lambda.add_to_policy(
      iam.PolicyStatement(
          actions=["sqs:SendMessage"],
          resources=[webhook_queue.queue_arn]
      )
  )
  ```

#### 2.4: Exportar Queue URLs para Outputs

- [ ] Adicionar ao final de `FipeApiStack.__init__()`:
  ```python
  CfnOutput(
      self, f"WebhookQueueUrl-{stage}",
      value=webhook_queue.queue_url,
      description=f"SQS FIFO Queue para Webhooks - {stage}"
  )
  
  CfnOutput(
      self, f"WebhookDLQUrl-{stage}",
      value=webhook_dlq.queue_url,
      description=f"SQS FIFO DLQ para Webhooks - {stage}"
  )
  ```

#### 2.5: Validação e Commit

- [ ] `cdk diff` mostra queues FIFO criadas
- [ ] Commit: "add: SQS FIFO Queues para Webhooks + DLQ (Melhoria 4)"

---

### Etapa 3: Criar Lambda FipeSomaNotifier (2h)

#### 3.1: Criar arquivo `code_lambdas/src/fipe_api/fipe_soma_notifier.py`

- [ ] Criar arquivo com código completo do design doc
- [ ] Validar imports: boto3, requests, json, logging, os, datetime
- [ ] Validar função `call_webhook()` com retry exponencial backoff
- [ ] Validar função `emit_metric()` para CloudWatch

#### 3.2: Configurar Lambda no CDK

- [ ] Adicionar imports:
  ```python
  from aws_cdk import aws_lambda_event_sources as lambda_event_sources
  ```

- [ ] Adicionar Lambda:
  ```python
  notifier_lambda = lambda_.Function(
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
      role=lambda_role,
      layers=[lambda_layer],
      description=f"Disparar webhooks após pipeline FIPE completa - {stage}"
  )
  ```

#### 3.3: Adicionar Event Source (SQS FIFO)

- [ ] Adicionar ao `fipe_api_stack.py`:
  ```python
  notifier_lambda.add_event_source(
      lambda_event_sources.SqsEventSource(
          webhook_queue,
          batch_size=1,
          max_batching_window=Duration.seconds(0)
      )
  )
  ```

#### 3.4: Adicionar IAM Permissions

- [ ] Criar nova role para notifier (ou reusar):
  ```python
  notifier_lambda.add_to_policy(iam.PolicyStatement(
      actions=["ssm:GetParameter"],
      resources=[f"arn:aws:ssm:{region}:{account}:parameter/fipe/webhooks/*"]
  ))
  
  notifier_lambda.add_to_policy(iam.PolicyStatement(
      actions=["cloudwatch:PutMetricData"],
      resources=["*"]
  ))
  ```

#### 3.5: Validação e Commit

- [ ] `cdk diff` mostra Lambda FipeSomaNotifier criada
- [ ] `cdk diff` mostra SQS event source
- [ ] Sintaxe Python: `python -m py_compile code_lambdas/src/fipe_api/fipe_soma_notifier.py`
- [ ] Commit: "add: Lambda FipeSomaNotifier para disparar webhooks (Melhoria 4)"

---

### Etapa 4: Configurar Parameter Store para Webhooks (0.5h)

#### 4.1: Criar Configuração Inicial no Parameter Store

- [ ] Executar:
  ```bash
  aws ssm put-parameter \
    --name /fipe/webhooks/stg \
    --value '{
      "webhooks": [
        {
          "name": "test-webhook",
          "url": "https://webhook.site/your-unique-id",
          "api_key": "test-key-123"
        }
      ]
    }' \
    --type String \
    --region us-east-2
  ```

- [ ] Validar criação:
  ```bash
  aws ssm get-parameter --name /fipe/webhooks/stg --region us-east-2
  ```

#### 4.2: Documentar Formato

- [ ] Criar arquivo `docs/WEBHOOK-CONFIG.md` com:
  - [ ] Formato de JSON
  - [ ] Como adicionar novo webhook
  - [ ] Como validar configuração
  - [ ] Exemplo de payload

#### 4.3: Commit

- [ ] Commit: "add: Parameter Store webhook configuration template (Melhoria 4)"

---

### Etapa 5: Preparar Layer e Deploy em STG (0.5h)

#### 5.1: Rebuild Lambda Layer

- [ ] Executar: `make prepare-layers`
- [ ] Validar que dependências foram incluídas (requests já deve estar)

#### 5.2: Deploy em STG

- [ ] Executar:
  ```bash
  make deploy-stg AWS_PROFILE=your-profile VPC_ID=vpc-xxxx ALLOWED_IP=1.2.3.4
  ```

- [ ] Validar outputs:
  ```
  ✅ Webhook Queue URL
  ✅ Webhook DLQ URL
  ✅ FipeSomaNotifier Lambda criada
  ✅ Alarms criados
  ```

---

### Etapa 6: Testes em STG (1.5h)

#### 6.1: Teste Automatizado CDK

- [ ] Executar: `cdk diff --context vpc_id=xxx --context allowed_ip=xxx`
- [ ] Validar que todos recursos aparecem

#### 6.2: Teste Manual - Registrar Webhook

- [ ] Criar webhook de teste em webhook.site
- [ ] Salvar URL: `https://webhook.site/test-id-123`

- [ ] Atualizar Parameter Store:
  ```bash
  aws ssm put-parameter \
    --name /fipe/webhooks/stg \
    --value '{
      "webhooks": [
        {
          "name": "test-app",
          "url": "https://webhook.site/test-id-123",
          "api_key": "sk_test_abc123"
        }
      ]
    }' \
    --overwrite \
    --type String \
    --region us-east-2
  ```

- [ ] Validar:
  ```bash
  aws ssm get-parameter --name /fipe/webhooks/stg --region us-east-2
  ```

#### 6.3: Teste Manual - Simular END_OF_RECORDS

- [ ] Enviar mensagem para fila de preços:
  ```bash
  aws sqs send-message \
    --queue-url <PRICE_QUEUE_URL> \
    --message-body '{
      "type": "END_OF_RECORDS",
      "reference_month": "2026-05"
    }' \
    --message-group-id "2026-05" \
    --message-deduplication-id "2026-05-end" \
    --region us-east-2
  ```

- [ ] Lambda FipeSomaIngestor processará a mensagem
- [ ] Se validação RDS passou, coloca na webhook queue

#### 6.4: Teste Manual - Validar Webhook Disparado

- [ ] Verificar logs:
  ```bash
  aws logs tail /aws/lambda/FipeSomaNotifier-stg --follow
  ```

- [ ] Acessar webhook.site e validar que POST foi recebido
- [ ] Validar payload contém campos:
  - [ ] "type": "WEBHOOK_NOTIFY"
  - [ ] "reference_month": "2026-05"
  - [ ] "records_total": (número)
  - [ ] "timestamp": (ISO format)

#### 6.5: Teste Manual - Validar Métrica de Sucesso

- [ ] Executar:
  ```bash
  aws cloudwatch get-metric-statistics \
    --namespace FipeDataStack \
    --metric-name webhook_success_count \
    --dimensions Name=WebhookName,Value=test-app Name=Stage,Value=stg \
    --statistics Sum \
    --start-time 2026-05-15T00:00:00Z \
    --end-time 2026-05-16T00:00:00Z \
    --period 3600 \
    --region us-east-2
  ```

- [ ] Validar que Count > 0

#### 6.6: Teste Manual - Simular Webhook Falhando

- [ ] Atualizar webhook com URL inválida:
  ```bash
  aws ssm put-parameter \
    --name /fipe/webhooks/stg \
    --value '{
      "webhooks": [
        {
          "name": "failing-app",
          "url": "https://invalid-webhook-url-that-does-not-exist.example.com",
          "api_key": "test-key"
        }
      ]
    }' \
    --overwrite \
    --type String \
    --region us-east-2
  ```

- [ ] Simular END_OF_RECORDS novamente
- [ ] Aguardar ~150 segundos (5 retries com backoff: 5s+10s+20s+40s+80s)
- [ ] Validar:
  - [ ] Mensagem vai para webhook DLQ
  - [ ] CloudWatch Alarm dispara (WARNING)
  - [ ] Email + Slack notificações enviadas

#### 6.7: Teste Manual - Validar Métrica de Falha

- [ ] Executar:
  ```bash
  aws cloudwatch get-metric-statistics \
    --namespace FipeDataStack \
    --metric-name webhook_failure_count \
    --dimensions Name=WebhookName,Value=failing-app Name=Stage,Value=stg \
    --statistics Sum \
    --start-time 2026-05-15T00:00:00Z \
    --end-time 2026-05-16T00:00:00Z \
    --period 3600 \
    --region us-east-2
  ```

- [ ] Validar Count > 0

#### 6.8: Teste Manual - Validar DLQ

- [ ] Verificar mensagens em DLQ:
  ```bash
  aws sqs receive-message \
    --queue-url <WEBHOOK_DLQ_URL> \
    --max-number-of-messages 10 \
    --region us-east-2
  ```

- [ ] Validar que mensagem contém payload original + headers

---

### Etapa 7: Criar Pull Request STG

- [ ] Todos commits feitos:
  1. FipeSomaIngestor modifications
  2. SQS FIFO Queues + DLQ + Alarm
  3. FipeSomaNotifier Lambda
  4. Parameter Store template

- [ ] `git log --oneline` mostra 4 commits

- [ ] Executar:
  ```bash
  git push origin melhoria-4-webhooks
  gh pr create --title "Melhoria 4: Webhooks para Notificação de Dados" \
    --body "Sistema de webhooks com retry inteligente, Parameter Store config, e métricas CloudWatch"
  ```

- [ ] Validar PR checks
- [ ] Aprovação da PR

---

## PRD: Production Deployment

### Etapa 8: Repetir Etapas 1-7 para PRD (us-east-1)

Executar os mesmos passos, mas com:
- Region: `us-east-1` (em vez de us-east-2)
- Branch: pode ser na mesma ou separada
- Todos os valores devem ser PRD (não STG)

#### 8.1-8.8: Repetir testes em PRD

- [ ] Deploy em us-east-1
- [ ] Repetir todos os testes manuais
- [ ] Validar webhook.site recebe POSTs
- [ ] Validar métricas em CloudWatch

#### 8.9: Merge e Release

- [ ] Merge PR em `main`
- [ ] Criar git tag: `git tag -a v4.0.0-webhooks -m "Melhoria 4: Webhooks"`
- [ ] Push tag: `git push origin v4.0.0-webhooks`

---

## Pós-Deployment

### Etapa 9: Integração com Aplicações Consumidoras (1h)

#### 9.1: Documentar Integração

- [ ] Criar `docs/WEBHOOK-INTEGRATION.md` com:
  - [ ] Formato esperado do webhook endpoint
  - [ ] Headers esperados (X-API-Key)
  - [ ] Payload example
  - [ ] Error handling recommendations
  - [ ] Retry behavior documentation

#### 9.2: Exemplo de Implementação

- [ ] Incluir exemplo de endpoint em Flask/FastAPI:
  ```python
  @app.route('/webhooks/fipe', methods=['POST'])
  def fipe_webhook():
      api_key = request.headers.get('X-API-Key')
      if api_key != os.environ['FIPE_API_KEY']:
          return jsonify({"error": "Unauthorized"}), 401
      
      payload = request.json
      reference_month = payload.get('reference_month')
      records_total = payload.get('records_total')
      
      logger.info(f"FIPE data available: {reference_month}, {records_total} records")
      trigger_fipe_data_refresh(reference_month)
      
      return jsonify({"status": "received"}), 200
  ```

#### 9.3: Notificar Times Consumidores

- [ ] Enviar email para teams que consomem dados FIPE com:
  - [ ] Instruções de integração
  - [ ] Webhook URL
  - [ ] Exemplo de payload
  - [ ] Link para documentação

### Etapa 10: Monitoramento e Validação Final (0.5h)

#### 10.1: Verificar Dashboards

- [ ] CloudWatch Dashboard com métricas:
  - [ ] webhook_success_count (por WebhookName e Stage)
  - [ ] webhook_failure_count (por WebhookName e Stage)
  - [ ] Webhook Queue depth
  - [ ] Webhook DLQ depth

#### 10.2: Documentação Final

- [ ] Atualizar README com informação sobre webhooks
- [ ] Documentar processo de adição de novo webhook
- [ ] Documentar alertas e tratamento de erros

#### 10.3: Notificação ao Time

- [ ] Comunicar ao time:
  - [ ] Webhooks deployados em STG e PRD
  - [ ] Aplicações podem se registrar
  - [ ] Notificações automáticas quando dados ficam disponíveis
  - [ ] Retry automático com backoff exponencial

---

## Commits Esperados (4 no total)

1. `modify: FipeSomaIngestor - adicionar validação e webhook queue (Melhoria 4)`
2. `add: SQS FIFO Queues para Webhooks + DLQ (Melhoria 4)`
3. `add: Lambda FipeSomaNotifier para disparar webhooks (Melhoria 4)`
4. `add: Parameter Store webhook configuration template (Melhoria 4)`

---

## Checklist Final

- [ ] Todos testes em STG passaram
- [ ] Todos testes em PRD passaram
- [ ] Webhook recebe notificações corretamente
- [ ] Retry com backoff exponencial funciona
- [ ] Falhas vão para DLQ e disparam alarms
- [ ] Métricas CloudWatch sendo emitidas
- [ ] PR merge em main
- [ ] Git tag criada
- [ ] Documentação criada
- [ ] Teams consumidoras notificadas
- [ ] Dashboard monitorando webhooks

---

**Duração Total Esperada:** 6.5 horas (0.8 dias de trabalho)

---

## Notas Importantes

### Adicionar Novo Webhook (Pós-Deploy)

Para adicionar novo webhook consumidor (sem redeployar):

```bash
# 1. Buscar configuração atual
aws ssm get-parameter \
  --name /fipe/webhooks/stg \
  --query 'Parameter.Value' \
  --output text > webhooks.json

# 2. Editar webhooks.json - adicionar novo webhook

# 3. Salvar atualizado
aws ssm put-parameter \
  --name /fipe/webhooks/stg \
  --value file://webhooks.json \
  --overwrite \
  --type String \
  --region us-east-2

# 4. Próxima notificação usará novo webhook
```

### Reprocessar Mensagens de DLQ

Se webhook falhou e depois foi corrigido:

```bash
# 1. Buscar mensagens de DLQ
aws sqs receive-message \
  --queue-url <DLQ_URL> \
  --max-number-of-messages 10 \
  --region us-east-2

# 2. Copiar MessageBody e colocar de volta na queue principal
aws sqs send-message \
  --queue-url <WEBHOOK_QUEUE_URL> \
  --message-body '<COPIED_MESSAGE_BODY>' \
  --message-group-id '2026-05' \
  --message-deduplication-id 'manual-reprocess-1' \
  --region us-east-2

# 3. Deletar da DLQ
aws sqs delete-message \
  --queue-url <DLQ_URL> \
  --receipt-handle '<RECEIPT_HANDLE>' \
  --region us-east-2
```
