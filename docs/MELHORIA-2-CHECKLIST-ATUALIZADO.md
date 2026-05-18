# CHECKLIST DETALHADO: Melhoria 2 - Multi-Region Lambda Architecture (sa-east-1)

**Versão:** 2026-05-15  
**Status:** Pronto para Implementação  
**Tempo Estimado:** 16-20 horas de trabalho  
**Abordagem:** Incremental (STG → PRD)

---

## FASE PREPARAÇÃO

### 1. Setup Inicial
- [ ] Ler especificação: `docs/superpowers/specs/2026-05-15-multi-region-lambda-architecture-design.md`
- [ ] Criar branch: `git checkout -b feature/multi-region-sa-east-1`
- [ ] Validar acesso AWS a sa-east-1: `aws ec2 describe-regions --region-names sa-east-1`
- [ ] Notificar team: "Começando migração Multi-Region (STG → PRD, duração: 3-5 dias)"

---

## FASE STG (STAGING) - us-east-2 ↔ sa-east-1

### 2. ETAPA 1: Preparar Infraestrutura Base em sa-east-1

#### 2.1 Criar SQS Queues FIFO em sa-east-1
```bash
# Via AWS CLI ou CDK (recomendado via CDK)
# As filas devem ser criadas como FIFO (First-In-First-Out)

# Queues a criar:
# - fipe-manufacturer-queue-stg.fifo
# - fipe-model-queue-stg.fifo
# - fipe-price-queue-stg.fifo
# - fipe-soma-webhook-queue-stg.fifo
# E correspondentes DLQs
```

- [ ] Modificar `fipe_api_stack.py` para criar queues em sa-east-1:
  ```python
  # Adicionar parâmetro de região ao stack
  # Criar queues com fifo=True
  ```
- [ ] Executar CDK diff: `cdk diff --context vpc_id=... --context allowed_ip=...`
- [ ] Revisar mudanças (apenas SQS FIFO, nada mais)
- [ ] Commit: `git commit -am "CDK: Criar SQS FIFO queues em sa-east-1 para STG"`

#### 2.2 Rebuild Lambda Layer em sa-east-1
```bash
make prepare-layers
# OU
./create-fipe-api-layer.sh
```

- [ ] Layer preparada com sucesso
- [ ] Validar: `ls -la fipe_api_layer.zip`

#### 2.3 Criar EventBridge Rule em sa-east-1
```python
# Adicionar ao CDK:
# - EventBridge Rule: "FipeManufacturerMonthlyRule-stg"
# - Schedule: "0 1 4 * *" (4º dia do mês, 01:00 UTC)
# - Region: sa-east-1
```

- [ ] CDK modificado para criar EventBridge em sa-east-1
- [ ] Commit: `git commit -am "CDK: Adicionar EventBridge Rule em sa-east-1"`

#### 2.4 Criar Security Group para Ingestor em sa-east-1
```python
# Adicionar ao CDK:
# - Security Group em VPC default sa-east-1
# - Nome: FipeSomaIngestorSecurityGroup-stg
# - Egress: Tudo permitido (para RDS cross-region)
```

- [ ] Security Group criado no CDK
- [ ] Commit: `git commit -am "CDK: Criar Security Group para Ingestor em sa-east-1"`

#### 2.5 Deploy Infraestrutura Base em STG
```bash
# Deploy com contexto para sa-east-1
cdk deploy --region sa-east-1 \
  --context vpc_id=vpc-xxxxx \
  --context allowed_ip=123.456.789.0
```

- [ ] Deploy iniciado
- [ ] Aguardar conclusão (~5-10 minutos)
- [ ] ✅ Deployment bem-sucedido (sem erros)
- [ ] Validar no console AWS:
  - [ ] SQS Queues criadas em sa-east-1 (FIFO)
  - [ ] EventBridge Rule criada
  - [ ] Security Group criado
