#!/bin/bash

# Script para configurar webhooks iniciais no Parameter Store
# Uso: ./setup_webhooks.sh [stage]
# Exemplo: ./setup_webhooks.sh sa-east-1

set -e

STAGE=${1:-sa-east-1}
REGION=${2:-sa-east-1}

# Mapear stage para região
case $STAGE in
  sa-east-1)
    REGION="sa-east-1"
    WEBHOOK_URL="https://webhook.site/seu-id-unico-sa-east-1"
    ;;
  stg)
    REGION="us-east-2"
    WEBHOOK_URL="https://webhook.site/seu-id-unico-stg"
    ;;
  prd)
    REGION="us-east-1"
    WEBHOOK_URL="https://webhook.site/seu-id-unico-prd"
    ;;
  *)
    echo "Uso: $0 [sa-east-1|stg|prd]"
    exit 1
    ;;
esac

echo "=== Configurando webhooks para stage: $STAGE (região: $REGION) ==="

# Valor padrão para teste
WEBHOOK_CONFIG="{
  \"webhooks\": [
    {
      \"name\": \"test-webhook\",
      \"url\": \"$WEBHOOK_URL\",
      \"api_key\": \"test-key-$(date +%s)\"
    }
  ]
}"

echo "Criando Parameter Store: /fipe/webhooks/$STAGE"
echo "Webhook URL: $WEBHOOK_URL"

aws ssm put-parameter \
  --name "/fipe/webhooks/$STAGE" \
  --value "$WEBHOOK_CONFIG" \
  --type String \
  --region "$REGION" \
  --overwrite || {
    echo "❌ Erro ao criar Parameter Store"
    exit 1
  }

echo "✅ Parameter Store criado com sucesso"

# Validar
echo ""
echo "=== Validando configuração ==="
aws ssm get-parameter \
  --name "/fipe/webhooks/$STAGE" \
  --query 'Parameter.Value' \
  --output text \
  --region "$REGION" | jq . || {
    echo "❌ Erro ao validar Parameter Store"
    exit 1
  }

echo ""
echo "✅ Configuração validada com sucesso"
echo ""
echo "Próximo passo: Obter URL real do webhook em https://webhook.site"
echo "Depois, atualizar Parameter Store com a URL real:"
echo ""
echo "aws ssm put-parameter \\"
echo "  --name /fipe/webhooks/$STAGE \\"
echo "  --value '{\"webhooks\": [{\"name\": \"test-app\", \"url\": \"https://webhook.site/seu-id-real\", \"api_key\": \"test-key\"}]}' \\"
echo "  --overwrite \\"
echo "  --type String \\"
echo "  --region $REGION"
