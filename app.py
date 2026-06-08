#!/usr/bin/env python3
"""
Stack Única em sa-east-1 com Encaminhamento SQS Cross-Region

Arquitetura Consolidada:
- 1 Stack em sa-east-1 (FipeDataStack, FipeApiStack)
- 4 Lambdas: FipeManufacturerLoader, FipeModelLoader, FipePriceLoader, FipeSomaIngestor
- 3 SQS Queues: manufacturer, model, price
- FipeSomaIngestor encaminha mensagens para soma-fipe-ingestor-stg (us-east-2)
  e soma-fipe-ingestor-prd (us-east-1), consumidas pelas stacks STG/PRD existentes
"""

import os
import sys
import boto3
from aws_cdk import App, Environment

from fipe_data_stack import FipeDataStack

# ============================================================================
# CONFIGURAÇÃO: Stack Única em sa-east-1
# ============================================================================

# Região fixa para stack única (consolida tudo em sa-east-1)
TARGET_REGION = "sa-east-1"

# URLs das filas SQS de ingestão nas stacks STG e PRD (encaminhamento cross-region)
SQS_FORWARDING_URLS = {
    "stg": os.environ.get(
        "SQS_URL_STG",
        "https://sqs.us-east-2.amazonaws.com/652510808251/fipe-price-queue-stg"
    ),
    "prd": os.environ.get(
        "SQS_URL_PRD",
        "https://sqs.us-east-1.amazonaws.com/652510808251/fipe-price-queue-prd"
    )
}

print("=" * 80)
print("FipeDataStack - Stack Única em sa-east-1")
print("=" * 80)
print(f"Região de Deploy: {TARGET_REGION}")
print(f"Fila de Preços STG (us-east-2): {SQS_FORWARDING_URLS['stg']}")
print(f"Fila de Preços PRD (us-east-1): {SQS_FORWARDING_URLS['prd']}")
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
            print("✅ Autenticação com perfil AWS bem-sucedida")
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

# Obter Slack Webhook URL do contexto CDK
slack_webhook_url = app.node.try_get_context("slack_webhook_url")
if slack_webhook_url:
    print(f"✅ Slack Webhook URL obtida do contexto CDK")
else:
    print("⚠️  Slack Webhook URL não definida - Lambda Slack Notifier não funcionará")

# Stack única em sa-east-1 (sem sufixo de stage)
print(f"Criando stack: FipeDataStack em {TARGET_REGION}")

FipeDataStack(
    app,
    "FipeDataStack",  # Nome sem sufixo - stack única
    env=env,
    stage="unified",  # Identificador interno (não afeta nomes dos recursos)
    create_rds=False,  # Não criar RDS - Lambdas encaminham via SQS
    sqs_forwarding_urls=SQS_FORWARDING_URLS,  # URLs das filas SQS STG e PRD
    slack_webhook_url=slack_webhook_url  # URL do webhook Slack
)

print("✅ Stack criada com sucesso")
print()

app.synth()