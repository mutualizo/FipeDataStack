# CHECKLIST DETALHADO: Melhoria 1 - Python 3.10 → 3.12

**Versão:** 2026-05-15  
**Status:** Pronto para Implementação  
**Tempo Estimado:** 8-10 horas de trabalho

---

## FASE PREPARAÇÃO

### 1. Setup Inicial
- [ ] Ler especificação: `docs/superpowers/specs/2026-05-15-python-3-12-migration-design.md`
- [ ] Criar branch: `git checkout -b feature/python-312-migration`
- [ ] Validar ambiente: Python 3.12 instalado localmente (`python --version`)
- [ ] Notificar team: "Começando migração Python 3.10 → 3.12 (duração: 2-3 dias)"

### 2. PASSO CRÍTICO: Desativar Auto-Deploy dos Workflows
⚠️ **FAZER ISTO PRIMEIRO ANTES DE QUALQUER OUTRA MUDANÇA**

#### 2.1 Editar `.github/workflows/deploy-stage.yml`
```bash
# Editar arquivo
vim .github/workflows/deploy-stage.yml
```

**Mudança necessária (linhas 3-7):**
```yaml
# ANTES:
on:
  workflow_dispatch:
  push:
    branches:
      - stage

# DEPOIS (comentar push):
on:
  workflow_dispatch:
  # push:
  #   branches:
  #     - stage
```

- [ ] Atualizar arquivo
- [ ] Validar: `cat .github/workflows/deploy-stage.yml | grep -A 3 "^on:"`
- [ ] Commit: `git commit -am "CI: Desativar auto-deploy em STG durante migração"`

#### 2.2 Editar `.github/workflows/deploy-production.yml`
```bash
vim .github/workflows/deploy-production.yml
```

**Mesma mudança que 2.1 (comentar trigger push):**

- [ ] Atualizar arquivo
- [ ] Validar: `cat .github/workflows/deploy-production.yml | grep -A 3 "^on:"`
- [ ] Commit: `git commit -am "CI: Desativar auto-deploy em PRD durante migração"`

#### 2.3 Verificação de Segurança
```bash
# Garantir que workflows NÃO disparam ao fazer push
git push origin feature/python-312-migration

# Ir para GitHub Actions e validar que:
# - Deploy Stage NÃO foi disparado
# - Deploy Production NÃO foi disparado
```

- [ ] Confirmado: workflows desativados (nenhum disparo automático)

---

## FASE STG (STAGING)

### 3. ETAPA 1a: Atualizar Python para 3.12 em STG

#### 3.1 Atualizar Workflow deploy-stage.yml
```bash
vim .github/workflows/deploy-stage.yml
```

**Mudança (linha 30):**
```yaml
# ANTES:
- name: Setup Python
  uses: actions/setup-python@v4
  with:
    python-version: '3.10'

# DEPOIS:
- name: Setup Python
  uses: actions/setup-python@v4
  with:
    python-version: '3.12'
```

- [ ] Atualizar arquivo
- [ ] Validar: `grep "python-version:" .github/workflows/deploy-stage.yml`
- [ ] Commit: `git commit -am "CI: Atualizar Python 3.10 → 3.12 em deploy-stage.yml"`

#### 3.2 Atualizar fipe_api_stack.py
```bash
vim fipe_api_stack.py
```

**Procurar por (grep):**
```bash
grep -n "PYTHON_3_10" fipe_api_stack.py
```

**Mudança:**
```python
# ANTES:
runtime=lambda_.Runtime.PYTHON_3_10

# DEPOIS:
runtime=lambda_.Runtime.PYTHON_3_12
```

- [ ] Atualizar todas as ocorrências
- [ ] Validar: `grep "PYTHON_3_12" fipe_api_stack.py`
- [ ] Commit: `git commit -am "CDK: Atualizar Lambda runtime para Python 3.12"`

#### 3.3 Rebuild Lambda Layer com Python 3.12
```bash
# Preparar layers com Python 3.12
make prepare-layers

# OU manualmente:
chmod +x create-fipe-api-layer.sh
./create-fipe-api-layer.sh
```

- [ ] Layer rebuilt com sucesso
- [ ] Validar: `ls -la fipe_api_layer.zip` (arquivo existe?)

#### 3.4 Testes Automatizados - Etapa 1a
```bash
# Lint
ruff check .
ruff format --check .

# Unit tests
python -m pytest tests/

# CDK validation
cdk diff --context vpc_id=vpc-xxxxx --context allowed_ip=123.456.789.0
```

- [ ] Ruff check PASSED
- [ ] Unit tests PASSED
- [ ] CDK diff mostra mudanças esperadas (apenas Python 3.12)
- [ ] Commit: `git commit -am "Tests: Python 3.12 in STG - all automated tests pass"`

