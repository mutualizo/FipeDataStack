# Migração Python 3.10 → 3.12 + Atualização de Dependências

**Data:** 2026-05-15  
**Autor:** Alexandre Defendi  
**Status:** Design Aprovado

---

## 1. Visão Geral

### Motivador
A AWS está descontinuando o suporte ao Python 3.10 em Lambda. Esta migração é obrigatória para manter a compatibilidade e segurança da infraestrutura FipeDataStack.

### Objetivo
Migrar o projeto de Python 3.10 para Python 3.12 e atualizar todas as dependências para versões compatíveis com o novo runtime, mantendo a funcionalidade existente e validando a integridade da pipeline de dados.

### Escopo
- Atualizar versão do Python em workflows GitHub Actions (3.10 → 3.12)
- Atualizar runtime das funções Lambda no CDK (3.10 → 3.12)
- Atualizar todas as dependências nos arquivos `requirements.txt` e `fipe_api_layer/requirements.txt`
- Validação completa em STG antes de rollout para PRD
- Ambientes impactados: **STG → PRD** (DEV descontinuado)

---

## 2. Arquitetura e Fases

### Estratégia: Staged Approach

A migração será executada em **2 fases** (STG e PRD), com **2 etapas por fase**:

#### Fase 1: Staging Environment

**Etapa 1a: Atualização do Python (Staging)**
- Atualizar `python-version` no workflow de `3.10` → `3.12`
- Atualizar Lambda runtime no CDK stack de `3.10` → `3.12`
- Rebuild da Lambda layer com Python 3.12
- Executar testes automatizados (lint, unit tests, CDK validation, layer validation)
- Executar testes manuais (execução pipeline, testes DB, teste E2E)
- **Critério de Sucesso:** Todos os testes passam, nenhuma quebra no CloudFormation
- **Progressão:** Se OK → avança para Etapa 2a; Se Falhar → investigar incompatibilidades e corrigir

**Etapa 2a: Atualização de Dependências (Staging)**
- Atualizar `requirements.txt` (CDK + boto3, constructs)
- Atualizar `fipe_api_layer/requirements.txt` (aws-lambda-powertools, boto3-stubs, psycopg2-binary, requests, httpx, etc.)
- Rebuild da Lambda layer
- Executar testes automatizados (lint, unit tests, CDK validation, layer validation)
- Executar testes manuais (execução pipeline, testes DB, teste E2E, monitoramento DLQs)
- **Critério de Sucesso:** Todos os testes passam, pipeline executa sem erros, banco de dados operacional
- **Progressão:** Se OK → ambas as etapas em PRD; Se Falhar → downgrade seletivo de dependências problemáticas

#### Fase 2: Produção Environment

Repetir Etapas 1a e 2a com os mesmos critérios de validação em produção.

### Benefício da Abordagem Staged

O isolamento entre Etapa 1 (Python) e Etapa 2 (Dependências) permite identificar rapidamente a causa de qualquer falha:
- Se Etapa 1 quebra → problema é incompatibilidade do Python 3.12 com o código
- Se Etapa 2 quebra → problema é uma ou mais dependências incompatíveis
- Se ambas passam → migração bem-sucedida

---

## 3. Componentes que Serão Tocados

### Arquivos a Modificar

| Arquivo | Mudança | Justificativa |
|---------|---------|---------------|
| `.github/workflows/deploy-development.yml` | `python-version: '3.10'` → `'3.12'` | Atualizar runtime dos testes e builds |
| `fipe_api_stack.py` | `runtime=lambda_.Runtime.PYTHON_3_10` → `PYTHON_3_12` | Novo runtime das funções Lambda |
| `fipe_data_stack.py` | Revisar se há referências a Python 3.10 | Garantir consistência |
| `requirements.txt` | Atualizar versões de `aws-cdk-lib`, `boto3`, `constructs` | Compatibilidade com Python 3.12 |
| `fipe_api_layer/requirements.txt` | Atualizar todas as dependências (boto3, aws-lambda-powertools, psycopg2-binary, httpx, requests, etc.) | Compatibilidade com Python 3.12 |
| `create-fipe-api-layer.sh` | Revisar script para compatibilidade com 3.12 | Pode ser necessário atualizar flags de compilação |

### Dependências Principais a Validar

