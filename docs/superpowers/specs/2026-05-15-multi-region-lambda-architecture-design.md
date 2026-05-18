# Migração Multi-Region com Arquitetura Hybrid para Lambdas

**Data:** 2026-05-15  
**Autor:** Alexandre Defendi  
**Status:** Design Aprovado

---

## 1. Visão Geral

### Motivador
A ONG que gerencia a FIPE bloqueia acesso de IPs internacionais. As Lambdas atualmente em us-east-1 não conseguem fazer requisições à FIPE API. A solução é executar as Lambdas em São Paulo (sa-east-1), onde o IP é aceito.

### Objetivo
Migrar a infraestrutura de processamento (Lambdas + SQS + EventBridge) para sa-east-1 enquanto mantém os bancos de dados em us-east-1 (PRD) e us-east-2 (STG) inalterados, usando uma arquitetura hybrid que otimiza custo, performance e segurança.

### Escopo
- Mover Lambdas para sa-east-1 (com abordagem hybrid)
- Mover SQS Queues para sa-east-1
- Mover EventBridge para sa-east-1
- Configurar VPC Peering para acesso RDS cross-region
- Manter RDS em us-east-2 (STG) e us-east-1 (PRD)
- Dados permanecem inalterados
- Ambientes impactados: **STG → PRD** (incremental)

---

## 2. Arquitetura Hybrid

### Estratégia: Duas Categorias de Lambdas

A arquitetura separa Lambdas em duas categorias com diferentes necessidades de networking:

#### Categoria A: Lambdas SEM VPC (Acessam FIPE API)
```
FipeManufacturerLoader-stg/prd
FipeModelLoader-stg/prd
FipePriceLoader-stg/prd
```

**Características:**
- Executam em sa-east-1 **SEM VPC**
- Fazem requisições HTTP à FIPE API
- Enviam mensagens para SQS em sa-east-1
- Não acessam RDS (sem necessidade de VPC)
- Execução mais rápida (sem overhead VPC)
- Custo reduzido

**Fluxo:**
```
FIPE API (São Paulo) ← HTTP Request ← Lambda (sa-east-1, sem VPC)
                                         ↓
                                      SQS Manufacturer (sa-east-1)
```

#### Categoria B: Lambda COM VPC (Acessa RDS)
```
FipeSomaIngestor-stg/prd
```

**Características:**
- Executa em sa-east-1 **COM VPC** (default)
- Consome mensagens de SQS em sa-east-1
- Acessa RDS em us-east-2 (STG) ou us-east-1 (PRD) via VPC Peering
- RDS permanece privada (sem public endpoint)
- Segurança otimizada

**Fluxo:**
```
SQS (sa-east-1) ← Consume ← Lambda (sa-east-1, VPC default)
                                  ↓
                            VPC Peering (sa-east-1 ↔ us-east-2/us-east-1)
                                  ↓
                            RDS (us-east-2/us-east-1, privada)
```

### Benefícios da Arquitetura Hybrid

| Aspecto | Benefício |
|--------|-----------|
| **Custo** | Lambdas A não usam VPC (sem charges); apenas Ingestor usa |
| **Performance** | Lambdas A executam mais rápido (sem VPC overhead) |
| **Segurança** | RDS permanece privada (VPC Peering, sem public endpoint) |
| **Simplicidade** | Apenas uma Lambda precisa de VPC; outras são stateless |
| **Escalabilidade** | Categorias independentes podem ser escaladas separadamente |

---

## 3. Infraestrutura Detalhada

### Em sa-east-1 (Nova Região)

#### 3.1 SQS Queues
```
fipe-manufacturer-queue-stg/prd (sa-east-1)
├─ fipe-manufacturer-dlq-stg/prd
fipe-model-queue-stg/prd (sa-east-1)
├─ fipe-model-dlq-stg/prd
fipe-price-queue-stg/prd (sa-east-1)
├─ fipe-price-dlq-stg/prd
fipe-soma-queue-stg/prd (sa-east-1)
├─ fipe-soma-dlq-stg/prd
```

