# FASE 5: Testes End-to-End (E2E) - Pipeline Completa + Dual-Write

**Status:** 🔄 PENDENTE  
**Tempo Estimado:** 2-3 horas  
**Branch:** multi-region-sa-east-1  
**Data Planejada:** 2026-05-20+  

---

## Resumo Executivo

FASE 5 valida que:
1. ✅ Pipeline completa executa sem erros (Manufacturer → Model → Price → Ingestor)
2. ✅ Dados são injetados simultaneamente em RDS STG (us-east-2) e PRD (us-east-1)
3. ✅ Consistência: Ambos os RDS têm exatamente os mesmos registros
4. ✅ Tratamento de erros: Dead Letter Queues funcionam corretamente
5. ✅ Rollback automático: Se um RDS falha, ambos rollback
6. ✅ Logs são claros e rastreáveis

Esta é a **última validação crítica** antes de deletar a infraestrutura antiga em FASE 6.

---

## Pré-Requisitos

Antes de iniciar FASE 5:

- [x] FASE 4 completada (stack em sa-east-1 deployada)
- [x] Snapshots STG e PRD criados (para rollback de emergência)
- [x] VPC Peering PRD (sa-east-1 ↔ us-east-1) ACTIVE
- [x] RDS STG público com IP whitelist (189.36.254.27/32)
- [x] Credentials Secrets Manager atualizadas
- [x] Lambda Layer com todas as dependências
- [x] CloudWatch Logs configurado

---

## 5.1: Validação de Pré-Teste

Antes de executar o teste, validar que tudo está pronto:

### 5.1.1 Verificar Lambdas Existem

```bash
export AWS_PROFILE=mutualizo

# Listar todas as 5 Lambdas
aws lambda list-functions \
  --region sa-east-1 \
  --query 'Functions[?contains(FunctionName, `Fipe`)].{Name:FunctionName, Runtime:Runtime, Memory:MemorySize}' \
  --output table
```

**Resultado Esperado:**
```
├─ FipeManufacturerLoader    | python3.10 | 256 MB
├─ FipeModelLoader           | python3.10 | 256 MB
├─ FipePriceLoader           | python3.10 | 256 MB
├─ FipeSomaIngestor          | python3.10 | 256 MB
└─ RedriveDLQLambda          | python3.10 | 256 MB
```

### 5.1.2 Verificar SQS Queues Existem

```bash
export AWS_PROFILE=mutualizo

# Listar todas as 6 filas FIFO
aws sqs list-queues \
  --region sa-east-1 \
  --query 'QueueUrls[?contains(@, `fipe`)]' \
  --output json | jq -r '.[] | split("/") | .[-1]'
```

**Resultado Esperado:**
```
fipe-manufacturer-queue.fifo
fipe-model-queue.fifo
fipe-price-queue.fifo
fipe-manufacturer-dlq.fifo
fipe-model-dlq.fifo
fipe-price-dlq.fifo
```

### 5.1.3 Verificar Event Source Mappings

```bash
export AWS_PROFILE=mutualizo

# Listar mapeamentos de origem de evento
aws lambda list-event-source-mappings \
  --region sa-east-1 \
  --query 'EventSourceMappings[?contains(EventSourceArn, `fipe`)].{Function:FunctionArn, Source:EventSourceArn, State:State}' \
  --output table
```

**Resultado Esperado:**
```
├─ FipeModelLoader  | fipe-manufacturer-queue.fifo | ENABLED
├─ FipePriceLoader  | fipe-model-queue.fifo        | ENABLED
└─ FipeSomaIngestor | fipe-price-queue.fifo        | ENABLED
```

### 5.1.4 Verificar Endpoints RDS Acessíveis

