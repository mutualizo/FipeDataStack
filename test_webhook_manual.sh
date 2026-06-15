#!/bin/bash

# Script para testar webhooks manualmente
# Uso: ./test_webhook_manual.sh

set -e

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║       Teste Manual de Webhooks - Melhoria 4                   ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# Configurações
STAGE="sa-east-1"
REGION="sa-east-1"
LAMBDA_NAME="FipeSomaNotifier"
PROFILE="mutualizo"

echo "📋 Configurações:"
echo "  Stage: $STAGE"
echo "  Região: $REGION"
echo "  Lambda: $LAMBDA_NAME"
echo ""

# ===================================================================
# PASSO 1: Obter URL do webhook.site
# ===================================================================
echo "🌐 PASSO 1: Criar webhook de teste"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "⚠️  AÇÃO MANUAL NECESSÁRIA:"
echo "  1. Abra https://webhook.site em seu navegador"
echo "  2. Copie a URL única gerada (ex: https://webhook.site/abc123def456)"
echo ""
read -p "Cole a URL do webhook.site aqui: " WEBHOOK_URL

if [[ -z "$WEBHOOK_URL" ]]; then
    echo "❌ Erro: URL não fornecida"
    exit 1
fi

echo "✅ URL do webhook: $WEBHOOK_URL"
echo ""

# ===================================================================
# PASSO 2: Configurar Parameter Store
# ===================================================================
echo "⚙️  PASSO 2: Configurar Parameter Store"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

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
aws ssm put-parameter \
  --name "/fipe/webhooks/$STAGE" \
  --value "$WEBHOOK_CONFIG" \
  --type String \
  --region "$REGION" \
  --profile "$PROFILE" \
  --overwrite || {
    echo "❌ Erro ao criar Parameter Store"
    exit 1
  }

echo "✅ Parameter Store criado"
echo ""

# ===================================================================
# PASSO 3: Validar Parameter Store
# ===================================================================
echo "✓ PASSO 3: Validar configuração"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

aws ssm get-parameter \
  --name "/fipe/webhooks/$STAGE" \
  --query 'Parameter.Value' \
  --output text \
  --region "$REGION" \
  --profile "$PROFILE" | jq .

echo ""
echo "✅ Parameter Store validado"
echo ""

# ===================================================================
# PASSO 4: Preparar payload de teste
# ===================================================================
echo "📄 PASSO 4: Preparar payload"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

REFERENCE_MONTH="2026-06"
RECORDS_TOTAL="45230"

TEST_PAYLOAD="{
  \"reference_month\": \"$REFERENCE_MONTH\",
  \"records_total\": $RECORDS_TOTAL
}"

echo "Payload de teste:"
echo "$TEST_PAYLOAD" | jq .
echo ""

# ===================================================================
# PASSO 5: Invocar Lambda
# ===================================================================
echo "⚡ PASSO 5: Invocar Lambda"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "Invocando Lambda: $LAMBDA_NAME"
aws lambda invoke \
  --function-name "$LAMBDA_NAME" \
  --payload "$TEST_PAYLOAD" \
  --region "$REGION" \
  --profile "$PROFILE" \
  response.json || {
    echo "❌ Erro ao invocar Lambda"
    exit 1
  }

echo "✅ Lambda invocada com sucesso"
echo ""

# ===================================================================
# PASSO 6: Mostrar resposta
# ===================================================================
echo "📊 PASSO 6: Resultado"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "Resposta da Lambda:"
cat response.json | jq . 2>/dev/null || cat response.json
echo ""

# ===================================================================
# PASSO 7: Verificar logs
# ===================================================================
echo "📋 PASSO 7: Verificar logs"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "Aguardando logs (10 segundos)..."
sleep 10

echo ""
echo "Últimos logs da Lambda:"
echo "(Procure por mensagens NOTIFIER)"
echo ""

aws logs tail "/aws/lambda/$LAMBDA_NAME" \
  --follow \
  --since 1m \
  --region "$REGION" \
  --profile "$PROFILE" \
  --max-items 50 || echo "⚠️  Logs não disponíveis ainda"

echo ""

# ===================================================================
# PASSO 8: Instruções finais
# ===================================================================
echo "✅ PASSO 8: Validação final"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "🔍 PRÓXIMOS PASSOS:"
echo ""
echo "1️⃣  Volte para webhook.site (https://webhook.site/$WEBHOOK_URL)"
echo "   Verifique se o POST chegou com:"
echo "   - Method: POST"
echo "   - Body: JSON com reference_month e records_total"
echo "   - Headers: X-API-Key"
echo ""
echo "2️⃣  Verifique CloudWatch Metrics:"
echo "   aws cloudwatch get-metric-statistics \\"
echo "     --namespace FipeDataStack \\"
echo "     --metric-name webhook_success_count \\"
echo "     --dimensions Name=WebhookName,Value=test-webhook Name=Stage,Value=sa-east-1 \\"
echo "     --statistics Sum \\"
echo "     --start-time 2026-06-15T00:00:00Z \\"
echo "     --end-time 2026-06-16T00:00:00Z \\"
echo "     --period 3600 \\"
echo "     --region $REGION \\"
echo "     --profile $PROFILE"
echo ""
echo "3️⃣  Teste falha (webhook inválido):"
echo "   ./test_webhook_failure.sh"
echo ""

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║                   ✅ Teste Concluído!                         ║"
echo "╚════════════════════════════════════════════════════════════════╝"
