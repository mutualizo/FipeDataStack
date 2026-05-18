# Melhoria 3: Observabilidade e Resiliência - Checklist de Implementação

**Data:** 2026-05-15  
**Objetivo:** Implementar CloudWatch Alarms, SNS notificações, e reprocessamento inteligente de DLQ com health check FIPE  
**Duração Estimada:** 10 horas de desenvolvimento

---

## Preparação

### PASSO 0: Preparação de Ambiente

- [ ] Validar acesso AWS (aws sts get-caller-identity)
- [ ] Confirmar regiões de deployment (STG=us-east-2, PRD=us-east-1)
- [ ] Validar Python 3.12 instalado localmente
- [ ] Fazer backup de `fipe_api_stack.py` e `app.py` atuais
- [ ] Confirmar que todos os testes passam atualmente: `python -m pytest tests/`
- [ ] Criar nova branch: `git checkout -b melhoria-3-observability-resilience`

### PASSO 1: Configurar Email SNS (Prerequisito)

- [ ] Confirmar email: alexandre.defendi@mutualizo.com está verificado em SNS
  - Se não: `aws sns verify-email-identity --email-address alexandre.defendi@mutualizo.com`
- [ ] Testar recebimento de email SNS: verificar caixa de entrada

### PASSO 2: Configurar Slack Webhook (Prerequisito)

- [ ] Criar webhook no Slack workspace: Incoming Webhooks
- [ ] Salvar URL: `https://hooks.slack.com/services/YOUR/WEBHOOK/URL`
- [ ] Validar webhook com teste: 
  ```bash
  curl -X POST -H 'Content-type: application/json' \
    --data '{"text":"Test from FipeDataStack"}' \
    YOUR_SLACK_WEBHOOK_URL
  ```
- [ ] Confirmar mensagem chegou em canal Slack

---

## STG: Staging Deployment

### Etapa 1: CloudWatch Alarms para DLQs (1h)

#### 1.1: Modificar `fipe_api_stack.py` - Imports e CloudWatch

- [ ] Adicionar imports no topo do arquivo:
  ```python
  from aws_cdk import aws_cloudwatch as cloudwatch
  from aws_cdk import aws_cloudwatch_actions as cloudwatch_actions
  ```

#### 1.2: Criar Alarmes de DLQ - FipeManufacturerDLQ (CRÍTICO)

- [ ] Adicionar ao final da classe `FipeApiStack.__init__()`:
  ```python
  # CloudWatch Alarm: FipeManufacturerDLQ (CRÍTICO - 1+ mensagens)
  manufacturer_dlq_alarm = cloudwatch.Alarm(
      self, f"FipeManufacturerDLQAlarm-{stage}",
      metric=manufacturer_dlq.metric_approximate_number_of_messages_visible(),
      threshold=1,
      evaluation_periods=1,
      alarm_name=f"FipeManufacturerDLQ-Messages-Critical-{stage}",
      alarm_description=f"CRÍTICO: 1+ mensagens em DLQ do FipeManufacturerLoader-{stage}",
      treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING
  )
  ```

#### 1.3: Criar SNS Topic CRITICAL (sera usado em 1.6)

- [ ] Adicionar SNS Topic:
  ```python
  critical_topic = sns.Topic(
      self, f"FipeAlertsCritical-{stage}",
      topic_name=f"fipe-alerts-critical-{stage}",
      display_name="FIPE Alerts - Critical"
  )
  ```

#### 1.4: Associar Topic ao Alarme CRITICAL

- [ ] Adicionar ação SNS ao alarme:
  ```python
  manufacturer_dlq_alarm.add_alarm_action(
      cloudwatch_actions.SnsAction(critical_topic)
  )
  ```

#### 1.5: Criar Alarmes para outros DLQs (WARNING)

- [ ] Criar SNS Topic WARNING:
  ```python
  warning_topic = sns.Topic(
      self, f"FipeAlertsWarning-{stage}",
      topic_name=f"fipe-alerts-warning-{stage}",
      display_name="FIPE Alerts - Warning"
  )
  ```

