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

# Obter perfil AWS
aws_profile = os.environ.get('AWS_PROFILE')

if aws_profile:
    print(f"Usando perfil AWS: {aws_profile}")
    try:
        session = boto3.Session(profile_name=aws_profile)
        aws_account = session.client('sts').get_caller_identity().get('Account')

        if not aws_account:
            raise ValueError("Não foi possível obter a conta AWS")

        print(f"Conta AWS: {aws_account}")

    except ClientError as e:
        print(f"❌ Erro ao obter conta AWS: {str(e)}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Erro ao usar perfil AWS '{aws_profile}': {str(e)}")
        sys.exit(1)
else:
    # Usar variáveis de ambiente para credenciais
    aws_access_key_id = os.environ.get('AWS_ACCESS_KEY_ID')
    aws_secret_access_key = os.environ.get('AWS_SECRET_ACCESS_KEY')

    if aws_access_key_id and aws_secret_access_key:
        print("Usando credenciais AWS das variáveis de ambiente")
        boto3.setup_default_session(
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            region_name=TARGET_REGION
        )
        sts_client = boto3.client('sts')
        aws_account = sts_client.get_caller_identity().get('Account')
        print(f"Conta AWS: {aws_account}")
    else:
        print("❌ AWS_PROFILE não definido e credenciais de ambiente não encontradas")
        print("Por favor, defina AWS_PROFILE ou AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY")
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
    rds_endpoints=RDS_ENDPOINTS  # Endpoints dos RDS remotos
)

print("✅ Stack criada com sucesso")
print()

app.synth()