```bash
export AWS_PROFILE=mutualizo

# Verificar STG
aws rds describe-db-clusters \
  --db-cluster-identifier fipedatacluster-stg \
  --region us-east-2 \
  --query 'DBClusters[0].{Endpoint:Endpoint, Port:Port, PubliclyAccessible:PubliclyAccessible, Status:Status}' \
  --output table

# Resultado esperado:
# Endpoint: fipedatacluster-stg.cluster-cdqeius2qmwf.us-east-2.rds.amazonaws.com
# Port: 5432
# PubliclyAccessible: true
# Status: available

# Verificar PRD
aws rds describe-db-clusters \
  --db-cluster-identifier fipedatacluster-prd \
  --region us-east-1 \
  --query 'DBClusters[0].{Endpoint:Endpoint, Port:Port, Status:Status}' \
  --output table

# Resultado esperado:
# Endpoint: fipedatacluster-prd.cluster-chkg2mxlx9z0.us-east-1.rds.amazonaws.com
# Port: 5432
# Status: available
```

### 5.1.5 Verificar Security Groups

**STG (us-east-2):**
```bash
export AWS_PROFILE=mutualizo
AWS_ACCOUNT_ID="652510808251"

# Obter SG do RDS STG
STG_SG_ID=$(aws rds describe-db-clusters \
  --db-cluster-identifier fipedatacluster-stg \
  --region us-east-2 \
  --query 'DBClusters[0].VpcSecurityGroups[0].VpcSecurityGroupId' \
  --output text)

echo "SG STG: $STG_SG_ID"

# Verificar regra para IP 189.36.254.27/32
aws ec2 describe-security-groups \
  --group-ids $STG_SG_ID \
  --region us-east-2 \
  --query 'SecurityGroups[0].IpPermissions[?FromPort==`5432`]' \
  --output table
```

**Resultado Esperado:**
```
IpProtocol: tcp
FromPort: 5432
ToPort: 5432
IpRanges: 189.36.254.27/32 (Acesso de Lambda sa-east-1)
```

**PRD (us-east-1):**
```bash
export AWS_PROFILE=mutualizo

# Obter SG do RDS PRD
PRD_SG_ID=$(aws rds describe-db-clusters \
  --db-cluster-identifier fipedatacluster-prd \
  --region us-east-1 \
  --query 'DBClusters[0].VpcSecurityGroups[0].VpcSecurityGroupId' \
  --output text)

echo "SG PRD: $PRD_SG_ID"

# Verificar regra para 172.31.0.0/16 (CIDR sa-east-1)
aws ec2 describe-security-groups \
  --group-ids $PRD_SG_ID \
  --region us-east-1 \
  --query 'SecurityGroups[0].IpPermissions[?FromPort==`5432`]' \
  --output table
```

**Resultado Esperado:**
```
IpProtocol: tcp
FromPort: 5432
ToPort: 5432
IpRanges: 172.31.0.0/16 (CIDR VPC sa-east-1 via peering)
```

---

## 5.2: Preparação de Dados

Antes de executar o teste, preparar ambiente:

### 5.2.1 Limpar Queues (Opcional)

Se houver mensagens antigas nas queues, limpar:

```bash
export AWS_PROFILE=mutualizo

# Purge manufacturer queue
aws sqs purge-queue \
  --queue-url https://sqs.sa-east-1.amazonaws.com/652510808251/fipe-manufacturer-queue.fifo \
  --region sa-east-1

# Purge model queue
aws sqs purge-queue \
  --queue-url https://sqs.sa-east-1.amazonaws.com/652510808251/fipe-model-queue.fifo \
  --region sa-east-1

# Purge price queue
aws sqs purge-queue \
  --queue-url https://sqs.sa-east-1.amazonaws.com/652510808251/fipe-price-queue.fifo \
  --region sa-east-1

# Purge DLQs
aws sqs purge-queue \
  --queue-url https://sqs.sa-east-1.amazonaws.com/652510808251/fipe-manufacturer-dlq.fifo \
  --region sa-east-1

aws sqs purge-queue \
  --queue-url https://sqs.sa-east-1.amazonaws.com/652510808251/fipe-model-dlq.fifo \
  --region sa-east-1

aws sqs purge-queue \
  --queue-url https://sqs.sa-east-1.amazonaws.com/652510808251/fipe-price-dlq.fifo \
  --region sa-east-1

echo "✅ Queues limpas"
```

