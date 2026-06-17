# Melhoria 4: Webhooks - Status de Implementação

**Data:** 2026-06-17  
**Status:** ✅ **IMPLEMENTAÇÃO CONCLUÍDA**  
**Branch:** `melhoria-4-webhooks`  
**Commits:** 2 (core implementation + documentation)

---

## Resumo Executivo

Implementação do sistema de notificação por webhooks para alertar aplicações consumidoras quando dados FIPE são disponibilizados. O sistema dispara **automaticamente** quando FipeSomaIngestor (sa-east-1) termina de processar dados com sucesso, invocando as Lambdas FipeSomaNotifier em STG e PRD.

### Fluxo Implementado

```
PIPELINE MENSAL (EventBridge - 4º dia, 01:00 UTC)
    ↓
[FipeManufacturerLoader - sa-east-1]
    ├─ Busca fabricantes API FIPE
    └─ Envia para SQS manufacturer-queue
        ↓
    [FipeModelLoader - sa-east-1]
        ├─ Busca modelos por fabricante
        └─ Envia para SQS model-queue
            ↓
        [FipePriceLoader - sa-east-1]
            ├─ Busca preços por modelo
            └─ Envia para SQS price-queue
                ↓
            [FipeSomaIngestor - sa-east-1]
                ├─ Consome de price-queue
                ├─ Insere em RDS sa-east-1
                ├─ Encaminha para RDS STG (us-east-2)
                ├─ Encaminha para RDS PRD (us-east-1)
                └─ ✨ AQUI INVOCA WEBHOOKS ✨
                    ├─ FipeSomaNotifier-stg (us-east-2)
                    │   ├─ Lê /fipe/webhooks/stg do Parameter Store
                    │   ├─ Dispara POST para cada webhook configurado
                    │   ├─ Retry exponencial se falhar
                    │   └─ Emite métricas CloudWatch
                    │
                    └─ FipeSomaNotifier-prd (us-east-1)
                        ├─ Lê /fipe/webhooks/prd do Parameter Store
                        ├─ Dispara POST para cada webhook configurado
                        ├─ Retry exponencial se falhar
                        └─ Emite métricas CloudWatch
                            ↓
                        [Aplicação Consumidora - ex: Odoo v19]
                            ├─ Recebe POST com dados FIPE
                            ├─ Valida token X-Webhook-Token
                            ├─ Processa dados (atualiza preços, estoque, etc)
                            └─ Retorna 200 OK
```

---

## Arquitetura Corrigida

### O Problema Original

Na primeira implementação, FipeSomaNotifier era invocado **independentemente** em sa-east-1, sem estar integrado ao fluxo da cascade. Isso violava o design de fase descrito.

### A Solução

FipeSomaIngestor (sa-east-1) agora **orquestra** a invocação das Lambdas FipeSomaNotifier:

1. **FipeSomaIngestor-sa-east-1** processa todas as mensagens de price-queue
2. Se **SUCESSO** (total_failures == 0):
   - Extrai `reference_month` da primeira mensagem
   - Conta `success_count` (mensagens processadas com sucesso)
   - Invoca `FipeSomaNotifier-stg` (async) com (reference_month, success_count, "stg")
   - Invoca `FipeSomaNotifier-prd` (async) com (reference_month, success_count, "prd")
3. Se **FALHA** (total_failures > 0):
   - Webhook **não** é disparado (segurança)
   - Mensagens falhadas vão para DLQ para retry manual

### Por Que Esta Abordagem

- ✅ **Automático:** Webhook dispara sem manual trigger
- ✅ **Síncrono com dados:** Dispara APÓS dados serem persistidos em RDS
- ✅ **Isolado por ambiente:** STG e PRD disparam em seus próprios ambientes AWS
- ✅ **SA-EAST-1 não envia notificações:** Apenas orquestra (conforme especificado)
- ✅ **Seguro:** Só dispara se processamento foi bem-sucedido
- ✅ **Observável:** Logs e métricas CloudWatch

---

## Componentes Implementados

### 1. Lambda FipeSomaIngestor Modificada
**Arquivo:** `code_lambdas/src/fipe_api/fipe_soma_ingestor.py`

**Alterações:**
- ✅ Adicionado import `boto3` para lambda client
- ✅ Adicionado função `invoke_webhook_notifier(reference_month, records_count, stage_target)`
- ✅ Extração de `reference_month` durante processamento
- ✅ Contagem de registros processados com sucesso
- ✅ Invocação assíncrona (InvokeFunction com InvocationType="Event") de FipeSomaNotifier-stg e FipeSomaNotifier-prd após sucesso