**Configuração:**
- Visibility timeout: 600s
- Retention: 4 days (main queues), 14 days (DLQs)
- Região: sa-east-1

#### 3.2 Lambda Layer
- Python 3.12 (da migração anterior)
- Buildado em sa-east-1 com `create-fipe-api-layer.sh`
- Inclui: boto3, requests, psycopg2-binary, aws-lambda-powertools, etc.

#### 3.3 EventBridge Rule
```
FipeManufacturerMonthlyRule-stg/prd (sa-east-1)
```
- Schedule: `0 1 4 * *` (4º dia do mês, 01:00 UTC)
- Target: FipeManufacturerLoader-stg/prd em sa-east-1
- Ação: Invocar Lambda automaticamente

#### 3.4 VPC Default (sa-east-1)
- Security Group para FipeSomaIngestor
  - Egress: Tudo permitido (para RDS cross-region)
  - Ingress: Não necessário
- Subnets: Já existentes na VPC default
- Internet Gateway: Já existe (para acesso FIPE API das Lambdas sem VPC)

#### 3.5 Lambdas

**Lambdas SEM VPC:**
```
FipeManufacturerLoader-stg/prd
- Runtime: Python 3.12
- Memory: 256MB
- Timeout: 10 min (para múltiplas requisições à FIPE)
- Layer: fipe-api-layer (sa-east-1)
- VPC: Nenhuma
- Env vars: SQS_OUTPUT_URL (manufacturer queue em sa-east-1)
```

```
FipeModelLoader-stg/prd
- Runtime: Python 3.12
- Memory: 256MB
- Timeout: 5 min
- Layer: fipe-api-layer (sa-east-1)
- VPC: Nenhuma
- Env vars: SQS_INPUT_URL (manufacturer queue), SQS_OUTPUT_URL (model queue)
```

```
FipePriceLoader-stg/prd
- Runtime: Python 3.12
- Memory: 256MB
- Timeout: 5 min
- Layer: fipe-api-layer (sa-east-1)
- VPC: Nenhuma
- Env vars: SQS_INPUT_URL (model queue), SQS_OUTPUT_URL (price queue)
```

**Lambda COM VPC:**
```
FipeSomaIngestor-stg/prd
- Runtime: Python 3.12
- Memory: 256MB
- Timeout: 5 min
- Layer: fipe-api-layer (sa-east-1)
- VPC: VPC default (sa-east-1)
- Security Group: FipeIngestorSG-stg/prd
- Env vars:
  - SQS_INPUT_URL (price queue em sa-east-1)
  - RDS_HOST (us-east-2 para STG, us-east-1 para PRD)
  - RDS_PORT: 5432
  - RDS_DATABASE: fipedata
  - RDS_USER: postgres
  - RDS_SECRET_ARN: (mesmo de antes, via Secrets Manager)
```

### Em us-east-2 (STG) e us-east-1 (PRD)

#### 3.6 VPC Peering

**STG (us-east-2 ↔ sa-east-1):**
```
Peering Connection: sa-east-1-vpc-default ↔ us-east-2-fipe-vpc
- Status: Active
- Route Table (us-east-2): 10.0.0.0/8 (sa-east-1 CIDR) → Peering
```

**PRD (us-east-1 ↔ sa-east-1):**
```
Peering Connection: sa-east-1-vpc-default ↔ us-east-1-fipe-vpc
- Status: Active
- Route Table (us-east-1): 10.0.0.0/8 (sa-east-1 CIDR) → Peering
```

#### 3.7 RDS Security Groups

**STG (us-east-2):**
```
Ingress Rule Adicional:
- Source: sa-east-1 VPC default CIDR (10.0.0.0/16 ou específico)
- Port: 5432
- Protocol: TCP
- Description: Allow Peering from sa-east-1
```

**PRD (us-east-1):**
```
Ingress Rule Adicional:
- Source: sa-east-1 VPC default CIDR (10.0.0.0/16 ou específico)
- Port: 5432
- Protocol: TCP
- Description: Allow Peering from sa-east-1
```