### 5.2.2 Capturar Row Counts Iniciais

```bash
export AWS_PROFILE=mutualizo

# Contar registros STG
STG_INITIAL=$(aws rds describe-db-clusters \
  --db-cluster-identifier fipedatacluster-stg \
  --region us-east-2 \
  --query 'DBClusters[0].AllocatedStorage' \
  --output text)

echo "STG Initial State:"
echo "  Cluster: fipedatacluster-stg"
echo "  Region: us-east-2"

# Contar registros PRD
PRD_INITIAL=$(aws rds describe-db-clusters \
  --db-cluster-identifier fipedatacluster-prd \
  --region us-east-1 \
  --query 'DBClusters[0].AllocatedStorage' \
  --output text)

echo "PRD Initial State:"
echo "  Cluster: fipedatacluster-prd"
echo "  Region: us-east-1"
```

---

## 5.3: Executar Pipeline E2E

### 5.3.1 Invocar FipeManufacturerLoader

```bash
export AWS_PROFILE=mutualizo

echo "⏱️  Iniciando teste de pipeline..."
echo "🚀 Invocando FipeManufacturerLoader..."

# Invocar Lambda
aws lambda invoke \
  --function-name FipeManufacturerLoader \
  --region sa-east-1 \
  --log-type Tail \
  --payload '{}' \
  response.json

# Mostrar resposta
echo ""
echo "📄 Resposta da invocação:"
cat response.json | jq .

# Capturar timestamp de início
START_TIME=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "⏰ Tempo de início do teste: $START_TIME"
```

**Resultado Esperado:**
```json
{
  "StatusCode": 200,
  "FunctionVersion": "$LATEST",
  "LogResult": "..."
}
```

### 5.3.2 Monitorar Logs em Cascata (Múltiplas Abas)

Abrir **5 abas de terminal** simultâneas (uma para cada Lambda):

**Aba 1 - FipeManufacturerLoader:**
```bash
export AWS_PROFILE=mutualizo
aws logs tail /aws/lambda/FipeManufacturerLoader \
  --region sa-east-1 \
  --follow \
  --format short
```

**Aba 2 - FipeModelLoader:**
```bash
export AWS_PROFILE=mutualizo
aws logs tail /aws/lambda/FipeModelLoader \
  --region sa-east-1 \
  --follow \
  --format short
```

**Aba 3 - FipePriceLoader:**
```bash
export AWS_PROFILE=mutualizo
aws logs tail /aws/lambda/FipePriceLoader \
  --region sa-east-1 \
  --follow \
  --format short
```

**Aba 4 - FipeSomaIngestor:**
```bash
export AWS_PROFILE=mutualizo
aws logs tail /aws/lambda/FipeSomaIngestor \
  --region sa-east-1 \
  --follow \
  --format short
```

**Aba 5 - CloudWatch Insights (opcional):**
```bash
# Usar AWS Console para ver logs de todas as Lambdas
# https://console.aws.amazon.com/logs/home?region=sa-east-1
```

### 5.3.3 Sequência de Execução Esperada

```
T+0s   📌 FipeManufacturerLoader invocado
       ├─ Chama FIPE API para listar fabricantes
       ├─ Envia mensagens para SQS manufacturer-queue
       └─ Retorna com sucesso

T+5s   📌 FipeModelLoader dispara (SQS trigger)
       ├─ Consome mensagens de manufacturer-queue
       ├─ Para cada fabricante, chama FIPE API para modelos
       ├─ Envia mensagens para SQS model-queue
       └─ Deleta mensagens de manufacturer-queue

T+10s  📌 FipePriceLoader dispara (SQS trigger)
       ├─ Consome mensagens de model-queue
       ├─ Para cada modelo, chama FIPE API para preços
       ├─ Envia mensagens para SQS price-queue
       └─ Deleta mensagens de model-queue

T+15s  📌 FipeSomaIngestor dispara (SQS trigger)
       ├─ Consome mensagens de price-queue
       ├─ Abre conexão com RDS STG
       ├─ Abre conexão com RDS PRD
       ├─ Inicia transação em ambos
       ├─ INSERT registros em fipe_vehicle_price (STG)
       ├─ INSERT registros em fipe_vehicle_price (PRD)
       ├─ COMMIT em STG
       ├─ COMMIT em PRD
       ├─ Deleta mensagens de price-queue
       └─ Retorna sucesso

T+20s  ✅ Pipeline completa (todas as 4 Lambdas executadas)
       ✅ Dados em STG
       ✅ Dados em PRD
       ✅ DLQs vazias
```