#### 3.5 Deploy Etapa 1a em STG
```bash
# Opção 1: GitHub CLI
gh workflow run deploy-stage.yml

# Opção 2: GitHub Web UI
# 1. Ir para https://github.com/seu-repo/actions
# 2. Clicar "Deploy CDK Python Stack - Stage"
# 3. Clicar "Run workflow" → "Run workflow"
```

- [ ] Workflow iniciado (observar status em GitHub Actions)
- [ ] Aguardar conclusão (~5-10 minutos)
- [ ] ✅ Workflow finalizado com sucesso (verde)
- [ ] Validar CloudFormation stack (sem erros)

#### 3.6 Testes Manuais - Etapa 1b (Validação em STG)
```bash
# Invocar FipeManufacturerLoader manualmente
aws lambda invoke \
  --function-name FipeManufacturerLoader-stg \
  --region us-east-1 \
  response.json

# Verificar resposta
cat response.json

# Ver logs
aws logs tail /aws/lambda/FipeManufacturerLoader-stg --follow
```

- [ ] Lambda executou com sucesso (FunctionError NÃO presente)
- [ ] Logs mostram: "INFO" (sem erros)
- [ ] Validar mensagens em SQS (chegaram?)
  ```bash
  aws sqs get-queue-attributes \
    --queue-url https://sqs.us-east-1.amazonaws.com/xxx/fipe-manufacturer-queue-stg \
    --attribute-names ApproximateNumberOfMessages \
    --region us-east-1
  ```
- [ ] ✅ Mensagens na fila (ApproximateNumberOfMessages > 0)
- [ ] Documentar: "✅ Etapa 1 PASSED"
- [ ] Commit: `git commit -am "Test: Etapa 1a STG - Manual tests passed"`

---

### 4. ETAPA 2a: Atualizar Dependências em STG

#### 4.1 Atualizar requirements.txt
```bash
# Ver versões atuais
cat requirements.txt

# Editar arquivo
vim requirements.txt
```

**Atualizar:**
```
# ANTES:
aws-cdk-lib == 2.252.0
constructs>=10.0.0,<11.0.0
boto3>=1.28.0
psycopg2-binary>=2.9.6

# DEPOIS: (pesquisar versões compatíveis com Python 3.12)
aws-cdk-lib == 2.LATEST  # ← Atualizar para versão mais recente compatível
constructs>=10.0.0,<11.0.0  # ← Validar compatibilidade
boto3>=1.28.0  # ← Atualizar para latest
psycopg2-binary>=2.9.6  # ← Atualizar para latest
```

- [ ] Atualizar versões
- [ ] Testar localmente: `pip install -r requirements.txt` (sem erros?)
- [ ] Commit: `git commit -am "Dependencies: Atualizar requirements.txt para Python 3.12"`

#### 4.2 Atualizar fipe_api_layer/requirements.txt
```bash
vim fipe_api_layer/requirements.txt
```

**Atualizar (validar compatibilidade com 3.12):**
```
# Principais a verificar:
boto3==1.28.36                    → boto3==LATEST
boto3-stubs[sqs, dynamodb]==1.28.36  → boto3-stubs[sqs, dynamodb]==LATEST
aws_lambda_powertools==2.37.0     → aws_lambda_powertools==LATEST (com suporte 3.12)
requests==2.31.0                  → requests==LATEST
psycopg2-binary==2.9.9            → psycopg2-binary==LATEST (validar wheels 3.12)
httpx==0.27.0                     → httpx==LATEST
```

- [ ] Atualizar versões
- [ ] Testar: `pip install -r fipe_api_layer/requirements.txt` (sem erros?)
- [ ] Commit: `git commit -am "Dependencies: Atualizar lambda layer requirements para Python 3.12"`

#### 4.3 Rebuild Lambda Layer com Deps Atualizadas
```bash
make prepare-layers
```

- [ ] Layer rebuilt com sucesso
- [ ] Validar: `ls -la fipe_api_layer.zip`

#### 4.4 Testes Automatizados - Etapa 2a
```bash
ruff check .
ruff format --check .
python -m pytest tests/
cdk diff --context vpc_id=vpc-xxxxx --context allowed_ip=123.456.789.0
```

- [ ] Ruff check PASSED
- [ ] Unit tests PASSED
- [ ] CDK diff mostra mudanças esperadas (versões de deps)
- [ ] Commit: `git commit -am "Tests: Deps updated in STG - all automated tests pass"`

#### 4.5 Deploy Etapa 2a em STG
```bash
gh workflow run deploy-stage.yml
# OU via GitHub UI
```

- [ ] Workflow iniciado
- [ ] Aguardar conclusão
- [ ] ✅ Workflow finalizado com sucesso
- [ ] Validar CloudFormation (sem erros)