#### 3.8 RDS (Sem Mudanças)
- Engine: PostgreSQL Aurora 15.15
- Credenciais: Mesmas (via Secrets Manager)
- Public endpoint: NÃO (continua privada)
- Backup: Inalterado

---

## 4. Componentes que Serão Tocados

### Arquivos CDK

| Arquivo | Mudança | Justificativa |
|---------|---------|---------------|
| `fipe_api_stack.py` | Refatorar em 2 classes | Separar Lambdas sem VPC das com VPC |
| `fipe_data_stack.py` | Adicionar VPC Peering, RDS SG rules | Permitir tráfego cross-region |
| `app.py` | Adicionar support para sa-east-1 | Permitir deploy em múltiplas regiões |

### GitHub Actions Workflows

| Arquivo | Mudança |
|---------|---------|
| `.github/workflows/deploy-development.yml` | Remover (DEV descontinuado) ou converter para sa-east-1 |
| `.github/workflows/deploy-stage.yml` | Adicionar steps para deploy em sa-east-1 |
| `.github/workflows/deploy-production.yml` | Adicionar steps para deploy em sa-east-1 |

### Scripts de Build

| Arquivo | Mudança |
|---------|---------|
| `create-fipe-api-layer.sh` | Nenhuma mudança (reutilizar em sa-east-1) |
| `makefile.txt` | Adicionar targets para sa-east-1 deploy |

### Configuração CDK

| Arquivo | Mudança |
|---------|---------|
| `cdk.json` | Adicionar context vars para sa-east-1 |
| `requirements.txt` | Nenhuma mudança (já atualizado em melhoria anterior) |
| `fipe_api_layer/requirements.txt` | Nenhuma mudança (já atualizado em melhoria anterior) |

---

## 5. Plano de Migração (Incremental)

### Fase 1: Staging (us-east-2 ← sa-east-1)

**Etapa 1: Preparação em sa-east-1 (~30 min)**
- Criar SQS Queues (Manufacturer, Model, Price + DLQs) em sa-east-1
- Criar EventBridge Rule em sa-east-1
- Preparar Lambda layer em sa-east-1
- Criar Security Group para Ingestor (VPC default sa-east-1)
- Deploy de CDK stack (infraestrutura base)

**Etapa 2: Deploy de Lambdas sem VPC (~45 min)**
- Deploy FipeManufacturerLoader-stg em sa-east-1 (sem VPC)
- Deploy FipeModelLoader-stg em sa-east-1 (sem VPC)
- Deploy FipePriceLoader-stg em sa-east-1 (sem VPC)
- Testes manuais: Invocar FipeManufacturerLoader, validar acesso FIPE API
- Validar SQS message delivery

**Etapa 3: VPC Peering e RDS Access (~30 min)**
- Criar VPC Peering: sa-east-1 (default) ↔ us-east-2 (STG)
- Atualizar route tables em us-east-2
- Atualizar RDS Security Group em us-east-2 (ingress rule para Peering)
- Teste de conectividade: psql de Lambda em sa-east-1 para RDS em us-east-2

**Etapa 4: Deploy de Lambda Ingestor com VPC (~45 min)**
- Deploy FipeSomaIngestor-stg em sa-east-1 (com VPC default)
- Configurar variáveis de ambiente (RDS_HOST, etc)
- Testes manuais: Invocar com mensagem de teste, validar insert no RDS

**Etapa 5: Validação Completa (~60 min)**
- Teste end-to-end: Pipeline completa (Manufacturer → Ingestor)
- Validar que dados estão em RDS
- Verificar zero mensagens em DLQs
- Monitorar CloudWatch logs e metrics
- Validar latência cross-region

**Total Fase 1: ~3.5 horas**

---

### Fase 2: Produção (us-east-1 ← sa-east-1)

Repetir Fase 1 com:
- VPC Peering: sa-east-1 ↔ us-east-1 (em vez de us-east-2)
- RDS em us-east-1 (em vez de us-east-2)
- Mesmo plano de validação

**Total Fase 2: ~3.5 horas**

---

### Critérios de Progressão Entre Etapas