### 5.3.4 Sinais de Sucesso nos Logs

Procurar por estes padrões nos logs:

**FipeManufacturerLoader:**
```
✅ "Fetched 40 manufacturers from FIPE API"
✅ "Sent 40 messages to SQS manufacturer-queue"
✅ "Lambda completed successfully"
```

**FipeModelLoader:**
```
✅ "Processing batch of 40 messages from manufacturer-queue"
✅ "Fetching models for manufacturer X..."
✅ "Sent 1200 messages to SQS model-queue"
✅ "Successfully processed 40 messages"
```

**FipePriceLoader:**
```
✅ "Processing batch of 40 messages from model-queue"
✅ "Fetching prices for model X..."
✅ "Sent 2400 messages to SQS price-queue"
✅ "Successfully processed 1200 messages"
```

**FipeSomaIngestor:**
```
✅ "Processing batch of 40 messages from price-queue"
✅ "Connected to RDS STG at fipedatacluster-stg..."
✅ "Connected to RDS PRD at fipedatacluster-prd..."
✅ "Starting transaction..."
✅ "Inserted 2400 rows in STG"
✅ "Inserted 2400 rows in PRD"
✅ "Committed transaction STG"
✅ "Committed transaction PRD"
✅ "Successfully processed 2400 messages"
```

### 5.3.5 Sinais de Erro (O Que Evitar)

❌ **Erros de Conexão:**
```
❌ "Connection refused to RDS"
❌ "Unable to connect to fipedatacluster-stg"
❌ "Network error"
```

❌ **Erros de Credenciais:**
```
❌ "Authentication failed"
❌ "Invalid credentials"
❌ "Access denied"
```

❌ **Erros de Transação:**
```
❌ "Transaction rollback in STG"
❌ "Transaction rollback in PRD"
❌ "Inconsistent state detected"
```

❌ **Erros de SQS:**
```
❌ "Message not found in queue"
❌ "Queue not found"
❌ "Access denied to queue"
```

---

## 5.4: Validar Dados em RDS

### 5.4.1 Obter Credentials das Secrets

```bash
export AWS_PROFILE=mutualizo

# Obter secrets do RDS
SECRET_STG=$(aws secretsmanager get-secret-value \
  --secret-id fipedatacluster-stg-secret \
  --region us-east-2 \
  --query 'SecretString' \
  --output text 2>/dev/null || echo "{}")

SECRET_PRD=$(aws secretsmanager get-secret-value \
  --secret-id fipedatacluster-prd-secret \
  --region us-east-1 \
  --query 'SecretString' \
  --output text 2>/dev/null || echo "{}")

# Extrair password (se disponível)
STG_PASSWORD=$(echo $SECRET_STG | jq -r '.password' 2>/dev/null || echo "")
PRD_PASSWORD=$(echo $SECRET_PRD | jq -r '.password' 2>/dev/null || echo "")

echo "STG Secret: $SECRET_STG"
echo "PRD Secret: $SECRET_PRD"
```

### 5.4.2 Conectar ao RDS STG e Contar Registros