- [ ] Documentar URLs/ARNs de recursos criados
- [ ] Commit: `git commit -am "Infra: Etapa 1 STG completa - recursos em sa-east-1"`

---

### 3. ETAPA 2: Deploy Lambdas SEM VPC em sa-east-1

#### 3.1 Refatorar fipe_api_stack.py para Separar Lambdas
```python
# Criar 2 classes de Lambdas:
# 1. LambdasWithoutVPC: FipeManufacturerLoader, FipeModelLoader, FipePriceLoader
# 2. LambdasWithVPC: FipeSomaIngestor

# Lambdas SEM VPC: 
#   - Sem subnet selection
#   - Sem security group
#   - Acesso direto à internet (para FIPE API)

# Lambdas COM VPC:
#   - Com VPC default sa-east-1
#   - Com security group
#   - Para acesso RDS via peering
```

- [ ] CDK refatorado para 2 categorias
- [ ] Commit: `git commit -am "CDK: Refatorar Lambdas em categorias SEM/COM VPC"`

#### 3.2 Deploy Lambdas SEM VPC
```bash
cdk deploy --region sa-east-1 \
  --context deploy_lambdas_without_vpc=true \
  --context vpc_id=... --context allowed_ip=...
```

- [ ] Deploy iniciado
- [ ] Aguardar conclusão
- [ ] ✅ Lambdas criadas em sa-east-1:
  - [ ] FipeManufacturerLoader-stg (sem VPC)
  - [ ] FipeModelLoader-stg (sem VPC)
  - [ ] FipePriceLoader-stg (sem VPC)

#### 3.3 Testes Manuais - Lambdas SEM VPC
```bash
# Invocar FipeManufacturerLoader manualmente
aws lambda invoke \
  --function-name FipeManufacturerLoader-stg \
  --region sa-east-1 \
  response.json

# Validar resposta
cat response.json
# Esperado: {"statusCode": 200} ou sucesso

# Ver logs
aws logs tail /aws/lambda/FipeManufacturerLoader-stg --follow --region sa-east-1
```

- [ ] Lambda executou sem erros
- [ ] Logs mostram "INFO" (sucesso)
- [ ] Validar FIPE API access (log deve mostrar requisição bem-sucedida)
- [ ] Validar SQS message delivery:
  ```bash
  aws sqs get-queue-attributes \
    --queue-url https://sqs.sa-east-1.amazonaws.com/xxx/fipe-manufacturer-queue-stg.fifo \
    --attribute-names ApproximateNumberOfMessages \
    --region sa-east-1
  ```
- [ ] ✅ Mensagens na fila (> 0)
- [ ] Documentar: "✅ Etapa 2 PASSED - Lambdas SEM VPC funcionando"
- [ ] Commit: `git commit -am "Test: Etapa 2 STG - Lambdas SEM VPC validadas"`

---

### 4. ETAPA 3: Configurar VPC Peering (sa-east-1 ↔ us-east-2)

#### 4.1 Criar VPC Peering Connection
```bash
# Via AWS CLI
aws ec2 create-vpc-peering-connection \
  --vpc-id vpc-sa-east-1-default \
  --peer-vpc-id vpc-us-east-2-stg \
  --peer-region us-east-2 \
  --region sa-east-1
```

- [ ] Peering connection criada
- [ ] Validar status: `aws ec2 describe-vpc-peering-connections --region sa-east-1`
- [ ] Status deve ser "pending-acceptance"

#### 4.2 Aceitar Peering Connection em us-east-2
```bash
# Via AWS CLI
aws ec2 accept-vpc-peering-connection \
  --vpc-peering-connection-id pcx-xxxxx \
  --region us-east-2
```

- [ ] Peering connection aceita
- [ ] Validar status: deve estar "active"

#### 4.3 Atualizar Route Tables em us-east-2
```bash
# Adicionar rota em us-east-2 para sa-east-1 CIDR (10.0.0.0/16)
# Target: Peering connection

aws ec2 create-route \
  --route-table-id rtb-us-east-2 \
  --destination-cidr-block 10.0.0.0/16 \
  --vpc-peering-connection-id pcx-xxxxx \
  --region us-east-2
```