#### 4.6 Testes Manuais - Etapa 2b (Validação em STG)
```bash
# Invocar FipePriceLoader
aws lambda invoke \
  --function-name FipePriceLoader-stg \
  --region us-east-1 \
  --payload '{"Records":[{"body":"{\\"manufacturer\\":\\"FORD\\",\\"model\\":\\"Fiesta\\"}"}]}' \
  response.json
```

- [ ] Lambda executou com sucesso
- [ ] Logs sem erros

```bash
# Invocar FipeSomaIngestor (para validar RDS connection)
aws lambda invoke \
  --function-name FipeSomaIngestor-stg \
  --region us-east-1 \
  --payload '{"Records":[{"body":"{\\"price\\":\\"15000\\"}"}]}' \
  response.json
```

- [ ] Lambda conectou ao RDS (sem erros de conexão)
- [ ] Validar dados no RDS:
  ```bash
  # Conectar ao RDS STG (us-east-2)
  psql -h <RDS_ENDPOINT> -p 5432 -U postgres -d fipedata -c "SELECT COUNT(*) FROM fipe_vehicle_price;"
  ```

- [ ] ✅ Dados no banco (COUNT > 0)
- [ ] Validar DLQs vazias:
  ```bash
  aws sqs get-queue-attributes \
    --queue-url https://sqs.us-east-1.amazonaws.com/xxx/fipe-manufacturer-dlq-stg \
    --attribute-names ApproximateNumberOfMessages
  ```

- [ ] ✅ DLQs vazias (ApproximateNumberOfMessages = 0)
- [ ] Documentar: "✅ Etapa 2 PASSED"
- [ ] Commit: `git commit -am "Test: Etapa 2a STG - Manual tests passed"`

#### 4.7 Go/No-Go Decision para PRD
- [ ] ✅ Etapa 1a PASSED
- [ ] ✅ Etapa 1b PASSED
- [ ] ✅ Etapa 2a PASSED
- [ ] ✅ Etapa 2b PASSED

**Decisão:**
- [ ] **GO** para PRD (todos testes passaram, proceder para produção)
  - OU
- [ ] **NO-GO** para PRD (algum teste falhou, investigar antes)

---

## FASE PRD (PRODUÇÃO)

### 5. PASSO 1: Preparar Workflows PRD

#### 5.1 Desativar Auto-Deploy em deploy-production.yml
```bash
vim .github/workflows/deploy-production.yml
```

**Comentar trigger push:**
```yaml
on:
  workflow_dispatch:
  # push:
  #   branches:
  #     - production
```

- [ ] Arquivo atualizado
- [ ] Commit: `git commit -am "CI: Desativar auto-deploy em PRD antes de migração"`

### 6. ETAPA 1a: Atualizar Python para 3.12 em PRD

#### 6.1 Atualizar Workflow deploy-production.yml
```bash
vim .github/workflows/deploy-production.yml
```

**Mudança (linha 30):**
```yaml
python-version: '3.12'
```

- [ ] Arquivo atualizado
- [ ] Commit: `git commit -am "CI: Atualizar Python 3.10 → 3.12 em deploy-production.yml"`

#### 6.2 Deploy Etapa 1a em PRD
```bash
gh workflow run deploy-production.yml
```

- [ ] Workflow iniciado
- [ ] Aguardar conclusão
- [ ] ✅ Workflow finalizado com sucesso
- [ ] Validar CloudFormation PRD (sem erros)

#### 6.3 Testes Manuais - Etapa 1b em PRD
```bash
# Invocar FipeManufacturerLoader-prd
aws lambda invoke \
  --function-name FipeManufacturerLoader-prd \
  --region us-east-1 \
  response.json
```

- [ ] Lambda executou com sucesso
- [ ] Logs OK (INFO, sem erros)
- [ ] ✅ Etapa 1b PRD PASSED

### 7. ETAPA 2a: Atualizar Dependências em PRD

#### 7.1 Atualizar Workflows deploy-production.yml
**Não há alteração de deps aqui (já foi em STG)**

#### 7.2 Deploy Etapa 2a em PRD
```bash
gh workflow run deploy-production.yml
```

- [ ] Workflow iniciado
- [ ] Aguardar conclusão
- [ ] ✅ Workflow finalizado com sucesso

#### 7.3 Testes Manuais - Etapa 2b em PRD
```bash
# Invocar FipePriceLoader-prd
aws lambda invoke --function-name FipePriceLoader-prd --region us-east-1 response.json

# Invocar FipeSomaIngestor-prd
aws lambda invoke --function-name FipeSomaIngestor-prd --region us-east-1 response.json
```

- [ ] Lambdas executaram com sucesso
- [ ] RDS PRD (us-east-1) conectou OK
- [ ] ✅ Etapa 2b PRD PASSED