```bash
export AWS_PROFILE=mutualizo

STG_HOST="fipedatacluster-stg.cluster-cdqeius2qmwf.us-east-2.rds.amazonaws.com"
STG_USER="postgres"
STG_DB="fipedata"

echo "🔗 Conectando ao RDS STG..."
echo "   Host: $STG_HOST"
echo "   User: $STG_USER"
echo "   DB: $STG_DB"

# Contar total de registros
STG_COUNT=$(psql -h $STG_HOST -U $STG_USER -d $STG_DB -t -c \
  "SELECT COUNT(*) FROM fipe_vehicle_price;" 2>/dev/null || echo "ERRO")

echo "📊 STG Row Count: $STG_COUNT"

# Detalhe por tabela
psql -h $STG_HOST -U $STG_USER -d $STG_DB -t -c \
  "SELECT 
     (SELECT COUNT(*) FROM fipe_manufacturer) as manufacturers,
     (SELECT COUNT(*) FROM fipe_vehicle_model) as models,
     (SELECT COUNT(*) FROM fipe_vehicle_price) as prices;" 2>/dev/null
```

**Resultado Esperado:**
```
manufacturers | models | prices
───────────────────────────────
      40      |  1200  |  2400
```

### 5.4.3 Conectar ao RDS PRD e Contar Registros

```bash
export AWS_PROFILE=mutualizo

PRD_HOST="fipedatacluster-prd.cluster-chkg2mxlx9z0.us-east-1.rds.amazonaws.com"
PRD_USER="postgres"
PRD_DB="fipedata"

echo "🔗 Conectando ao RDS PRD..."
echo "   Host: $PRD_HOST"
echo "   User: $PRD_USER"
echo "   DB: $PRD_DB"

# Contar total de registros
PRD_COUNT=$(psql -h $PRD_HOST -U $PRD_USER -d $PRD_DB -t -c \
  "SELECT COUNT(*) FROM fipe_vehicle_price;" 2>/dev/null || echo "ERRO")

echo "📊 PRD Row Count: $PRD_COUNT"

# Detalhe por tabela
psql -h $PRD_HOST -U $PRD_USER -d $PRD_DB -t -c \
  "SELECT 
     (SELECT COUNT(*) FROM fipe_manufacturer) as manufacturers,
     (SELECT COUNT(*) FROM fipe_vehicle_model) as models,
     (SELECT COUNT(*) FROM fipe_vehicle_price) as prices;" 2>/dev/null
```

**Resultado Esperado:**
```
manufacturers | models | prices
───────────────────────────────
      40      |  1200  |  2400
```

### 5.4.4 Validar Consistency (STG = PRD)

```bash
export AWS_PROFILE=mutualizo

STG_HOST="fipedatacluster-stg.cluster-cdqeius2qmwf.us-east-2.rds.amazonaws.com"
PRD_HOST="fipedatacluster-prd.cluster-chkg2mxlx9z0.us-east-1.rds.amazonaws.com"

# Contar em ambos
STG_COUNT=$(psql -h $STG_HOST -U postgres -d fipedata -t -c \
  "SELECT COUNT(*) FROM fipe_vehicle_price;" 2>/dev/null)

PRD_COUNT=$(psql -h $PRD_HOST -U postgres -d fipedata -t -c \
  "SELECT COUNT(*) FROM fipe_vehicle_price;" 2>/dev/null)

echo "📊 Comparação de Row Counts:"
echo "   STG: $STG_COUNT"
echo "   PRD: $PRD_COUNT"

if [ "$STG_COUNT" == "$PRD_COUNT" ]; then
  echo "✅ CONSISTENCY OK - Ambos têm $STG_COUNT registros"
else
  echo "❌ INCONSISTENCY DETECTED!"
  echo "   Diferença: $((PRD_COUNT - STG_COUNT))"
  exit 1
fi
```

### 5.4.5 Amostragem de Dados (Sample Check)