**Comportamento:**
```python
if total_failures == 0:
    # Webhook é disparado APENAS se sucesso
    invoke_webhook_notifier("2026-06", 45230, "stg")
    invoke_webhook_notifier("2026-06", 45230, "prd")
else:
    # Webhook NÃO é disparado se falhar
    log("Webhook não disparado: falhas no processamento")
```

### 2. Lambda FipeSomaNotifier (Nova)
**Arquivo:** `code_lambdas/src/fipe_api/fipe_soma_notifier.py`

**Responsabilidades:**
- Busca configuração de webhooks do Parameter Store (`/fipe/webhooks/{stage}`)
- Dispara POST para cada webhook configurado
- Implementa retry automático com backoff exponencial (5, 10, 20, 40, 80 segundos)
- Emite métricas CloudWatch (`webhook_success_count`, `webhook_failure_count`)
- Registra logs estruturados para observabilidade

**Payload Enviado:**
```json
{
  "type": "WEBHOOK_NOTIFY",
  "pipeline": "fipe_monthly_load",
  "reference_month": "2026-06",
  "records_total": 45230,
  "timestamp": "2026-06-04T01:15:30.123456Z",
  "stage": "stg" ou "prd"
}
```

**Autenticação:**
- Header: `X-Webhook-Token` (enviado como `api_key` do Parameter Store)
- Aplicação consumidora deve validar este token

### 3. CDK Stack Modificado
**Arquivo:** `fipe_api_stack.py`

**Alterações:**
- ✅ Criação de Lambda `FipeSomaNotifier-stg` (us-east-2)
- ✅ Criação de Lambda `FipeSomaNotifier-prd` (us-east-1)
- ✅ Permissão IAM: `ssm:GetParameter` para `/fipe/webhooks/{stage}`
- ✅ Permissão IAM: `cloudwatch:PutMetricData` para emitir métricas
- ✅ Permissão IAM: `lambda:InvokeFunction` ao ingestor para invocar notifiers
- ✅ CfnOutputs para nomes das Lambdas webhook

### 4. Documentação

#### `docs/WEBHOOK-CONFIG.md` (290 linhas)
- Visão geral da arquitetura
- Instruções de configuração inicial
- Estrutura do Parameter Store JSON
- Como adicionar/remover webhooks sem redeploy
- Estrutura do payload
- Requisitos do endpoint webhook
- Comportamento de retry
- Monitoramento e troubleshooting

#### `docs/TESTE-WEBHOOKS.md` (300 linhas)
7 testes manuais abrangentes:
1. Verificar webhooks configurados
2. Testar webhook com webhook.site
3. Testar retry em caso de falha
4. Testar múltiplos webhooks
5. Testar integração com FipeSomaIngestor
6. Verificar métricas CloudWatch
7. Simular erro (webhook não dispara)

#### `docs/EXEMPLO-ODOO-WEBHOOK.md` (980 linhas)
Integração completa com Odoo v19:
- Modelo de dados `fipe.webhook.data`
- Controller para receber webhook `/api/fipe/webhook`
- Processamento automático (atualizar preços, registrar estoque, notificar vendas)
- 3 opções de token (env var, config param, com expiração)
- Views no Odoo
- Exemplos de teste

### 5. Scripts

#### `setup_webhooks.sh`
Script para inicializar webhooks no Parameter Store:
```bash
./setup_webhooks.sh stg   # Configura /fipe/webhooks/stg em us-east-2
./setup_webhooks.sh prd   # Configura /fipe/webhooks/prd em us-east-1
```

---

## Fluxo de Execução - Exemplo

### Mês: Junho 2026

**1. EventBridge Trigger** (04/06/2026, 01:00 UTC)
```
Dispara FipeManufacturerLoader-sa-east-1
```

**2. Lambda Chain** (01:00 - 01:15 UTC)
```
FipeManufacturerLoader
    ↓ [200 msgs] → SQS
FipeModelLoader
    ↓ [5000 msgs] → SQS
FipePriceLoader
    ↓ [45230 msgs] → SQS
FipeSomaIngestor (sa-east-1)
    ├─ Processa 45230 msgs
    ├─ Insere 45230 registros em RDS sa-east-1
    ├─ Encaminha para RDS STG
    ├─ Encaminha para RDS PRD
    └─ LOG: "Disparando webhooks para STG e PRD"
        ├─ invoke("FipeSomaNotifier-stg", {"reference_month": "2026-06", "records_total": 45230, "stage": "stg"})
        └─ invoke("FipeSomaNotifier-prd", {"reference_month": "2026-06", "records_total": 45230, "stage": "prd"})
```