---

## FASE FINALIZAÇÃO

### 8. PASSO FINAL: Reativar Auto-Deploy

#### 8.1 Descomentar Trigger Push em deploy-stage.yml
```bash
vim .github/workflows/deploy-stage.yml
```

**Descomentar:**
```yaml
on:
  workflow_dispatch:
  push:
    branches:
      - stage
```

- [ ] Arquivo atualizado
- [ ] Commit: `git commit -am "CI: Reativar auto-deploy em STG"`

#### 8.2 Descomentar Trigger Push em deploy-production.yml
```bash
vim .github/workflows/deploy-production.yml
```

**Descomentar:**
```yaml
on:
  workflow_dispatch:
  push:
    branches:
      - production
```

- [ ] Arquivo atualizado
- [ ] Commit: `git commit -am "CI: Reativar auto-deploy em PRD"`

#### 8.3 Verificação de Workflows Reativados
```bash
# Validar que workflows estão comentados removidos
git diff .github/workflows/deploy-*.yml

# Verificar em GitHub
# Actions → ver se workflows têm "push:" trigger
```

- [ ] ✅ Workflows reativados (push trigger ativo)
- [ ] ✅ Nenhum comentário em "on:" seção

### 9. Create Pull Request
```bash
# Push para main/develop
git push origin feature/python-312-migration

# Criar PR via GitHub CLI
gh pr create --title "Python 3.10 → 3.12 Migration" \
  --body "Completes migration to Python 3.12 with updated dependencies"

# OU via GitHub Web UI
```

- [ ] PR criado
- [ ] Title: "Python 3.10 → 3.12 Migration"
- [ ] Description: Referencia arquivo de spec
- [ ] Pedir review de 1-2 pessoas
- [ ] ✅ PR aprovado

### 10. Merge para Main
```bash
gh pr merge <PR_NUMBER> --merge --auto

# OU via GitHub Web UI (Squash and merge recomendado)
```

- [ ] PR merged para main
- [ ] Branch deletado (local + remote)

### 11. Create Release Tag
```bash
git tag -a v1.1.0-python-312 -m "Python 3.10 → 3.12 Migration Complete"
git push origin v1.1.0-python-312
```

- [ ] Tag criada
- [ ] Tag pushed para remote

### 12. Notificar Team
```
✅ MIGRAÇÃO PYTHON 3.10 → 3.12 COMPLETA

Timeline:
- STG: ✅ Validado com sucesso
- PRD: ✅ Validado com sucesso

Mudanças:
- Python 3.10 → 3.12 em todas as Lambdas
- Dependências atualizadas
- Auto-deploy reativado

Release: v1.1.0-python-312
```

- [ ] Team notificado
- [ ] Documentação atualizada

---

## CHECKLIST DE SEGURANÇA FINAL

- [ ] ✅ Workflows desativados no início da migração
- [ ] ✅ Auto-deploy não dispara durante migração
- [ ] ✅ Testes automatizados PASSAM em ambas etapas
- [ ] ✅ Testes manuais PASSAM em STG antes de PRD
- [ ] ✅ Testes manuais PASSAM em PRD
- [ ] ✅ RDS em ambos ambientes conecta OK
- [ ] ✅ DLQs vazias (sem erros)
- [ ] ✅ Workflows reativados após testes
- [ ] ✅ PR criado, revisado, mergeado
- [ ] ✅ Release tag criada
- [ ] ✅ Team notificado

---

## RESUMO DE COMMITS

Você fará commits nesta ordem:
```
1. CI: Desativar auto-deploy em STG durante migração
2. CI: Desativar auto-deploy em PRD durante migração
3. CI: Atualizar Python 3.10 → 3.12 em deploy-stage.yml
4. CDK: Atualizar Lambda runtime para Python 3.12
5. Tests: Python 3.12 in STG - all automated tests pass
6. Test: Etapa 1a STG - Manual tests passed
7. Dependencies: Atualizar requirements.txt para Python 3.12
8. Dependencies: Atualizar lambda layer requirements para Python 3.12
9. Tests: Deps updated in STG - all automated tests pass
10. Test: Etapa 2a STG - Manual tests passed
11. CI: Desativar auto-deploy em PRD antes de migração
12. CI: Atualizar Python 3.10 → 3.12 em deploy-production.yml
13. Test: Etapa 1a PRD - Manual tests passed
14. Test: Etapa 2a PRD - Manual tests passed
15. CI: Reativar auto-deploy em STG
16. CI: Reativar auto-deploy em PRD
```

---

**Tempo Total Estimado:** 8-10 horas  
**Críticos:** Passos 2, 3.5, 6.2, 8.1, 8.2 (envolvem CI/CD)

