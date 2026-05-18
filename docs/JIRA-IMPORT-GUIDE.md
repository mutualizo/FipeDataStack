# Guia de Importação - Checklist for Jira Cloud

**Data:** 2026-05-15  
**App:** Checklist for Jira Cloud  
**Arquivo:** `docs/fipe-melhorias-checklist.json`

---

## Visão Geral

O arquivo `fipe-melhorias-checklist.json` contém todas as 4 melhorias organizadas como checklists estruturados:

| Melhoria | ID | Tarefas | Duração |
|----------|----|---------| --------|
| Python 3.12 Migration | `melhoria-1-python-312` | 30+ | 8h |
| Multi-Region Lambdas | `melhoria-2-multi-region` | 40+ | 20h |
| Observability & Resilience | `melhoria-3-observability` | 35+ | 10h |
| Webhooks | `melhoria-4-webhooks` | 30+ | 6.5h |

**Total: 135+ tarefas, 44.5 horas de desenvolvimento**

---

## Opção 1: Importar como Jira Issues

### Passo 1: Abrir App Checklist for Jira Cloud

1. Acesse seu projeto Jira
2. Clique em **Apps** → **Checklist for Jira Cloud**
3. Ou acesse diretamente: `https://jira.company.com/secure/RapidBoard.jspa`

### Passo 2: Criar Issue Base

Para cada melhoria, crie uma Issue:

```
Projeto: FipeDataStack2
Tipo: Improvement ou Epic
Título: Melhoria 1: Migração Python 3.10 → 3.12
Descrição: (copiar de MELHORIA-1-CHECKLIST-ATUALIZADO.md)
Labels: melhoria-1, python, migration
Priority: High
Estimation: 8 horas
```

### Passo 3: Adicionar Checklist na Issue

1. Abra a Issue criada
2. Clique em **Add** → **Checklist**
3. Crie manualmente ou importe:
   - Nome: `Melhoria 1: Python 3.12`
   - Copie as tarefas de `fipe-melhorias-checklist.json` → seção `melhoria-1-python-312`

### Passo 4: Estrutura de Issues

```
Epic: FipeDataStack Improvements v2.0
├── Issue 1: Melhoria 1 - Python 3.12 [8h]
│   └── Checklist (30+ items)
├── Issue 2: Melhoria 2 - Multi-Region [20h]
│   └── Checklist (40+ items)
├── Issue 3: Melhoria 3 - Observability [10h]
│   └── Checklist (35+ items)
└── Issue 4: Melhoria 4 - Webhooks [6.5h]
    └── Checklist (30+ items)
```

---

## Opção 2: Importar via API (Recomendado)

Se sua instância Jira suporta Script Runner ou webhooks:

### Passo 1: Preparar Dados

```bash
# Converter JSON para formato Jira REST API
jq '.checklists[] | {
  summary: .title,
  description: .description,
  customfield_checklist: .items
}' docs/fipe-melhorias-checklist.json > jira-import.json
```

### Passo 2: Criar Issues via API

```bash
for item in $(jq -r '.checklists[] | @base64' docs/fipe-melhorias-checklist.json); do
  CHECKLIST=$(echo $item | base64 -d)
  
  TITLE=$(echo $CHECKLIST | jq -r '.title')
  DESC=$(echo $CHECKLIST | jq -r '.description')
  
  curl -X POST \
    -H "Authorization: Bearer YOUR_JIRA_TOKEN" \
    -H "Content-Type: application/json" \
    https://jira.company.com/rest/api/3/issues \
    -d "{
      \"fields\": {
        \"project\": {\"key\": \"FIPE\"},
        \"summary\": \"$TITLE\",
        \"description\": \"$DESC\",
        \"issuetype\": {\"name\": \"Task\"},
        \"labels\": [\"melhoria\"],
        \"timeestimate\": ESTIMATED_SECONDS
      }
    }"
done
```

---

## Opção 3: Importar Manualmente (Step-by-Step)

### Para Melhoria 1: Python 3.10 → 3.12

**Issue:**
```
Título: Melhoria 1: Migração Python 3.10 → 3.12
Tipo: Improvement
Priority: High
Time Estimate: 8h
```

**Checklist Items (copiar para Issue):**

```
☐ PASSO 0: Preparação - Desativar auto-deploy
  ☐ Comentar push trigger em deploy-stage.yml
  ☐ Comentar push trigger em deploy-production.yml
  ☐ Criar backup de .github/workflows/
  ☐ Confirmar workflows não disparam automaticamente

☐ Etapa 1: Atualizar Python Version em Workflows
  ☐ Editar deploy-stage.yml - python-version: 3.12
  ☐ Editar deploy-production.yml - python-version: 3.12
  ☐ Commit: 'update: python version 3.10 -> 3.12 em workflows'

☐ Etapa 2: Atualizar fipe_api_stack.py - Lambda Runtime
  ☐ Localizar lambda_.Runtime.PYTHON_3_10
  ☐ Alterar para lambda_.Runtime.PYTHON_3_12
  ☐ Verificar todos os lambdas foram atualizados
  ☐ Commit: 'update: lambda runtime 3.10 -> 3.12 em fipe_api_stack.py'

... (continuar com demais itens)
```

### Para Melhoria 2: Multi-Region