| Etapa | Critério de Sucesso | Falha → Ação |
|-------|-------------------|------------|
| 1 | Infraestrutura criada sem erros | Revisar CDK logs, corrigir template |
| 2 | Lambdas conseguem acessar FIPE, mensagens em SQS | Validar IAM, testar FIPE API access |
| 3 | Peering ativo, conectividade RDS validada | Verificar route tables, SG rules |
| 4 | Ingestor conecta ao RDS, insere dados | Validar connection string, credentials |
| 5 | Pipeline completa, 0 DLQ messages | Investigar logs, testar manualmente |

---

## 6. Validação e Testes

### Testes Automatizados

#### 6.1 CDK Validation
```bash
cdk diff --context vpc_id=<DEFAULT_VPC_SA> \
         --context allowed_ip=<SA_REGION_IP>
```
- Validar que CloudFormation template está correto
- Garantir que SQS, Lambdas, Peering estão definidos
- Verificar IAM policies

#### 6.2 Lambda Layer Validation
```bash
./create-fipe-api-layer.sh
```
- Rebuild da layer com Python 3.12
- Validar que todos os packages instalam corretamente em sa-east-1

#### 6.3 Unit Tests
```bash
python -m pytest tests/
```
- Validar lógica das Lambdas
- Testar parsing de respostas FIPE API
- Testar formatação de SQS messages

#### 6.4 Lint com Ruff
```bash
ruff check .
ruff format --check .
```
- Validar qualidade do código
- Conformidade com padrões

### Testes Manuais

#### 6.5 Teste de Acesso à FIPE API
```bash
aws lambda invoke --function-name FipeManufacturerLoader-stg \
  --region sa-east-1 response.json
```
- Invocar Lambda manualmente
- Validar acesso à FIPE API (sem bloqueio de IP)
- Check CloudWatch logs para sucesso

#### 6.6 Teste de SQS
```bash
aws sqs receive-message --queue-url <QUEUE_URL> --region sa-east-1
```
- Validar que mensagens chegam nas filas
- Testar comunicação intra-región (sa-east-1)

#### 6.7 Teste de VPC Peering e RDS
```bash
# De dentro de Lambda ou EC2 em sa-east-1:
psql -h <RDS_ENDPOINT_US_EAST_2> -U postgres -d fipedata -c "SELECT 1;"
```
- Validar conectividade cross-region
- Testar latência (esperado: 100-200ms)
- Validar credenciais via Secrets Manager

#### 6.8 Teste de Ingestão
```bash
aws lambda invoke --function-name FipeSomaIngestor-stg \
  --payload '{"Records":[...]}' \
  --region sa-east-1 response.json
```
- Invocar Ingestor com mensagem de teste
- Validar que dados são inseridos no RDS
- Check logs para sucesso

#### 6.9 Teste End-to-End
1. Invocar FipeManufacturerLoader manualmente
2. Validar que Model Loader é disparado (via SQS trigger)
3. Validar que Price Loader é disparado
4. Validar que Ingestor é disparado
5. Verificar dados em RDS (us-east-2 para STG)
6. Validar integridade (sem duplicatas, valores corretos)

#### 6.10 Monitoramento de DLQs
```bash
aws sqs get-queue-attributes --queue-url <DLQ_URL> \
  --attribute-names ApproximateNumberOfMessages \
  --region sa-east-1
```
- Validar que nenhuma DLQ tem mensagens
- Se houver: investigar e corrigir

#### 6.11 Testes de Latência
- Monitor CloudWatch Logs Insights:
  - Lambda duration (esperado: 500ms-2s)
  - RDS connection time (esperado: 100-200ms)
  - SQS message delivery

---

### Critérios de Sucesso

| Etapa | Teste | Critério |
|-------|-------|----------|
| 2 | Lambdas FIPE API | Requisições bem-sucedidas, mensagens em SQS |
| 3 | Peering + RDS | Conectividade comprovada, latência aceitável |
| 4 | Ingestor + RDS | Dados inseridos, sem erros de conexão |
| 5 | Pipeline E2E | Fluxo completo, 0 DLQ messages, latência OK |