- **aws-cdk-lib:** Verificar compatibilidade com Python 3.12
- **boto3 e boto3-stubs:** Atualizar para versão estável mais recente
- **psycopg2-binary:** Verificar wheels disponíveis para Python 3.12
- **aws-lambda-powertools:** Atualizar para versão com suporte a 3.12
- **requests e httpx:** Atualizar para versões compatíveis

---

## 3.1 Gestão de GitHub Actions Workflows

### Workflows Impactados

```
.github/workflows/
├─ deploy-development.yml    (DEV descontinuado, pode ser ignorado)
├─ deploy-stage.yml          ← MODIFICAR
└─ deploy-production.yml     ← MODIFICAR
```

Ambos os workflows possuem:
- Trigger automático: `push` para branch (stage / production)
- Trigger manual: `workflow_dispatch`
- Python version: **3.10** (linha 30) ← ATUALIZAR

### Risco de Auto-Deploy Durante Migração

**Problema:** Se alguém fizer `push` para `stage` ou `production` branch durante a migração:
- Workflow dispara **automaticamente**
- Deploy com Python **3.10** (misturado com código 3.12)
- Falha ou comportamento inconsistente
- Stack pode ficar em estado quebrado

### Estratégia: Desativar → Alterar → Reativar

#### Fase Preparação: Desativar Auto-Deploy

**Antes de começar a migração:**

Editar `.github/workflows/deploy-stage.yml` e `.github/workflows/deploy-production.yml`:

```yaml
# ANTES:
on:
  workflow_dispatch:
  push:                    # ← Trigger automático
    branches:
      - stage

# DEPOIS (comentar push):
on:
  workflow_dispatch:       # ← Apenas manual
  # push:
  #   branches:
  #     - stage
```

**Benefício:** Workflows não disparam ao fazer push, evitando auto-deploy com código misto.

#### Fase Etapa 1a: Atualizar Python e Invocar Manualmente

Editar `.github/workflows/deploy-stage.yml`:

```yaml
# ANTES:
- name: Setup Python
  uses: actions/setup-python@v4
  with:
    python-version: '3.10'   # ← OLD

# DEPOIS:
- name: Setup Python
  uses: actions/setup-python@v4
  with:
    python-version: '3.12'   # ← NEW
```

**Invocar workflow manualmente** (não automático):

```bash
# Opção 1: GitHub CLI
gh workflow run deploy-stage.yml

# Opção 2: GitHub Web UI
# Actions → Deploy CDK Python Stack - Stage → Run workflow → Run workflow
```

#### Fase Etapa 2a: Repetir para Dependências

Mesmo processo:
1. Atualizar dependências em `requirements.txt` e `fipe_api_layer/requirements.txt`
2. Fazer commit
3. Invocar workflow **manualmente** (não automático)

#### Fase Finalização: Reativar Auto-Deploy

**Após validação completa em STG e PRD:**

Descomentar trigger `push` em `.github/workflows/deploy-stage.yml` e `.github/workflows/deploy-production.yml`:

```yaml
# DEPOIS (descomentar push):
on:
  workflow_dispatch:
  push:                      # ← Reativar
    branches:
      - stage
```

**Benefício:** Workflows voltam ao modo normal, auto-deploy funciona novamente.

### Arquivos a Modificar (Workflows)

| Arquivo | Mudança | Quando |
|---------|---------|--------|
| `.github/workflows/deploy-stage.yml` | Comentar trigger `push` | Preparação |
| `.github/workflows/deploy-stage.yml` | `python-version: '3.10'` → `'3.12'` | Etapa 1a |
| `.github/workflows/deploy-stage.yml` | Descomentar trigger `push` | Finalização |
| `.github/workflows/deploy-production.yml` | Comentar trigger `push` | Passo 1 (PRD prep) |
| `.github/workflows/deploy-production.yml` | `python-version: '3.10'` → `'3.12'` | Etapa 1a (PRD) |
| `.github/workflows/deploy-production.yml` | Descomentar trigger `push` | Passo Final |

### Checklist de Segurança

- ✅ **Passo 0:** Comentar trigger `push` em ambos os workflows
- ✅ **Etapa 1a (STG):** Atualizar Python → 3.12, invocar manualmente
- ✅ **Etapa 2a (STG):** Atualizar deps → invocar manualmente
- ✅ **Validação STG:** Todos os testes passam?
- ✅ **Passo 1 (PRD prep):** Comentar trigger `push` em deploy-production.yml
- ✅ **Etapa 1a (PRD):** Atualizar Python → 3.12, invocar manualmente
- ✅ **Etapa 2a (PRD):** Atualizar deps → invocar manualmente
- ✅ **Validação PRD:** Todos os testes passam?
- ✅ **Passo Final:** Descomentar trigger `push` em ambos os workflows
- ✅ **Verificação:** Workflows estão ativos novamente?