```bash
export AWS_PROFILE=mutualizo

STG_HOST="fipedatacluster-stg.cluster-cdqeius2qmwf.us-east-2.rds.amazonaws.com"
PRD_HOST="fipedatacluster-prd.cluster-chkg2mxlx9z0.us-east-1.rds.amazonaws.com"

echo "🔍 Amostragem de dados (primeiras 5 linhas):"
echo ""
echo "=== STG ==="
psql -h $STG_HOST -U postgres -d fipedata -c \
  "SELECT fipe_id, name, model_id, price LIMIT 5;" 2>/dev/null

echo ""
echo "=== PRD ==="
psql -h $PRD_HOST -U postgres -d fipedata -c \
  "SELECT fipe_id, name, model_id, price LIMIT 5;" 2>/dev/null
```

**Resultado Esperado:**
```
=== STG ===
fipe_id | name           | model_id | price
────────────────────────────────────────────
  xxx   | Toyota Corolla |  yyy     | 95000.00
  xxx   | Honda Civic    |  yyy     | 88000.00
  ...

=== PRD ===
fipe_id | name           | model_id | price
────────────────────────────────────────────
  xxx   | Toyota Corolla |  yyy     | 95000.00
  xxx   | Honda Civic    |  yyy     | 88000.00
  ...
```

---

## 5.5: Validar Dead Letter Queues (DLQs)

### 5.5.1 Verificar Contagem de Mensagens em DLQs

```bash
export AWS_PROFILE=mutualizo
ACCOUNT_ID="652510808251"

# Verificar cada DLQ
echo "🔍 Verificando Dead Letter Queues:"

# Manufacturer DLQ
MANU_DLQ_COUNT=$(aws sqs get-queue-attributes \
  --queue-url https://sqs.sa-east-1.amazonaws.com/$ACCOUNT_ID/fipe-manufacturer-dlq.fifo \
  --attribute-names ApproximateNumberOfMessages \
  --region sa-east-1 \
  --query 'Attributes.ApproximateNumberOfMessages' \
  --output text)

echo "📭 Manufacturer DLQ: $MANU_DLQ_COUNT mensagens"

# Model DLQ
MODEL_DLQ_COUNT=$(aws sqs get-queue-attributes \
  --queue-url https://sqs.sa-east-1.amazonaws.com/$ACCOUNT_ID/fipe-model-dlq.fifo \
  --attribute-names ApproximateNumberOfMessages \
  --region sa-east-1 \
  --query 'Attributes.ApproximateNumberOfMessages' \
  --output text)

echo "📭 Model DLQ: $MODEL_DLQ_COUNT mensagens"

# Price DLQ
PRICE_DLQ_COUNT=$(aws sqs get-queue-attributes \
  --queue-url https://sqs.sa-east-1.amazonaws.com/$ACCOUNT_ID/fipe-price-dlq.fifo \
  --attribute-names ApproximateNumberOfMessages \
  --region sa-east-1 \
  --query 'Attributes.ApproximateNumberOfMessages' \
  --output text)

echo "📭 Price DLQ: $PRICE_DLQ_COUNT mensagens"

echo ""
if [ "$MANU_DLQ_COUNT" == "0" ] && [ "$MODEL_DLQ_COUNT" == "0" ] && [ "$PRICE_DLQ_COUNT" == "0" ]; then
  echo "✅ TODAS AS DLQS VAZIAS - Pipeline executou sem erros!"
else
  echo "⚠️  DLQs com mensagens - Há erros na pipeline!"
  echo "   Investigar logs das Lambdas"
fi
```

**Resultado Esperado:**
```
📭 Manufacturer DLQ: 0 mensagens
📭 Model DLQ: 0 mensagens
📭 Price DLQ: 0 mensagens

✅ TODAS AS DLQS VAZIAS - Pipeline executou sem erros!
```

### 5.5.2 Se Houver Mensagens em DLQ (Debug)

```bash
export AWS_PROFILE=mutualizo
ACCOUNT_ID="652510808251"

# Receber mensagens da DLQ (máximo 10)
aws sqs receive-message \
  --queue-url https://sqs.sa-east-1.amazonaws.com/$ACCOUNT_ID/fipe-manufacturer-dlq.fifo \
  --max-number-of-messages 10 \
  --region sa-east-1 \
  --output json | jq '.Messages[] | {
    MessageId: .MessageId,
    Body: .Body,
    Attributes: .Attributes
  }'

# Analisar a mensagem
# - MessageId: Identificador único
# - Body: Payload original que falhou
# - Attributes: Timestamps, ApproximateReceiveCount, etc.
```