**3. Webhook Dispatch** (01:15 - 01:20 UTC)

**STG (FipeSomaNotifier-stg em us-east-2):**
```
CloudWatch Log:
├─ NOTIFIER - Handler iniciado
├─ NOTIFIER - Config carregada de /fipe/webhooks/stg: 2 webhook(s)
│   ├─ "odoo-stg"
│   └─ "datamart-stg"
├─ NOTIFIER - Disparando para odoo-stg...
│   └─ POST https://seu-odoo-stg.com/api/fipe/webhook
│       ├─ Header: X-Webhook-Token: seu-token
│       └─ Body: {type, pipeline, reference_month, records_total, timestamp, stage}
│       └─ Response: 200 OK
├─ NOTIFIER - Métrica webhook_success_count emitida para odoo-stg
├─ NOTIFIER - Disparando para datamart-stg...
│   └─ POST https://datamart-stg.com/fipe/load
│       └─ Response: 200 OK
└─ NOTIFIER - Processamento concluído: 2/2 webhooks bem-sucedidos
```

**PRD (FipeSomaNotifier-prd em us-east-1):**
```
CloudWatch Log:
├─ NOTIFIER - Handler iniciado
├─ NOTIFIER - Config carregada de /fipe/webhooks/prd: 1 webhook(s)
│   └─ "odoo-prd"
├─ NOTIFIER - Disparando para odoo-prd...
│   └─ POST https://seu-odoo-prd.com/api/fipe/webhook
│       └─ Response: 200 OK
└─ NOTIFIER - Processamento concluído: 1/1 webhooks bem-sucedidos
```

**4. Aplicações Consumidoras Recebem**
```
Odoo STG:
├─ Valida X-Webhook-Token
├─ Cria registro em fipe.webhook.data
├─ Dispara ações automáticas:
│   ├─ Atualiza preços de veículos
│   ├─ Registra movimentos de estoque
│   ├─ Notifica gestor de vendas via email
│   └─ Gera relatório CSV de preços
└─ Retorna 200 OK

Odoo PRD:
├─ [mesmos passos]
└─ Retorna 200 OK
```

---

## Segurança

### Token de Autenticação

Três opções de configuração:

1. **Variável de Ambiente** (Recomendado STG)
   ```bash
   export FIPE_WEBHOOK_TOKEN="seu-token-secreto"
   ```

2. **ir.config.parameter** (Odoo)
   ```
   Configurações > Técnico > Parâmetros
   Chave: fipe_webhook.api_token
   Valor: seu-token-secreto
   ```

3. **Com Expiração** (Mais seguro PRD)
   ```json
   {
     "token": "seu-token",
     "expires_at": "2026-09-17T00:00:00Z"
   }
   ```

### Validação no Endpoint

```python
# Aplicação consumidora DEVE validar
received_token = request.headers.get('X-Webhook-Token')
if received_token != expected_token:
    return 401 Unauthorized
```

### Idempotência Obrigatória

Como webhooks podem ser chamados múltiplas vezes (retries), endpoint DEVE ser idempotente:

```python
# ✅ CORRETO
def webhook_receiver(data):
    key = f"{data['reference_month']}-{data['stage']}"
    if already_processed(key):
        return 200  # Já foi processado, retorna sucesso
    process(data)
    mark_as_processed(key)
    return 200
```

---

## Configuração Inicial (Pós-Deploy)

### 1. Inicializar Parameter Store

```bash
./setup_webhooks.sh stg
./setup_webhooks.sh prd
```

Ou manual:

```bash
aws ssm put-parameter \
  --name /fipe/webhooks/stg \
  --value '{
    "webhooks": [
      {
        "name": "odoo-webhook",
        "url": "https://seu-odoo-stg.com/api/fipe/webhook",
        "api_key": "seu-token-secreto"
      }
    ]
  }' \
  --type String \
  --region us-east-2
```

### 2. Adicionar Webhooks Sem Redeploy

