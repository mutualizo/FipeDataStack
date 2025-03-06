#!/usr/bin/env python3
import os
import sys

import aws_cdk as cdk
from fipe_data_stack import FipeDataStack


# Verificar o estágio (dev, stg, prd)
if len(sys.argv) > 1 and sys.argv[1] in ['dev', 'stg', 'prd']:
    stage = sys.argv[1]
else:
    # Usar variável de ambiente ou padrão "dev"
    stage = os.environ.get('STACK_STAGE', 'dev')

aws_region = os.getenv('AWS_REGION', 'us-east-2')
aws_account = os.getenv('AWS_ACCOUNT', '672847879444')

print(f"Implantando no estágio: {stage}\nAccount: {aws_account} {aws_region}")


app = cdk.App()

FipeDataStack(
    app,
    f"FipeDataStack-{stage}",
    stage=stage,
    env=cdk.Environment(account=aws_account, region=aws_region),
)

app.synth()
