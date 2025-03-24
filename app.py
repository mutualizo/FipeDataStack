#!/usr/bin/env python3
import os
import sys
import boto3
from aws_cdk import App, Environment
from botocore.exceptions import ClientError

from fipe_data_stack import FipeDataStack

# Verificar o estágio (dev, stg, prd)
if len(sys.argv) > 1 and sys.argv[1] in ['dev', 'stg', 'prd']:
    stage = sys.argv[1]
else:
    # Usar variável de ambiente ou padrão "dev"
    stage = os.environ.get('STACK_STAGE', 'dev')

print(f"Implantando no estágio: {stage}")

# Verificar se um perfil AWS específico foi fornecido
aws_profile = os.environ.get('AWS_PROFILE')
if not aws_profile:
    print("AWS_PROFILE não definido.")
    print("Por favor, defina a variável AWS_PROFILE com o nome do seu perfil AWS.")
    sys.exit(1)

print(f"Usando perfil AWS: {aws_profile}")

# Obter região e conta do perfil AWS
try:
    # Configurar boto3 com o perfil
    session = boto3.Session(profile_name=aws_profile)
    
    # Obter a região do perfil (ou usar a variável de ambiente como fallback)
    aws_region = os.environ.get('AWS_REGION') or os.environ.get('AWS_DEFAULT_REGION') or session.region_name
    if not aws_region:
        print("Região AWS não encontrada no perfil e AWS_REGION não está definido.")
        print("Por favor, defina a região no perfil AWS ou use a variável AWS_REGION.")
        sys.exit(1)
    
    # Obter a conta AWS do perfil
    try:
        aws_account = session.client('sts').get_caller_identity().get('Account')
        if not aws_account:
            raise ValueError("Não foi possível obter a conta AWS do perfil")
    except ClientError as e:
        print(f"Erro ao obter conta AWS do perfil: {str(e)}")
        print("Verifique se o perfil tem credenciais válidas.")
        sys.exit(1)
    
except Exception as e:
    print(f"Erro ao usar perfil AWS '{aws_profile}': {str(e)}")
    print("Verifique se o perfil existe e tem credenciais válidas.")
    sys.exit(1)

print(f"Região AWS: {aws_region}")
print(f"Conta AWS: {aws_account}")

# Criar o app e o stack com ambiente específico
app = App()
env = Environment(
    account=aws_account,
    region=aws_region
)

# Criar stack com o estágio especificado
# O FipeApiStack será criado como um stack filho dentro do FipeDataStack
FipeDataStack(app, f"FipeDataStack-{stage}", env=env, stage=stage)

app.synth()