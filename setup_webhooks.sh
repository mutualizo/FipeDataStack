#!/bin/bash

# Script para configurar webhooks iniciais no AWS Systems Manager Parameter Store
# Uso: ./setup_webhooks.sh [stg|prd]

set -e

STAGE=${1:-stg}
REGION=""

case "$STAGE" in
    stg)
        REGION="us-east-2"
        ;;
    prd)
        REGION="us-east-1"
        ;;
    *)
        echo "Uso: $0 [stg|prd]"
        exit 1
        ;;
esac

echo "================================"
echo "Configurando webhooks para: $STAGE"
echo "Região: $REGION"
echo "================================"

# Configuração padrão com um webhook de teste (pode ser customizado)
WEBHOOK_CONFIG='{
  "webhooks": [
    {
      "name": "odoo-webhook",
      "url": "https://seu-odoo.example.com/api/fipe/webhook",
      "api_key": "seu-token-secreto-aqui"
    }
  ]
}'

PARAM_NAME="/fipe/webhooks/$STAGE"

echo "Criando Parameter Store: $PARAM_NAME"

aws ssm put-parameter \
  --name "$PARAM_NAME" \
  --value "$WEBHOOK_CONFIG" \
  --type "String" \
  --region "$REGION" \
  --overwrite \
  2>/dev/null && echo "✅ Parameter Store criado com sucesso" || echo "⚠️ Parameter pode já existir"

echo ""
echo "Verificando configuração..."
aws ssm get-parameter \
  --name "$PARAM_NAME" \
  --region "$REGION" \
  --query 'Parameter.Value' \
  --output text | jq '.' 2>/dev/null && echo "✅ Configuração verificada"

echo ""
echo "Para adicionar um novo webhook, execute:"
echo "aws ssm get-parameter --name $PARAM_NAME --region $REGION --query 'Parameter.Value' --output text > webhooks.json"
echo "# Edite webhooks.json e adicione novo webhook"
echo "aws ssm put-parameter --name $PARAM_NAME --value file://webhooks.json --overwrite --type String --region $REGION"