- [ ] Adicionar alarmes para Model, Price, e Soma DLQs (5+ mensagens):
  ```python
  # FipeModelDLQ
  model_dlq_alarm = cloudwatch.Alarm(
      self, f"FipeModelDLQAlarm-{stage}",
      metric=model_dlq.metric_approximate_number_of_messages_visible(),
      threshold=5,
      evaluation_periods=1,
      alarm_name=f"FipeModelDLQ-Messages-Warning-{stage}",
      treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING
  )
  model_dlq_alarm.add_alarm_action(cloudwatch_actions.SnsAction(warning_topic))
  
  # FipePriceDLQ
  price_dlq_alarm = cloudwatch.Alarm(
      self, f"FipePriceDLQAlarm-{stage}",
      metric=price_dlq.metric_approximate_number_of_messages_visible(),
      threshold=5,
      evaluation_periods=1,
      alarm_name=f"FipePriceDLQ-Messages-Warning-{stage}",
      treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING
  )
  price_dlq_alarm.add_alarm_action(cloudwatch_actions.SnsAction(warning_topic))
  
  # FipeSomaDLQ
  soma_dlq_alarm = cloudwatch.Alarm(
      self, f"FipeSomaDLQAlarm-{stage}",
      metric=soma_dlq.metric_approximate_number_of_messages_visible(),
      threshold=5,
      evaluation_periods=1,
      alarm_name=f"FipeSomaDLQ-Messages-Warning-{stage}",
      treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING
  )
  soma_dlq_alarm.add_alarm_action(cloudwatch_actions.SnsAction(warning_topic))
  ```

#### 1.6: Validação

- [ ] Executar: `cdk diff --context vpc_id=xxx --context allowed_ip=xxx` e validar alarmes criados
- [ ] Commit: "add: CloudWatch Alarms para DLQs (Melhoria 3)"

---

### Etapa 2: Lambda SNSToSlack (1.5h)

#### 2.1: Criar arquivo `code_lambdas/src/fipe_api/sns_to_slack.py`

- [ ] Criar arquivo com código completo do design doc
- [ ] Validar imports: requests, json, os, time
- [ ] Testar localmente: `python sns_to_slack.py` (sem chamadas reais)

#### 2.2: Configurar Lambda no CDK

- [ ] Adicionar ao `fipe_api_stack.py`:
  ```python
  sns_to_slack_lambda = lambda_.Function(
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
  ```

#### 2.3: Configurar Subscriptions

- [ ] Adicionar subscriptions ao SNS:
  ```python
  from aws_cdk import aws_sns_subscriptions as subscriptions
  
  critical_topic.add_subscription(subscriptions.LambdaSubscription(sns_to_slack_lambda))
  warning_topic.add_subscription(subscriptions.LambdaSubscription(sns_to_slack_lambda))
  ```

#### 2.4: Configurar Email Subscriptions

- [ ] Adicionar email subscription:
  ```python
  critical_topic.add_subscription(
      subscriptions.EmailSubscription("alexandre.defendi@mutualizo.com")
  )
  warning_topic.add_subscription(
      subscriptions.EmailSubscription("alexandre.defendi@mutualizo.com")
  )
  ```

#### 2.5: Validação e Commit

- [ ] `cdk diff` mostra Lambda SNSToSlack criada
- [ ] Commit: "add: Lambda SNSToSlack para notificações Slack (Melhoria 3)"

---

### Etapa 3: Lambda RedriveDLQLambda-Scheduled (2h)

#### 3.1: Criar arquivo `code_lambdas/src/fipe_api/fipe_redrive_scheduled.py`

- [ ] Criar arquivo com código completo do design doc
- [ ] Validar imports: boto3, requests, logging, json, datetime
- [ ] Verificar função `check_fipe_health()` com timeout 5s
- [ ] Verificar função `redrive_dlq_to_main_queue()` com lógica de move

#### 3.2: Configurar Lambda no CDK

- [ ] Adicionar ao `fipe_api_stack.py`:
  ```python
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
          "FIPE_HEALTH_CHECK_TIMEOUT": "5",
          "STAGE": stage
      },
      role=lambda_role,
      layers=[lambda_layer],
      description=f"Reprocessar DLQ a cada hora com health check FIPE - {stage}"
  )
  ```

#### 3.3: Adicionar Permissions para SQS

- [ ] Adicionar ao IAM role:
  ```python
  lambda_role.add_to_policy(iam.PolicyStatement(
      actions=["sqs:ReceiveMessage", "sqs:SendMessage", "sqs:DeleteMessage"],
      resources=[
          manufacturer_dlq.queue_arn,
          model_dlq.queue_arn,
          price_dlq.queue_arn,
          manufacturer_queue.queue_arn,
          model_queue.queue_arn,
          price_queue.queue_arn
      ]
  ))
  ```