```bash
# Buscar config atual
aws ssm get-parameter --name /fipe/webhooks/stg --region us-east-2 \
  --query 'Parameter.Value' --output text > webhooks.json

# Editar webhooks.json (adicionar novo webhook)
# Salvar
aws ssm put-parameter --name /fipe/webhooks/stg \
  --value file://webhooks.json --overwrite --type String --region us-east-2

# Próxima notificação usará novo webhook!
```

### 3. Testar

```bash
# Invocar Lambda manualmente
aws lambda invoke \
  --function-name FipeSomaNotifier-stg \
  --payload '{"reference_month": "2026-06", "records_total": 45230, "stage": "stg"}' \
  --region us-east-2 \
  response.json

# Verificar logs
aws logs tail /aws/lambda/FipeSomaNotifier-stg --follow --region us-east-2

# Verificar métricas
aws cloudwatch get-metric-statistics \
  --namespace "FipeWebhooks" \
  --metric-name "webhook_success_count" \
  --region us-east-2
```

---

## Monitoramento Recomendado

### CloudWatch Logs
```bash
# Monitorar Lambda de webhook
aws logs tail /aws/lambda/FipeSomaNotifier-stg --follow
aws logs tail /aws/lambda/FipeSomaNotifier-prd --follow

# Buscar erros
aws logs filter-log-events \
  --log-group-name /aws/lambda/FipeSomaNotifier-stg \
  --filter-pattern "ERROR"
```

### CloudWatch Metrics
```bash
# Ver sucesso/falha por webhook
aws cloudwatch list-metrics --namespace FipeWebhooks

# Dashboard automático
aws cloudwatch put-dashboard \
  --dashboard-name "FIPE-Webhooks" \
  --dashboard-body file://dashboard.json
```

### CloudWatch Alarms (Recomendado)

```bash
# Disparar alerta se webhook falhar
aws cloudwatch put-metric-alarm \
  --alarm-name "FIPE-Webhook-Failures" \
  --metric-name webhook_failure_count \
  --namespace FipeWebhooks \
  --statistic Sum \
  --period 300 \
  --threshold 1 \
  --comparison-operator GreaterThanOrEqualToThreshold \
  --alarm-actions arn:aws:sns:region:account:topic
```

---

## Próximas Etapas

### Curto Prazo (Hoje)
- [ ] Fazer deploy CDK em STG (us-east-2)
- [ ] Fazer deploy CDK em PRD (us-east-1)
- [ ] Executar 7 testes manuais de validação
- [ ] Verificar logs e métricas

### Médio Prazo (Esta Semana)
- [ ] Configurar webhooks reais em apps consumidoras
- [ ] Treinar equipe de consumidores sobre webhook
- [ ] Monitorar primeira notificação mensal
- [ ] Coletar feedback

### Longo Prazo (Próximas Semanas)
- [ ] Adicionar mais apps consumidoras
- [ ] Criar dashboard consolidado
- [ ] Documentar SLAs de webhook
- [ ] Implementar retry automático via SQS (se necessário)

---

## Commits Realizados

```
45f2a52 update: Implementar webhook dispatch cascadeado por FipeSomaIngestor (Melhoria 4)
7af5376 add: Documentação e scripts para configuração de webhooks (Melhoria 4)
```

---

## FAQ

**P: Webhook é acionado em sa-east-1?**
R: Não. FipeSomaIngestor (sa-east-1) orquestra a invocação, mas apenas das Lambdas em STG e PRD.

**P: E se FipeSomaIngestor falhar?**
R: Webhook não é acionado. Mensagens vão para DLQ. Quando corrigir, manual retry ou próximo ciclo mensal.

**P: Posso ter múltiplos webhooks?**
R: Sim! Registre quantos precisar em `/fipe/webhooks/{stage}`.

**P: Preciso fazer redeploy para adicionar webhook?**
R: Não! Atualize Parameter Store e próxima notificação já usa novo webhook.

**P: Quanto tempo leva?**
R: Imediatamente após FipeSomaIngestor terminar (~1 segundo), ou até 150s se houver retries.

**P: Webhook pode ser chamado múltiplas vezes?**
R: Sim, em caso de retries. Implemente idempotência no endpoint.

---

## Conclusão

Melhoria 4 implementa um sistema robusto, seguro e observável de notificação por webhooks. O design corrigido garante que webhooks são disparados **automaticamente** após sucesso do pipeline, sem intervenção manual, e apenas para os ambientes corretos (STG e PRD).

Próximo passo: Deploy em STG e PRD, seguido de validação e integração com aplicações consumidoras.