---

## 7. Tratamento de Erros

### Cenário 1: Lambdas não conseguem acessar FIPE API (Etapa 2)

**Sintomas:** Lambda falha com erro de conexão, timeout, ou bloqueio de IP

**Causas Possíveis:**
- IP de sa-east-1 ainda bloqueado pela FIPE
- Lambda não tem permissão de egress
- FIPE API está down

**Ações:**
1. Verificar CloudWatch logs detalhadamente
2. Testar curl de um EC2 em sa-east-1 para FIPE API
3. Validar IAM policy (allow egress)
4. Se IP bloqueado: contactar FIPE ONG para whitelist
5. Alternativa: usar NAT Gateway com IP estático (mais caro)

---

### Cenário 2: VPC Peering não funciona (Etapa 3)

**Sintomas:** Lambda não consegue resolver hostname RDS, timeout, "Name or service not known"

**Causas Possíveis:**
- Peering não está ativa
- Route tables não atualizadas
- RDS Security Group não permite tráfego
- CIDR ranges incorretos

**Ações:**
1. Verificar status do Peering (deve estar "Active")
2. Validar route tables em us-east-2 (deve ter rota para sa-east-1 CIDR)
3. Validar RDS SG (deve ter ingress rule para sa-east-1)
4. Testar conectividade com `nc` ou `psql`
5. Rollback: reverter Peering, continuar debugging

---

### Cenário 3: Ingestor não consegue conectar ao RDS (Etapa 4)

**Sintomas:** Lambda falha com erro de autenticação, timeout, "FATAL: Ident authentication failed"

**Causas Possíveis:**
- Connection string incorreta
- Credentials do Secrets Manager não atualizadas
- RDS não aceita Peering
- IAM permission issue

**Ações:**
1. Validar connection string (hostname, port, database, user)
2. Testar credentials manualmente: `psql -h <endpoint> -U postgres`
3. Verificar IAM policy (secretsmanager:GetSecretValue)
4. Revisar RDS Proxy config (se usar)
5. Usar credentials hardcoded temporariamente para debug

---

### Cenário 4: Pipeline quebra (Etapa 5)

**Sintomas:** Uma ou mais Lambdas falham, mensagens em DLQ, dados incompletos

**Ações:**
1. Identificar qual Lambda falhou (check logs)
2. Aplicar ações específicas (Cenário 1, 2 ou 3)
3. Se erro de lógica: corrigir código, testar com mock
4. Reprocessar mensagens de DLQ após fix
5. Re-executar pipeline completa

---

### Cenário 5: Performance inaceitável (Etapa 5)

**Sintomas:** Lambda duration > 5s, RDS queries lentos, timeout

**Causas Possíveis:**
- Latência de rede cross-region alta
- RDS com pouca capacity
- Query ineficiente
- Connection pooling inadequado

**Ações:**
1. Monitor CloudWatch Logs Insights (Lambda duration, RDS time)
2. Otimizações:
   - Usar RDS Proxy para connection pooling
   - Aumentar RDS capacity
   - Batch inserts
   - Adicionar índices no RDS
3. Se latência inaceitável: considerar replicar RDS para sa-east-1

---

### Rollback Geral

Se múltiplas Etapas falharem:

1. **Manter STG funcionando** (com arquitetura hybrid)
2. **Reverter PRD para arquitetura antiga:**
   - Deletar Lambdas de sa-east-1
   - Deletar SQS de sa-east-1
   - Reativar Lambdas da arquitetura antiga (us-east-1)
   - Deletar VPC Peering
3. **Investigação pós-mortem**
4. **Replanejar** com mudanças

---

## 8. Cronograma e Checkpoints

### Timeline

| Fase | Atividades | Duração | Data Recomendada |
|------|-----------|---------|-----------------|
| STG | Etapas 1-5 | 3.5h | Dia útil, horário comercial |
| Validação | Monitorar, ajustar | 1-2 semanas | Após STG |
| PRD | Etapas 1-5 | 3.5h | Noite ou fim de semana |
| Descomissionar | Deletar infraestrutura antiga | 1h | 2+ semanas após PRD |