```
Título: Melhoria 2: Arquitetura Multi-Região (sa-east-1)
Tipo: Improvement
Priority: High
Time Estimate: 20h
Subtasks:
  - STG - Etapa 1-5
  - PRD - Etapa 1-5
  - Cleanup
```

### Para Melhoria 3: Observability

```
Título: Melhoria 3: Observabilidade e Resiliência
Tipo: Improvement
Priority: Medium
Time Estimate: 10h
```

### Para Melhoria 4: Webhooks

```
Título: Melhoria 4: Webhooks para Notificação
Tipo: Improvement
Priority: Medium
Time Estimate: 6.5h
```

---

## Como Usar o Checklist no Jira

### Durante Desenvolvimento

1. **Abrir Issue** da melhoria
2. **Expandir Checklist** seção
3. **Verificar tarefas** conforme completa (`☑`)
4. **Deixar comentários** em tarefas específicas se necessário
5. **Atualizar status** da Issue conforme avança

### Rastreamento de Progresso

- Jira automaticamente calcula % completo do checklist
- Dashboard mostra progresso visual
- Progress bar indica quantas tarefas foram concluídas

### Exemplo:

```
Melhoria 1: Python 3.12 Migration
┌─────────────────────────────────────┐
│ Progress: 12/30 (40%) ████░░░░░░░  │
└─────────────────────────────────────┘

☑ PASSO 0: Preparação (4/4 concluídas)
☐ Etapa 1: Workflows (0/3 concluídas)
☐ Etapa 2: Lambda Runtime (0/4 concluídas)
... (continuar)
```

---

## Mapping do JSON para Jira

O arquivo JSON tem a seguinte estrutura:

```json
{
  "checklists": [
    {
      "id": "melhoria-1-python-312",
      "title": "Melhoria 1: ...",              // → Issue Summary
      "description": "...",                    // → Issue Description
      "estimatedHours": 8,                    // → Time Estimate
      "priority": "HIGH",                     // → Priority Field
      "items": [                              // → Checklist Items
        {
          "id": "m1-prep-0",
          "title": "PASSO 0: ...",            // → Checklist item
          "checked": false,                   // → Checkbox status
          "subtasks": [                       // → Nested items
            {
              "title": "...",
              "checked": false
            }
          ]
        }
      ]
    }
  ]
}
```

**Mapping para Jira:**

| JSON | Jira Field |
|------|-----------|
| `title` | Issue Summary |
| `description` | Issue Description |
| `estimatedHours` | Time Estimate (converter para segundos) |
| `priority` | Priority (High/Medium) |
| `items[].title` | Checklist Item Text |
| `items[].subtasks[]` | Nested Checklist Items |

---

## Dicas de Uso

### 1. Agrupar por Etapa

Se sua app permite, organize checklists por:
- **Preparação** (tarefas de setup)
- **Implementação** (código + testes)
- **Deploy** (STG + PRD)
- **Validação** (testes finais)

### 2. Usar Filtros no Board

```jql
project = FIPE AND labels = melhoria
project = FIPE AND status = "In Progress" AND labels = melhoria-3
project = FIPE AND checklist.progress < 100
```

### 3. Atribuições

Cada checklist pode ter dono:
- **Desenvolvimento:** Alexandre Defendi (melhoria-1 + 2)
- **QA:** Time de Testes (validação)
- **DevOps:** Time de Infra (deploy)

### 4. Timeline no Jira

```
Timeline Visual:
├─ Melhoria 1 (Python): 1 dia
├─ Melhoria 2 (Multi-Region): 2.5 dias
├─ Melhoria 3 (Observability): 1.25 dias
└─ Melhoria 4 (Webhooks): 0.8 dias

Total: ~5.5 dias de desenvolvimento
```

---

## Troubleshooting

### Problema: App não encontra arquivo JSON

**Solução:**
1. Validar JSON: `jq . docs/fipe-melhorias-checklist.json`
2. Se erro: corrigir JSON syntax
3. Re-upload para Jira

### Problema: Checklist items não aparecem

**Solução:**
1. Verificar que campo `customfield_checklist` existe em seu Jira
2. Criar manualmente primeiro item de checklist
3. Depois importar resto via API

### Problema: Encoding de caracteres (ç, ã, é)

**Solução:**
```bash
# Converter para UTF-8 se necessário
iconv -f ISO-8859-1 -t UTF-8 docs/fipe-melhorias-checklist.json > fipe-melhorias-checklist-utf8.json
```

---

## Próximos Passos

1. **Escolher opção de importação** (manual, API, ou app específica)
2. **Criar 4 Issues** (uma por melhoria)
3. **Adicionar checklists** às issues
4. **Configurar workflow** (To Do → In Progress → Done)
5. **Atribuir para time**
6. **Começar a trabalhar!** ✅

---

## Links Úteis

- **Checklist for Jira Cloud:** https://marketplace.atlassian.com/apps/1215521
- **Jira REST API Docs:** https://developer.atlassian.com/cloud/jira/rest/
- **JSON Validator:** https://jsonlint.com/

---

**Arquivo:** `docs/fipe-melhorias-checklist.json`  
**Tamanho:** ~50 KB  
**Formato:** JSON v1.0  
**Última atualização:** 2026-05-15