#### 3.4: EventBridge Rule para Execução Horária

- [ ] Adicionar Rule:
  ```python
  from aws_cdk import aws_events as events
  from aws_cdk import aws_events_targets as targets
  
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

#### 3.5: Validação e Commit

- [ ] `cdk diff` mostra Lambda RedriveDLQLambda-Scheduled criada
- [ ] `cdk diff` mostra EventBridge Rule criada
- [ ] Commit: "add: Lambda RedriveDLQLambda-Scheduled + EventBridge Rule (Melhoria 3)"

---

### Etapa 4: Preparar Layer e Deploy em STG

#### 4.1: Rebuild Lambda Layer

- [ ] Executar: `make prepare-layers`
- [ ] Validar que fipe_api_layer foi atualizado com novos imports (requests, etc)
- [ ] Commit: "chore: atualizar lambda layer com dependências (Melhoria 3)"

#### 4.2: Deploy em STG

- [ ] Validar env vars estão set (se necessário):
  ```bash
  export SLACK_WEBHOOK_CRITICAL="https://hooks.slack.com/services/..."
  export SLACK_WEBHOOK_WARNING="https://hooks.slack.com/services/..."
  ```

- [ ] Executar deploy:
  ```bash
  make deploy-stg AWS_PROFILE=your-profile VPC_ID=vpc-xxxx ALLOWED_IP=1.2.3.4
  ```

- [ ] Validar outputs:
  ```
  ✅ CloudWatch Alarms criados
  ✅ SNS Topics criados
  ✅ Lambdas criadas e deployadas
  ✅ EventBridge Rule ativa
  ```

---

### Etapa 5: Testes em STG (2h)

#### 5.1: Teste Automatizado CDK

- [ ] Executar: `cdk diff --context vpc_id=xxx --context allowed_ip=xxx`
- [ ] Validar que todos recursos aparecem (sem erros)

#### 5.2: Teste Manual - Alarme CRÍTICO (FipeManufacturerDLQ)

- [ ] Colocar 1 mensagem manualmente em DLQ:
  ```bash
  aws sqs send-message \
    --queue-url <MANUFACTURER_DLQ_URL> \
    --message-body '{"test": "message"}' \
    --region us-east-2
  ```

- [ ] Aguardar 1-2 minutos
- [ ] Validar:
  - [ ] Email recebido em alexandre.defendi@mutualizo.com (subject: CRÍTICO)
  - [ ] Slack recebeu notificação com emoji 🔴
  - [ ] CloudWatch Alarm status: ALARM

- [ ] Limpar: remover mensagem de DLQ

#### 5.3: Teste Manual - Alarme WARNING (FipeModelDLQ)

- [ ] Colocar 5 mensagens em DLQ:
  ```bash
  for i in {1..5}; do
    aws sqs send-message \
      --queue-url <MODEL_DLQ_URL> \
      --message-body "{\"seq\": $i}" \
      --region us-east-2
  done
  ```

- [ ] Aguardar 5-6 minutos
- [ ] Validar:
  - [ ] Email recebido (subject: WARNING)
  - [ ] Slack recebeu notificação com emoji 🟡
  - [ ] CloudWatch Alarm status: ALARM

- [ ] Limpar mensagens

#### 5.4: Teste Manual - Health Check FIPE OK

- [ ] Invocar Lambda manualmente:
  ```bash
  aws lambda invoke \
    --function-name RedriveDLQLambda-Scheduled-stg \
    --region us-east-2 \
    response.json
  
  cat response.json
  ```

- [ ] Validar resposta: `{"status": "SUCCESS", "messages_redriven": 0, ...}`
- [ ] Verificar logs: `aws logs tail /aws/lambda/RedriveDLQLambda-Scheduled-stg --follow`

#### 5.5: Teste Manual - Reprocessamento com Mensagens em DLQ

- [ ] Colocar 3 mensagens em DLQ:
  ```bash
  for i in {1..3}; do
    aws sqs send-message \
      --queue-url <PRICE_DLQ_URL> \
      --message-body "{\"price\": \"test_$i\"}" \
      --region us-east-2
  done
  ```

- [ ] Invocar Lambda RedriveDLQLambda-Scheduled
- [ ] Validar:
  - [ ] Response: `"messages_redriven": 3`
  - [ ] DLQ vazio
  - [ ] 3 mensagens agora em fila principal (Price Queue)

#### 5.6: Teste Automático - Cron Execução Horária

- [ ] Aguardar próxima hora exata (se necessário, criar rule de teste com cron "*/5 * * * *" para testar a cada 5 minutos)
- [ ] Validar logs em CloudWatch: `/aws/lambda/RedriveDLQLambda-Scheduled-stg`
- [ ] Confirmar Lambda executou automaticamente

#### 5.7: Verificação de Integração End-to-End

- [ ] Validar que SNS topics estão subscribed:
  ```bash
  aws sns list-subscriptions-by-topic \
    --topic-arn arn:aws:sns:us-east-2:xxx:fipe-alerts-critical-stg
  ```

- [ ] Confirmar que Lambda SNSToSlack está como subscription
- [ ] Confirmar que Email está como subscription

---

### Etapa 6: Criar Pull Request STG

- [ ] Validar todos commits foram feitos
- [ ] `git log --oneline` mostra 4 commits:
  1. CloudWatch Alarms
  2. SNS Topics
  3. Lambda SNSToSlack
  4. Lambda RedriveDLQLambda-Scheduled + EventBridge

- [ ] Executar:
  ```bash
  git push origin melhoria-3-observability-resilience
  gh pr create --title "Melhoria 3: Observabilidade e Resiliência" \
    --body "CloudWatch Alarms, SNS notificações, DLQ reprocessamento inteligente"
  ```

- [ ] Validar PR checks (workflows deploy)
- [ ] Aprovação da PR

---

## PRD: Production Deployment

### Etapa 7: Repetir Etapas 1-6 para PRD (us-east-1)

Executar os mesmos passos acima, mas com:
- Region: `us-east-1` (em vez de us-east-2)
- Branch: pode ser na mesma branch ou branch separada `melhoria-3-prd`
- Todos os valores devem referir PRD (não STG)

#### 7.1-7.6: Repetir todos os testes em PRD

- [ ] Executar `make deploy-prd` com context correto
- [ ] Repetir testes manuais em us-east-1
- [ ] Validar email + Slack notificações chegam

#### 7.7: Merge e Release

- [ ] Merge PR em `main`
- [ ] Criar git tag: `git tag -a v3.0.0-observability -m "Melhoria 3: Observabilidade e Resiliência"`
- [ ] Push tag: `git push origin v3.0.0-observability`

---

## Pós-Deployment

### Etapa 8: Monitoramento e Validação Final (0.5h)

#### 8.1: Verificar Metrics Dashboard

- [ ] Acessar CloudWatch Dashboard
- [ ] Validar que métricas estão sendo coletadas:
  - [ ] DLQ message counts
  - [ ] Lambda execution counts
  - [ ] Lambda error rates

#### 8.2: Documentação e Runbook

- [ ] Documentar processo de reprocessamento manual (se necessário)
- [ ] Documentar como atualizar Slack webhooks
- [ ] Documentar como aumentar thresholds de alarms

#### 8.3: Notificação ao Time

- [ ] Comunicar ao time:
  - [ ] Melhoria 3 deployada com sucesso em STG e PRD
  - [ ] Notificações automáticas agora ativas
  - [ ] DLQ reprocessamento automático a cada hora
  - [ ] Slack workspace recebendo notificações

---

## Commits Esperados (4 no total)

1. `add: CloudWatch Alarms para DLQs (Melhoria 3)`
2. `add: SNS Topics e Email Subscriptions (Melhoria 3)`
3. `add: Lambda SNSToSlack para notificações Slack (Melhoria 3)`
4. `add: Lambda RedriveDLQLambda-Scheduled + EventBridge Rule (Melhoria 3)`

---

## Checklist Final

- [ ] Todos testes em STG passaram
- [ ] Todos testes em PRD passaram
- [ ] Email notificações funcionando
- [ ] Slack notificações funcionando
- [ ] DLQ reprocessamento automático ativo
- [ ] PR merge em main
- [ ] Git tag criada e pushada
- [ ] Team notificado
- [ ] Documentação atualizada

---

**Duração Total Esperada:** 10 horas (1.25 dias de trabalho)