- [ ] Rota criada
- [ ] Validar: `aws ec2 describe-route-tables --route-table-ids rtb-us-east-2 --region us-east-2`

#### 4.4 Atualizar RDS Security Group em us-east-2
```bash
# Adicionar ingress rule no RDS security group
# Source: sa-east-1 default VPC CIDR (10.0.0.0/16)
# Port: 5432

aws ec2 authorize-security-group-ingress \
  --group-id sg-rds-us-east-2 \
  --protocol tcp \
  --port 5432 \
  --cidr 10.0.0.0/16 \
  --region us-east-2
```

- [ ] Ingress rule adicionada
- [ ] Validar: `aws ec2 describe-security-groups --group-ids sg-rds-us-east-2 --region us-east-2`

#### 4.5 Testes de Conectividade Peering
```bash
# De um EC2 em sa-east-1, testar conectividade com RDS em us-east-2
# Ou via Lambda

psql -h fipedata-cluster-stg.xxxxx.us-east-2.rds.amazonaws.com \
  -p 5432 \
  -U postgres \
  -d fipedata \
  -c "SELECT 1;"
```

- [ ] ✅ Conexão bem-sucedida
- [ ] Latência aceitável (< 200ms esperado)
- [ ] Documentar: "✅ Etapa 3 PASSED - VPC Peering ativo"
- [ ] Commit: `git commit -am "Network: Etapa 3 STG - VPC Peering configurado (sa-east-1 ↔ us-east-2)"`

---

### 5. ETAPA 4: Deploy Lambda Ingestor COM VPC em sa-east-1

#### 5.1 Refatorar CDK para Ingestor COM VPC
```python
# Adicionar ao CDK:
# - FipeSomaIngestor-stg COM VPC default sa-east-1
# - Security Group: FipeSomaIngestorSecurityGroup-stg
# - Environment variables:
#   - RDS_HOST: fipedata-cluster-stg.xxxxx.us-east-2.rds.amazonaws.com
#   - RDS_PORT: 5432
#   - RDS_DATABASE: fipedata
#   - RDS_USER: postgres
```

- [ ] CDK modificado
- [ ] Commit: `git commit -am "CDK: Adicionar FipeSomaIngestor COM VPC em sa-east-1"`

#### 5.2 Deploy Ingestor
```bash
cdk deploy --region sa-east-1 \
  --context deploy_lambdas_with_vpc=true \
  --context vpc_id=... --context allowed_ip=...
```

- [ ] Deploy iniciado
- [ ] ✅ FipeSomaIngestor-stg criada com VPC

#### 5.3 Testes Manuais - Ingestor COM VPC
```bash
# Criar mensagem de teste (preço)
aws sqs send-message \
  --queue-url https://sqs.sa-east-1.amazonaws.com/xxx/fipe-price-queue-stg.fifo \
  --message-body '{"price": 15000, "vehicle_id": 1}' \
  --message-group-id "test-group" \
  --region sa-east-1

# Invocar Ingestor manualmente
aws lambda invoke \
  --function-name FipeSomaIngestor-stg \
  --region sa-east-1 \
  response.json
```

- [ ] Lambda executou com sucesso
- [ ] Logs mostram RDS connection OK (sem erros de conexão)
- [ ] Validar dados no RDS:
  ```bash
  psql -h fipedata-cluster-stg.xxxxx.us-east-2.rds.amazonaws.com \
    -U postgres -d fipedata -c "SELECT COUNT(*) FROM fipe_vehicle_price;"
  ```
- [ ] ✅ Dados inseridos (COUNT > 0)
- [ ] Documentar: "✅ Etapa 4 PASSED - Ingestor COM VPC funcionando"
- [ ] Commit: `git commit -am "Test: Etapa 4 STG - FipeSomaIngestor com VPC validado"`