### Avisos ao Time

**Comunicação importante durante migração:**

```markdown
⚠️ AVISO: Migração Python 3.10 → 3.12 em progresso

- Auto-deploy desativado em `stage` e `production` branches
- Workflows APENAS manuais (`workflow_dispatch`)
- Se precisar fazer deploy: use GitHub Actions UI ou `gh workflow run`
- ✅ Auto-deploy será reativado após testes completos

Duração estimada: 2-3 dias
```

---

## 4. Estratégia de Testes

### Testes Automatizados

#### 4.1 Lint com Ruff
```bash
ruff check .
ruff format --check .
```
- Validar qualidade do código
- Garantir conformidade com padrões de projeto
- Executar antes de cada etapa

#### 4.2 Unit Tests
```bash
python -m pytest tests/
```
- Validar que não há erros de importação
- Verificar lógica dos testes existentes
- Confirmar que templates CDK geram corretamente

#### 4.3 CDK Validation
```bash
cdk diff --context vpc_id=<VPC_ID> --context allowed_ip=<ALLOWED_IP>
```
- Validar que o template CloudFormation não sofreu mudanças inesperadas
- Garantir que não há breaking changes

#### 4.4 Lambda Layer Validation
```bash
./create-fipe-api-layer.sh
```
- Rebuild manual da layer
- Verificar que todos os pacotes são instalados corretamente
- Validar que não há erros de compilação

### Testes Manuais (em Staging)

#### 4.5 Execução Manual da Pipeline
```bash
aws lambda invoke --function-name FipeManufacturerLoader-stg response.json
cat response.json
```
- Invocar função Lambda manualmente
- Validar que executa sem erros
- Monitorar logs em CloudWatch
- Verificar que dados são processados corretamente

#### 4.6 Teste de Conexão com Banco de Dados
```bash
# Via Lambda function ou psql
SELECT * FROM fipedata.information_schema.tables;
INSERT INTO <table> VALUES (...);
```
- Validar que Lambda consegue conectar ao RDS
- Testar SELECT e INSERT operations
- Confirmar que credenciais do Secrets Manager funcionam

#### 4.7 Teste End-to-End
- Executar pipeline completa: Manufacturer → Model → Price → Ingestor
- Validar que todas as 4 funções Lambda são invocadas corretamente
- Confirmar que dados finais são inseridos no banco de dados
- Validar integridade dos dados (sem linhas duplicadas, valores corretos)

#### 4.8 Monitoramento de Dead Letter Queues (DLQs)
```bash
aws sqs get-queue-attributes --queue-url <DLQ_URL> \
  --attribute-names ApproximateNumberOfMessages
```
- Validar que não há mensagens em nenhuma DLQ
- Se houver mensagens: investigar causa e reprocessar

---

## 5. Tratamento de Erros e Rollback

### Cenário 1: Falha em Etapa 1a (Python 3.12 em STG)

**Sintomas:**
- Unit tests falham
- Lint encontra erros de compatibilidade
- CDK validation mostra breaking changes
- Lambda layer falha ao rebuildar

**Ação:**
1. Revisar logs detalhados de erro
2. Investigar qual código/dependência é incompatível
3. Corrigir o código ou fazer downgrade seletivo
4. Reexecutar testes
5. **Não avançar para Etapa 2a** até que Etapa 1a esteja 100% estável

### Cenário 2: Falha em Etapa 2a (Dependências em STG)

**Sintomas:**
- Lint encontra conflitos entre versões
- Unit tests falham por incompatibilidade de dependência
- Lambda não consegue importar módulos
- Testes manuais mostram erros de runtime

**Ação:**
1. Identificar qual(is) dependência(s) causou(aram) o problema
2. Estratégia A: Atualizar para versão mais recente que seja compatível
3. Estratégia B: Manter versão atual dessa dependência, atualizar as outras
4. Reexecutar testes
5. Se múltiplas dependências forem incompatíveis: documentar e seguir com as que funcionam

### Cenário 3: Falha Crítica em STG (ambas etapas)

**Ação:**
1. Revert do commit/branch
2. Redeploy da stack com Python 3.10 (STG ainda terá 3.10 no template)
3. Investigação pós-mortem para entender a causa
4. Replanejar a migração se necessário

