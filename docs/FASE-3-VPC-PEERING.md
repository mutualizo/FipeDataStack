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

### 2. sa-east-1 ↔ us-east-2 (STG) ⚠️

```
ID: pcx-04602b1fce1d15c68
Nome: sa-east-1-to-us-east-2-STG
Status: FAILED
Motivo: Overlapping CIDR - ambas VPCs usam 172.31.0.0/16
Requester: vpc-02d4f96e811959b9d (sa-east-1)
Accepter: vpc-07a47de6c1f21851e (us-east-2)
```

**Problema:** Não é possível fazer VPC Peering entre VPCs com CIDRs sobrepostos.

**Soluções Alternativas:**

#### Opção A: VPN Site-to-Site (Recomendado para Produção)
```bash
# Criar VPN Customer Gateway em sa-east-1
# Criar VPN Virtual Private Gateway em us-east-2
# Estabelecer tunel VPN criptografado
aws ec2 create-customer-gateway \
  --type ipsec.1 \
  --public-ip <IP-PUBLICA-SA-EAST-1> \
  --bgp-asn 65000 \
  --region us-east-2

# Habilita rota via VPN
```

#### Opção B: NAT Gateway + Elastic IP (Mais simples para Dev/Test)
- Criar NAT Gateway em sa-east-1
- Rotear tráfego RDS STG através de NAT
- Usar IP elástico do NAT nas security groups do RDS STG

#### Opção C: AWS PrivateLink ou Recriar VPC com CIDR diferente
- Mais complexo, requer redesign

---

## Próximas Ações

### Para PRD (Ativo):
- ✅ Peering criado e ACTIVE
- ✅ Routes configuradas
- ⏳ Security Groups do RDS serão atualizados após deploy (FASE 4)

### Para STG (CIDR Overlap):
1. **Imediato:** Avaliar qual solução usar (VPN, NAT Gateway, ou recriar VPC)
2. **Recomendação:** Usar NAT Gateway para dev/test
3. **Implementar:** Criar NAT Gateway em sa-east-1 e rotear para us-east-2 via NAT

### Post-Deploy (FASE 4):
- Adicionar regras de ingresso nos Security Groups dos RDS
  - PRD: Permitir 172.31.0.0/16 na porta 5432 (de sa-east-1)
  - STG: Permitir acesso via NAT IP na porta 5432

---

## Checklist FASE 3

- [x] Obter informações de todas as VPCs
- [x] Criar Peering Connection sa-east-1 ↔ us-east-1 (PRD)
- [x] Aceitar Peering Connection PRD
- [x] Configurar Route Tables para PRD
- [x] Criar Peering Connection sa-east-1 ↔ us-east-2 (STG)
- [x] Diagnosticar falha de CIDR overlap em STG
- [ ] Implementar solução alternativa para STG (VPN ou NAT Gateway)
- [ ] Configurar Security Groups dos RDS (após criação em FASE 4)

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