---

### 6. ETAPA 5: Validação E2E em STG

#### 6.1 Teste End-to-End Completa
```bash
# 1. Invocar FipeManufacturerLoader manualmente
aws lambda invoke \
  --function-name FipeManufacturerLoader-stg \
  --region sa-east-1 \
  response.json

# 2. Aguardar ModelLoader ser disparada (via SQS trigger)
# Verificar logs:
aws logs tail /aws/lambda/FipeModelLoader-stg --region sa-east-1

# 3. Aguardar PriceLoader
aws logs tail /aws/lambda/FipePriceLoader-stg --region sa-east-1

# 4. Aguardar Ingestor
aws logs tail /aws/lambda/FipeSomaIngestor-stg --region sa-east-1
```

- [ ] Manufacturer logs: sucesso
- [ ] Model logs: sucesso
- [ ] Price logs: sucesso
- [ ] Ingestor logs: sucesso (dados inseridos no RDS)

#### 6.2 Validar Integridade de Dados
```bash
# Verificar dados no RDS STG
psql -h fipedata-cluster-stg.xxxxx.us-east-2.rds.amazonaws.com \
  -U postgres -d fipedata << EOF
SELECT COUNT(*) as total_prices FROM fipe_vehicle_price;
SELECT COUNT(DISTINCT manufacturer_id) as unique_manufacturers FROM fipe_vehicle_price;
SELECT COUNT(DISTINCT model_id) as unique_models FROM fipe_vehicle_price;
EOF
```

- [ ] ✅ Total de preços > 0
- [ ] ✅ Fabricantes > 0
- [ ] ✅ Modelos > 0
- [ ] ✅ Sem duplicatas (validar via DISTINCT)

#### 6.3 Monitorar CloudWatch
```bash
# Monitorar latência cross-region
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Duration \
  --dimensions Name=FunctionName,Value=FipeSomaIngestor-stg \
  --start-time 2026-05-15T00:00:00Z \
  --end-time 2026-05-15T23:59:59Z \
  --period 3600 \
  --statistics Average \
  --region sa-east-1
```

- [ ] Latência aceitável (esperado: 500ms-2000ms com cross-region)
- [ ] DLQs vazias:
  ```bash
  aws sqs get-queue-attributes \
    --queue-url https://sqs.sa-east-1.amazonaws.com/xxx/fipe-manufacturer-dlq-stg.fifo \
    --attribute-names ApproximateNumberOfMessages \
    --region sa-east-1
  ```
- [ ] ✅ DLQs = 0 (nenhuma falha)

#### 6.4 Documentação STG Completo
- [ ] Documentar: "✅ ETAPA 5 STG PASSED - Pipeline E2E validada"
- [ ] Documentar latência observada
- [ ] Commit: `git commit -am "Validation: Etapa 5 STG - End-to-end test passed"`

#### 6.5 Go/No-Go Decision para PRD
- [ ] ✅ Etapa 1 PASSED
- [ ] ✅ Etapa 2 PASSED
- [ ] ✅ Etapa 3 PASSED
- [ ] ✅ Etapa 4 PASSED
- [ ] ✅ Etapa 5 PASSED

**Decisão:**
- [ ] **GO** para PRD (tudo funcionando perfeitamente)
  - OU
- [ ] **NO-GO** para PRD (alguma etapa falhou, investigar)

---

## FASE PRD (PRODUÇÃO) - us-east-1 ↔ sa-east-1

### 7. REPETIR ETAPAS 1-5 EM PRD

#### 7.1-7.5 Etapas 1-5 em PRD
**Repetir exatamente o mesmo processo que STG, mas:**
- Region: sa-east-1 (mesmo)
- RDS target: us-east-1 (PRD) em vez de us-east-2 (STG)
- VPC Peering: sa-east-1 ↔ us-east-1
- Queue names: com "-prd" em vez de "-stg"