### Checkpoints

| Checkpoint | Quando | Owner | Validação |
|-----------|--------|-------|-----------|
| Infraestrutura criada | Após Etapa 1 | DevOps | SQS, EventBridge no console |
| Lambdas FIPE testadas | Após Etapa 2 | QA | Manual invocation, logs |
| Peering ativo | Após Etapa 3 | DevOps | Status, psql test |
| Ingestor funcionando | Após Etapa 4 | QA | Dados no RDS |
| Pipeline E2E OK | Após Etapa 5 | QA | End-to-end test, 0 DLQ |
| Go/No-Go PRD | Antes Etapa 1 (PRD) | Lead | Decisão de prosseguir |

### Critérios de Sucesso Globais

- ✅ Lambdas em sa-east-1 conseguem fazer requisições à FIPE API
- ✅ SQS em sa-east-1 recebe e distribui mensagens
- ✅ VPC Peering está ativo e rotas configuradas
- ✅ RDS em us-east-2/us-east-1 acessível (latência < 300ms)
- ✅ Pipeline end-to-end sem erros
- ✅ Zero mensagens em Dead Letter Queues
- ✅ Dados inseridos corretamente no RDS
- ✅ CloudWatch logs mostram execução limpa
- ✅ Performance aceitável (latência total < 10 min)

---

## 9. Pós-Migração

### Descomissionar Arquitetura Antiga
Após 1-2 semanas de validação em PRD:
1. Deletar Lambdas antigas em us-east-1
2. Deletar SQS antigas
3. Deletar EventBridge antiga
4. Deletar VPC Peering (se tiver criar segunda para transição)

### Monitoramento Contínuo
- CloudWatch metrics diárias (primeiras 4 semanas)
- Alertas para DLQ messages
- Alertas para latência anômala
- Logs de execução (último 4º de cada mês)

### Lições Aprendidas
- Documentar problemas encontrados
- Otimizações descobertas
- Impacto de latência observado
- Recomendações para futuras migrações

---

## 10. Diagrama de Fluxo

```
┌─────────────────────┐
│   FIPE API (BR)     │
└──────────┬──────────┘
           │
           │ HTTP Request (IP: sa-east-1)
           │
    ┌──────▼────────────────────┐
    │  sa-east-1 Region         │
    │                            │
    │ ┌────────────────────────┐ │
    │ │ Lambdas (sem VPC)      │ │
    │ │ - Manufacturer Loader  │ │
    │ │ - Model Loader         │ │
    │ │ - Price Loader         │ │
    │ └──────────┬─────────────┘ │
    │            │                │
    │            │ SQS Messages   │
    │            ▼                │
    │ ┌────────────────────────┐ │
    │ │ SQS Queues (sa-east-1) │ │
    │ │ - Manufacturer         │ │
    │ │ - Model                │ │
    │ │ - Price                │ │
    │ │ - Soma                 │ │
    │ └──────────┬─────────────┘ │
    │            │                │
    │            │ SQS Trigger    │
    │            ▼                │
    │ ┌────────────────────────┐ │
    │ │ Lambda (com VPC)       │ │
    │ │ - Soma Ingestor        │ │
    │ └──────────┬─────────────┘ │
    │            │                │
    └────────────┼────────────────┘
                 │
                 │ VPC Peering (sa-east-1 ↔ us-east-2/us-east-1)
                 │
         ┌───────▼───────┐
         │ RDS (us-east) │
         │ - STG (us-e2) │
         │ - PRD (us-e1) │
         └───────────────┘
```

---

## Próximos Passos

1. ✅ Design aprovado e documentado
2. ⏳ Revisão da spec por stakeholder
3. ⏳ Criação do plano de implementação (skill: writing-plans)
4. ⏳ Execução em STG (Etapas 1-5)
5. ⏳ Validação completa em STG
6. ⏳ Execução em PRD (Etapas 1-5)
7. ⏳ Descomissionar arquitetura antiga
