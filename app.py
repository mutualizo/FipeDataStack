#!/usr/bin/env python3
"""
MELHORIA 2: Stack Única em sa-east-1 com Dual-Write RDS

Arquitetura Consolidada:
- 1 Stack em sa-east-1 (FipeDataStack, FipeApiStack)
- 4 Lambdas: FipeManufacturerLoader, FipeModelLoader, FipePriceLoader, FipeSomaIngestor
- 3 SQS Queues: manufacturer, model, price (FIFO)
- RDS em us-east-2 (STG) e us-east-1 (PRD) recebem dual-write
"""

import os
import sys
import json
import boto3
from aws_cdk import App, Environment
from botocore.exceptions import ClientError

from fipe_data_stack import FipeDataStack

# ============================================================================
# CONFIGURAÇÃO: Stack Única em sa-east-1
# ============================================================================

# Região fixa para stack única (consolida tudo em sa-east-1)
TARGET_REGION = "sa-east-1"

# RDS endpoints (acessados remotamente, não criados nesta stack)
RDS_ENDPOINTS = {
    "stg": os.environ.get(
        "RDS_HOST_STG",
        "fipedatacluster-stg.cluster-cdqeius2qmwf.us-east-2.rds.amazonaws.com"
    ),
    "prd": os.environ.get(
        "RDS_HOST_PRD",
        "fipedatacluster-prd.cluster-chkg2mxlx9z0.us-east-1.rds.amazonaws.com"
    )
}

# RDS Secrets ARNs (para dual-write com senhas diferentes)
RDS_SECRETS_ARNS = {
    "stg": os.environ.get(
        "DB_SECRET_ARN_STG",
        "arn:aws:secretsmanager:us-east-2:652510808251:secret:FipeDataDBCredentialsstgC4F-hkhpoRdKCAHD-dKKCyY"
    ),
    "prd": os.environ.get(
        "DB_SECRET_ARN_PRD",
        "arn:aws:secretsmanager:us-east-1:652510808251:secret:FipeDataDBCredentialsprd092-RmQzIGkR41ce-wJyt0E"
    )
}

print("=" * 80)
print("[MELHORIA 2] FipeDataStack - Stack Única em sa-east-1")
print("=" * 80)
print(f"Região de Deploy: {TARGET_REGION}")
print(f"RDS STG (us-east-2): {RDS_ENDPOINTS['stg']}")
print(f"RDS PRD (us-east-1): {RDS_ENDPOINTS['prd']}")
print()

# ============================================================================
# AUTENTICAÇÃO AWS
# ============================================================================

# Estratégia de autenticação AWS
aws_profile = os.environ.get('AWS_PROFILE')  # Sem default
aws_account = None

# 1. Tentar usar perfil AWS se definido
if aws_profile:
    print(f"Tentando usar perfil AWS: {aws_profile}")
    try:
        session = boto3.Session(profile_name=aws_profile)
        aws_account = session.client('sts').get_caller_identity().get('Account')
        if aws_account:
            print(f"✅ Autenticação com perfil AWS bem-sucedida")
            print(f"Conta AWS: {aws_account}")
    except Exception as e:
        print(f"⚠️  Perfil AWS '{aws_profile}' falhou: {str(e)}")
        print("Tentando variáveis de ambiente...")
        aws_profile = None  # Tentar env vars

# 2. Fallback: usar variáveis de ambiente
if not aws_profile or not aws_account:
    aws_access_key_id = os.environ.get('AWS_ACCESS_KEY_ID')
    aws_secret_access_key = os.environ.get('AWS_SECRET_ACCESS_KEY')

    if aws_access_key_id and aws_secret_access_key:
        print("✅ Usando credenciais AWS das variáveis de ambiente")
        boto3.setup_default_session(
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            region_name=TARGET_REGION
        )
        try:
            sts_client = boto3.client('sts')
            aws_account = sts_client.get_caller_identity().get('Account')
            print(f"Conta AWS: {aws_account}")
        except Exception as e:
            print(f"❌ Erro ao obter conta AWS: {str(e)}")
            sys.exit(1)
    else:
        print("❌ Nenhum método de autenticação disponível")
        print("Defina AWS_PROFILE ou AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY")
        sys.exit(1)

# Validar
if not aws_account:
    print("❌ Não foi possível obter a conta AWS")
    sys.exit(1)

# ============================================================================
# CRIAR CDK APP E STACK
# ============================================================================

print()
app = App()
env = Environment(
    account=aws_account,
    region=TARGET_REGION
)

# Stack única em sa-east-1 (sem sufixo de stage)
print(f"Criando stack: FipeDataStack em {TARGET_REGION}")

FipeDataStack(
    app,
    "FipeDataStack",  # Nome sem sufixo - stack única
    env=env,
    stage="unified",  # Identificador interno (não afeta nomes dos recursos)
    create_rds=False,  # Não criar RDS - acessar remotamente
    rds_endpoints=RDS_ENDPOINTS,  # Endpoints dos RDS remotos
    rds_secrets_arns=RDS_SECRETS_ARNS  # ARNs das secrets para dual-write
)

print("✅ Stack criada com sucesso")
print()

app.synth()