Mudanças principais:
```bash
# Etapa 3: Peering para us-east-1
aws ec2 create-vpc-peering-connection \
  --vpc-id vpc-sa-east-1-default \
  --peer-vpc-id vpc-us-east-1-prd \
  --peer-region us-east-1 \
  --region sa-east-1

# Etapa 4: RDS_HOST apontando para us-east-1
# RDS_HOST: fipedata-cluster-prd.xxxxx.us-east-1.rds.amazonaws.com
```

- [ ] Etapa 1 PRD: Infraestrutura base criada
- [ ] Etapa 2 PRD: Lambdas SEM VPC validadas
- [ ] Etapa 3 PRD: VPC Peering sa-east-1 ↔ us-east-1 ativo
- [ ] Etapa 4 PRD: Ingestor COM VPC validado
- [ ] Etapa 5 PRD: E2E validada, dados no RDS us-east-1
- [ ] Commit: `git commit -am "Prod: Etapas 1-5 PRD completas - Multi-region ativo"`

---

## FASE LIMPEZA

### 8. Descomissionar Arquitetura Antiga

#### 8.1 Após 1-2 Semanas Estável em PRD

```bash
# Deletar infraestrutura antiga em us-east-1:
# - Lambdas antigas (FipeManufacturerLoader-prd, etc em us-east-1)
# - SQS antigas em us-east-1
# - EventBridge Rule antiga
```

- [ ] Backup/documentação da configuração antiga
- [ ] Deletar Lambdas antigas
- [ ] Deletar SQS antigas
- [ ] Deletar EventBridge Rule antiga
- [ ] Commit: `git commit -am "Cleanup: Remover infraestrutura antiga em us-east-1"`

---

## PULL REQUEST E RELEASE

### 9. Criar PR e Merge
```bash
gh pr create --title "Multi-Region Architecture with sa-east-1" \
  --body "Lambdas migradas para sa-east-1 com VPC Peering para RDS cross-region"

# Após review:
gh pr merge <PR_NUMBER>
```

- [ ] PR criado
- [ ] ✅ Aprovado
- [ ] ✅ Merged

### 10. Create Release Tag
```bash
git tag -a v1.2.0-multi-region -m "Multi-Region Architecture: Lambdas in sa-east-1"
git push origin v1.2.0-multi-region
```

- [ ] Tag criada e pushed

### 11. Notificar Team
```
✅ MIGRAÇÃO MULTI-REGION COMPLETA

Arquitetura:
- Lambdas: sa-east-1 (FIPE API local)
- RDS STG: us-east-2
- RDS PRD: us-east-1
- Conectividade: VPC Peering

Performance:
- Latência esperada: 100-200ms (peering)
- Throughput: ilimitado (FIFO)

Release: v1.2.0-multi-region
```

- [ ] Team notificado

---

## RESUMO DE COMMITS

```
1. CDK: Criar SQS FIFO queues em sa-east-1 para STG
2. CDK: Adicionar EventBridge Rule em sa-east-1
3. CDK: Criar Security Group para Ingestor em sa-east-1
4. Infra: Etapa 1 STG completa - recursos em sa-east-1
5. CDK: Refatorar Lambdas em categorias SEM/COM VPC
6. Test: Etapa 2 STG - Lambdas SEM VPC validadas
7. Network: Etapa 3 STG - VPC Peering configurado (sa-east-1 ↔ us-east-2)
8. CDK: Adicionar FipeSomaIngestor COM VPC em sa-east-1
9. Test: Etapa 4 STG - FipeSomaIngestor com VPC validado
10. Validation: Etapa 5 STG - End-to-end test passed
11. Prod: Etapas 1-5 PRD completas - Multi-region ativo
12. Cleanup: Remover infraestrutura antiga em us-east-1
```

---

**Tempo Total Estimado:** 16-20 horas  
**Críticos:** VPC Peering (Etapa 3), Cross-region RDS access