---

## 5.6: Testes de Cenários Especiais

### 5.6.1 Teste de Rollback (Simular Falha em PRD)

**Objetivo:** Validar que se PRD falha, STG também faz rollback (não fica inconsistente)

```bash
# NOTA: Este teste é MANUAL e requer ação no RDS PRD
# Não fazer em produção!

# 1. Adicionar uma rule temporária no RDS PRD que rejeita conexões
#    (ou remover temporariamente a rule de 172.31.0.0/16)

# 2. Invocar FipeManufacturerLoader
aws lambda invoke --function-name FipeManufacturerLoader --region sa-east-1 response.json

# 3. Monitorar logs de FipeSomaIngestor
aws logs tail /aws/lambda/FipeSomaIngestor --region sa-east-1 --follow

# 4. Esperado:
#    - "Connection failed to RDS PRD"
#    - "Rolling back transaction in STG"
#    - "Erro enviado para DLQ"

# 5. Verificar que nenhum registro foi adicionado em STG ou PRD
SELECT COUNT(*) FROM fipe_vehicle_price;  # Deve ser 0 (ou anterior)

# 6. Restaurar a rule no RDS PRD

# ✅ Sucesso se: STG e PRD permanecerem sincronizados
```

### 5.6.2 Teste de Throttling da FIPE API

**Objetivo:** Validar que exponential backoff funciona quando FIPE API está lenta

```bash
# Este teste é automático (FIPE API pode throttle naturalmente)

# Monitorar logs para padrão de retry:
aws logs tail /aws/lambda/FipeManufacturerLoader --region sa-east-1 | grep -i "retry\|backoff\|throttle"

# Esperado:
# ✅ "Rate limited by FIPE API, retrying after 5s"
# ✅ "Retry 1/3: Waiting 10s..."
# ✅ "Retry 2/3: Waiting 20s..."
# ✅ "Success after retry"
```

### 5.6.3 Teste de Timeout

**Objetivo:** Validar que Lambda timeout está suficientemente longo

```bash
# Verificar timeout configurado em cada Lambda
aws lambda get-function-configuration \
  --function-name FipeManufacturerLoader \
  --region sa-east-1 \
  --query '{FunctionName: FunctionName, Timeout: Timeout, MemorySize: MemorySize}'

# Esperado:
# ✅ FipeManufacturerLoader: Timeout 600s (10 min)
# ✅ FipeModelLoader: Timeout 300s (5 min)
# ✅ FipePriceLoader: Timeout 300s (5 min)
# ✅ FipeSomaIngestor: Timeout 300s (5 min)
```

---

## 5.7: Performance Metrics

### 5.7.1 Medir Tempo Total da Pipeline

```bash
export AWS_PROFILE=mutualizo

# Obter timestamps dos logs
echo "⏱️  Medindo tempo total da pipeline..."

# Tempo de início (FipeManufacturerLoader)
START=$(aws logs describe-log-streams \
  --log-group-name /aws/lambda/FipeManufacturerLoader \
  --region sa-east-1 \
  --query 'logStreams[0].lastEventTimestamp' \
  --output text)

# Tempo de fim (FipeSomaIngestor)
END=$(aws logs describe-log-streams \
  --log-group-name /aws/lambda/FipeSomaIngestor \
  --region sa-east-1 \
  --query 'logStreams[0].lastEventTimestamp' \
  --output text)

echo "Início: $START"
echo "Fim: $END"
echo "Duração: ~$((($END - $START) / 1000))s"
```

**Resultado Esperado:**
```
⏱️  Duração total: ~20-30 segundos
   - FipeManufacturerLoader: ~5-10s (API calls)
   - FipeModelLoader: ~5-10s (SQS processing)
   - FipePriceLoader: ~5-10s (SQS processing)
   - FipeSomaIngestor: ~5-10s (DB inserts)
```

