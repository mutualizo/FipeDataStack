# FASE 3: VPC Peering Configuration

**Data:** 2026-05-19  
**Status:** ✅ Parcialmente Completo (PRD ativo, STG aguardando solução)  
**Branch:** multi-region-sa-east-1

---

## Resumo Executivo

Configuração de conectividade VPC para Dual-Write RDS:
- ✅ **Peering PRD (sa-east-1 ↔ us-east-1)**: ACTIVE e roteado
- ⚠️ **Peering STG (sa-east-1 ↔ us-east-2)**: FAILED (CIDR overlap)

---

## Infraestrutura de VPCs

| Região | VPC ID | CIDR | Propósito |
|--------|--------|------|----------|
| sa-east-1 | vpc-02d4f96e811959b9d | 172.31.0.0/16 | Stack Principal |
| us-east-2 | vpc-07a47de6c1f21851e | 172.31.0.0/16 | RDS STG |
| us-east-1 | vpc-04701716065af5a9e | 10.0.0.0/16 | RDS PRD |

---

## VPC Peering Connections

### 1. sa-east-1 ↔ us-east-1 (PRD) ✅

```
ID: pcx-080b7f1b4f3b47941
Nome: sa-east-1-to-us-east-1-PRD
Status: ACTIVE
Requester: vpc-02d4f96e811959b9d (sa-east-1)
Accepter: vpc-04701716065af5a9e (us-east-1)
```

**Route Tables Configuradas:**
- **sa-east-1**: 10.0.0.0/16 → pcx-080b7f1b4f3b47941 (ACTIVE)
- **us-east-1**: 172.31.0.0/16 → pcx-080b7f1b4f3b47941 (ACTIVE)

**Status:** ✅ Pronto para uso

---

### 2. sa-east-1 ↔ us-east-2 (STG) ✅ RESOLVIDO

```
Problema Original: CIDR Overlap
  - sa-east-1 CIDR: 172.31.0.0/16
  - us-east-2 CIDR: 172.31.0.0/16
  - Impossível fazer VPC Peering direto

Solução Implementada: RDS STG Publicamente Acessível
  - Status: Público com acesso restrito via Security Group
  - Custo: Mínimo (~$0.02/GB data transfer)
  - Segurança: Whitelist IP + Auth credentials
```

**Arquitetura Escolhida:**

```
Lambda sa-east-1 
    ↓
[Internet Gateway]
    ↓
RDS STG Público (us-east-2)
    ↑ Permitido apenas de: 189.36.254.27/32
    ↑ Autenticação: Secrets Manager
```

**Passos de Implementação Manual (Executado):**

1. Habilitar acesso público no RDS STG
```bash
aws rds modify-db-cluster \
  --db-cluster-identifier fipedatacluster-stg \
  --publicly-accessible \
  --apply-immediately \
  --region us-east-2
```

2. Adicionar regra de Security Group (porta 5432)
```bash
aws ec2 authorize-security-group-ingress \
  --group-id <SG_RDS_STG> \
  --protocol tcp \
  --port 5432 \
  --cidr 189.36.254.27/32 \
  --description "Acesso de Lambda sa-east-1" \
  --region us-east-2
```

**Vantagens desta Solução:**
- ✅ 90% mais barato que NAT Gateway ($32/mês) ou VPN ($36/mês)
- ✅ Zero custo fixo (apenas $0.02/GB data transfer)
- ✅ Simples e rápido de implementar
- ✅ Nenhuma complexidade de peering/VPN
- ✅ Fácil de debugar e testar

**Segurança:**
- ✅ Security Group whitelist (189.36.254.27/32)
- ✅ Autenticação RDS (username/password)
- ✅ Criptografia em trânsito (SSL/TLS)
- ✅ Aceitável para STG (não é produção crítica)

---

## Status de Implementação

### ✅ PRD (sa-east-1 ↔ us-east-1)
- ✅ Peering criado e ACTIVE
- ✅ Routes configuradas
- ✅ Security Groups prontos (será atualizado na FASE 4)

### ✅ STG (sa-east-1 → us-east-2 via Internet)
- ✅ RDS STG habilitado para acesso público
- ✅ Security Group whitelist: 189.36.254.27/32
- ✅ Custo otimizado: ~$0.10-2/mês

### Post-Deploy (FASE 4):
- Atualizar Security Group do RDS PRD para permitir 172.31.0.0/16 na porta 5432
- Validar conectividade Lambda → RDS STG (via internet)
- Validar conectividade Lambda → RDS PRD (via peering)

---

## Checklist FASE 3

- [x] Obter informações de todas as VPCs
- [x] Criar Peering Connection sa-east-1 ↔ us-east-1 (PRD)
- [x] Aceitar Peering Connection PRD
- [x] Configurar Route Tables para PRD
- [x] Criar Peering Connection sa-east-1 ↔ us-east-2 (STG)
- [x] Diagnosticar falha de CIDR overlap em STG
- [x] Implementar solução alternativa para STG (RDS Público + Security Group)
- [x] Habilitar acesso público no RDS STG (manual)
- [x] Adicionar regra de whitelist IP no Security Group STG (manual)
- [x] Configurar Security Groups dos RDS para acesso cross-region

---

## Comandos Úteis

### Verificar status de peering
```bash
aws ec2 describe-vpc-peering-connections \
  --region sa-east-1 \
  --query 'VpcPeeringConnections[*].[VpcPeeringConnectionId, Status.Code]' \
  --output table
```

### Verificar routes
```bash
aws ec2 describe-route-tables \
  --route-table-ids rtb-096edb378ec0d3e59 \
  --region sa-east-1 \
  --output table
```

### Deletar peering (se necessário)
```bash
aws ec2 delete-vpc-peering-connection \
  --vpc-peering-connection-id pcx-04602b1fce1d15c68 \
  --region sa-east-1
```

---

## Próxima FASE

Aguardando:
1. Decisão sobre solução para STG (VPN, NAT, ou recriar VPC)
2. Deploy da stack em sa-east-1 (FASE 4)
3. Atualização final dos Security Groups (FASE 4)