### Cenário 4: Falha em PRD

**Ação:**
1. Se Etapa 1a falha: corrigir código e reexecutar
2. Se Etapa 2a falha: aplicar mesma estratégia que em STG
3. Se falha crítica: revert para Python 3.10 (versão anterior do CloudFormation)
4. Não há impacto em STG pois estará em Python 3.12

---

## 6. Plano de Validação e Cronograma

### Timeline de Execução

| Etapa | Ambiente | Atividades | Duração | Executor |
|-------|----------|-----------|---------|----------|
| 1a | STG | Atualizar Python, lint, unit tests, CDK validation, testes manuais | 50 min | CI/CD + Manual |
| 2a | STG | Atualizar deps, rebuild layer, lint, unit tests, testes manuais, DLQ check | 65 min | CI/CD + Manual |
| 1-2 | PRD | Repetir Etapas 1a e 2a em produção | ~2h | CI/CD + Manual |

### Recomendação de Agendamento

- **Dia 1 (STG Etapa 1a):** Durante horário comercial (09:00-10:00)
- **Dia 2 (STG Etapa 2a):** Durante horário comercial (09:00-10:15)
- **Dia 3+ (PRD):** Após validação completa em STG; fora do horário crítico de operações (ex: 20:00-22:00)

### Critérios de Sucesso Globais

- ✅ Todos os testes automatizados passam (lint, unit tests, CDK, layer validation)
- ✅ Pipeline executa sem erros em testes manuais
- ✅ Banco de dados operacional e dados inseridos corretamente
- ✅ Nenhuma mensagem em Dead Letter Queues
- ✅ Logs do CloudWatch mostram execução limpa
- ✅ PRD em Python 3.12 com todas as dependências atualizadas

---

## 7. Documentação e Logging

### Por Etapa

Cada etapa será documentada em um commit separado com mensagem clara:

```
Etapa 1a: Atualizar Python 3.10 → 3.12 (STG)

- Atualizar python-version em workflows
- Atualizar Lambda runtime em CDK stack
- Rebuild lambda layer com Python 3.12
- Todos os testes automatizados passam
- Testes manuais validam pipeline e DB
```

### Log de Execução

Um arquivo será criado em `.github/migration-log-2026-05-15.md` com:
- Data/hora de início e fim de cada etapa
- Resultado dos testes (✅ PASSOU / ❌ FALHOU)
- Problemas encontrados e soluções aplicadas
- Tempo total de execução

---

## 8. Resumo de Mudanças Esperadas

### Requirements.txt (CDK)
- `aws-cdk-lib`: 2.252.0 → versão compatível com 3.12
- `boto3`: >=1.28.0 → versão estável mais recente
- `constructs`: >=10.0.0 → versão compatível

### fipe_api_layer/requirements.txt (Lambdas)
- `boto3`: 1.28.36 → versão estável mais recente
- `boto3-stubs`: 1.28.36 → versão compatível
- `aws-lambda-powertools`: 2.37.0 → versão com suporte a 3.12
- `psycopg2-binary`: 2.9.9 → versão com wheels para 3.12
- `requests`: 2.31.0 → versão estável mais recente
- `httpx`: 0.27.0 → versão compatível
- Outros pacotes: validar compatibilidade

### Workflows
- `.github/workflows/deploy-development.yml`: python-version 3.10 → 3.12
- Outros workflows (stg, prd): mesmo padrão

---

## 9. Riscos e Mitigações

| Risco | Probabilidade | Mitigação |
|-------|---------------|-----------|
| Dependência incompatível com 3.12 | Média | Teste em STG primeiro; downgrade seletivo se necessário |
| Código incompatível com 3.12 | Baixa | Lint com ruff captura a maioria dos problemas |
| Breaking change no CDK | Baixa | CDK validation detecta mudanças antes do deploy |
| Falha de compilação de psycopg2-binary | Média | Verificar wheels disponíveis; usar versão mais recente |
| Impacto em PRD durante deploy | Baixa | Validação completa em STG antes; rollback plano |

---

## 10. Próximos Passos

1. ✅ Design aprovado e documentado
2. ⏳ Revisão da spec por stakeholder
3. ⏳ Criação do plano de implementação (skill: writing-plans)
4. ⏳ Execução em STG (Etapa 1a)
5. ⏳ Execução em STG (Etapa 2a)
6. ⏳ Execução em PRD (Etapas 1a + 2a)
7. ⏳ Validação final e limpeza