### 5.7.2 Memory Usage

```bash
export AWS_PROFILE=mutualizo

# Verificar máximo de memória usada
aws logs filter-log-events \
  --log-group-name /aws/lambda/FipeSomaIngestor \
  --region sa-east-1 \
  --filter-pattern "Max Memory Used" \
  --query 'events[0].message'

# Esperado:
# ✅ Max Memory Used: < 200 MB (configurado: 256 MB)
```

### 5.7.3 Data Transfer Cost Estimate

```bash
# Estimativa de custo de dados

# STG (público): ~2400 registros * 100 bytes = 240 KB por execução
# PRD (peering): ~2400 registros * 100 bytes = 240 KB por execução

# Custo mensal (1 execução/mês):
# STG: 0.24 MB * $0.02 = $0.005/mês
# PRD: 0.24 MB * $0.02 = $0.005/mês
# Total: ~$0.01/mês

echo "💰 Custo mensal de data transfer: ~$0.01"
```

---

## 5.8: Checklist de Conclusão FASE 5

- [ ] ✅ Pré-requisitos validados (Lambdas, SQS, endpoints)
- [ ] ✅ Dados preparados (queues limpas, row counts iniciais capturados)
- [ ] ✅ FipeManufacturerLoader invocado manualmente
- [ ] ✅ Pipeline completa executada (todas as 4 Lambdas)
- [ ] ✅ Logs analisados (sem erros críticos)
- [ ] ✅ Dados injetados em RDS STG
- [ ] ✅ Dados injetados em RDS PRD
- [ ] ✅ Row counts iguais em STG e PRD (consistency validada)
- [ ] ✅ Todas as 3 DLQs vazias (zero mensagens)
- [ ] ✅ Performance dentro do esperado (20-30s total)
- [ ] ✅ Teste de rollback passou (se executado)
- [ ] ✅ Documentação de resultados realizada

---

## 5.9: Documentar Resultados

Ao completar todos os testes, criar um arquivo `PHASE-5-RESULTS.txt`:

```
TESTE E2E - RESULTADOS FINAIS
=============================
Data: 2026-05-20
Duration: XXm XXs

PIPELINE EXECUTION:
✅ FipeManufacturerLoader: SUCCESS (Xs)
✅ FipeModelLoader: SUCCESS (Xs)
✅ FipePriceLoader: SUCCESS (Xs)
✅ FipeSomaIngestor: SUCCESS (Xs)

DATA CONSISTENCY:
✅ STG Row Count: 2400
✅ PRD Row Count: 2400
✅ Consistency: VERIFIED (equal counts)

DLQ STATUS:
✅ Manufacturer DLQ: 0 messages
✅ Model DLQ: 0 messages
✅ Price DLQ: 0 messages

PERFORMANCE:
⏱️  Total Pipeline Time: ~25s
💾 Memory Usage: < 200MB
💰 Data Transfer Cost: $0.01/month

SECURITY CHECKS:
✅ VPC Peering PRD: ACTIVE
✅ RDS STG Public Access: Whitelisted (189.36.254.27/32)
✅ Dual-Write: Transactional (ACID)

CONCLUSION:
✅ PHASE 5 PASSED - Ready for PHASE 6 (Cleanup)
```

---

## 5.10: Próximas Ações

Se FASE 5 passou ✅:
→ Proceder para **FASE 6: Limpeza** (deletar infraestrutura antiga)

Se FASE 5 falhou ❌:
→ Investigar logs em `/aws/lambda/*`
→ Verificar conectividade RDS via security groups
→ Usar snapshots de rollback se necessário
→ Contactar suporte AWS se persistir

---

**Status:** 🔄 PENDENTE EXECUÇÃO  
**Atualizado em:** 2026-05-20  
**Próximo:** FASE 6 - Limpeza (após FASE 5 passar ✅)
