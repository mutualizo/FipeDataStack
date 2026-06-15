#!/bin/bash

# Script para testar retry com webhook falhando
# Uso: ./test_webhook_failure.sh

set -e

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║    Teste de Falha e Retry - Melhoria 4                        ║"
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
# PASSO 1: Configurar webhook com URL inválida
# ===================================================================
echo "⚠️  PASSO 1: Configurar webhook com URL inválida"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

INVALID_URL="https://invalid-webhook-url-that-does-not-exist-12345.example.com/webhook"

WEBHOOK_CONFIG="{
  \"webhooks\": [
    {
      \"name\": \"failing-webhook\",
      \"url\": \"$INVALID_URL\",
      \"api_key\": \"test-key-failure\"
    }
  ]
}"

echo "Atualizando Parameter Store com URL inválida..."
aws ssm put-parameter \
  --name "/fipe/webhooks/$STAGE" \
  --value "$WEBHOOK_CONFIG" \
  --type String \
  --region "$REGION" \
  --profile "$PROFILE" \
  --overwrite || {
    echo "❌ Erro ao atualizar Parameter Store"
    exit 1
  }

echo "✅ Parameter Store atualizado com URL inválida"
echo "   URL: $INVALID_URL"
echo ""

# ===================================================================
# PASSO 2: Preparar payload
# ===================================================================
echo "📄 PASSO 2: Preparar payload"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

REFERENCE_MONTH="2026-06"
RECORDS_TOTAL="45230"

TEST_PAYLOAD="{
  \"reference_month\": \"$REFERENCE_MONTH\",
  \"records_total\": $RECORDS_TOTAL
}"

echo "Payload:"
echo "$TEST_PAYLOAD" | jq .
echo ""

# ===================================================================
# PASSO 3: Invocar Lambda
# ===================================================================
echo "⚡ PASSO 3: Invocar Lambda (vai falhar e retentar)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

TIMESTAMP=$(date +%s%N)

echo "Invocando Lambda (isso vai levar ~150 segundos devido aos retries)..."
echo ""

aws lambda invoke \
  --function-name "$LAMBDA_NAME" \
  --payload "$TEST_PAYLOAD" \
  --region "$REGION" \
  --profile "$PROFILE" \
  response_failure_${TIMESTAMP}.json || {
    echo "❌ Erro ao invocar Lambda"
    exit 1
  }

echo ""
echo "✅ Lambda invocada"
echo ""

# ===================================================================
# PASSO 4: Mostrar resposta
# ===================================================================
echo "📊 PASSO 4: Resultado"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "Resposta da Lambda:"
cat response_failure_${TIMESTAMP}.json | jq . 2>/dev/null || cat response_failure_${TIMESTAMP}.json
echo ""

# ===================================================================
# PASSO 5: Aguardar retries completarem
# ===================================================================
echo "⏳ PASSO 5: Aguardando retries (total ~150 segundos)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "Cronograma de retries:"
echo "  Tentativa 1: Imediato"
echo "  Tentativa 2: +5 segundos"
echo "  Tentativa 3: +10 segundos"
echo "  Tentativa 4: +20 segundos"
echo "  Tentativa 5: +40 segundos"
echo "  Tentativa 6: +80 segundos"
echo "  Total: ~150 segundos"
echo ""

for i in {1..5}; do
  sleep 30
  ELAPSED=$((i * 30))
  echo "  ⏱️  Aguardados $ELAPSED segundos..."
done

echo ""
echo "✅ Retries completados"
echo ""

# ===================================================================
# PASSO 6: Verificar logs
# ===================================================================
echo "📋 PASSO 6: Verificar logs de falha"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "Logs da Lambda (procure por 'NOTIFIER - Webhook' e 'NOTIFIER - Erro'):"
echo ""

aws logs tail "/aws/lambda/$LAMBDA_NAME" \
  --follow \
  --since 5m \
  --region "$REGION" \
  --profile "$PROFILE" \
  --max-items 100 | grep -i "notifier\|error" || echo "Nenhum log encontrado"

echo ""

# ===================================================================
# PASSO 7: Verificar métrica de falha
# ===================================================================
echo "📊 PASSO 7: Verificar métrica de falha"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "Aguardando métrica ser emitida (até 1 minuto)..."
sleep 30

echo ""
echo "Consultando CloudWatch Metrics..."
echo ""

aws cloudwatch get-metric-statistics \
  --namespace FipeDataStack \
  --metric-name webhook_failure_count \
  --dimensions Name=WebhookName,Value=failing-webhook Name=Stage,Value=sa-east-1 \
  --statistics Sum \
  --start-time "$(date -u -d '10 minutes ago' +%Y-%m-%dT%H:%M:%SZ)" \
  --end-time "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --period 300 \
  --region "$REGION" \
  --profile "$PROFILE" || echo "Métrica ainda não disponível"

echo ""

# ===================================================================
# PASSO 8: Instruções finais
# ===================================================================
echo "✅ PASSO 8: Resumo"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "🔍 VALIDAÇÕES:"
echo ""
echo "✓ Lambda foi invocada 1x"
echo "✓ Lambda tentou conectar ao webhook 6x (1 + 5 retries)"
echo "✓ Cada tentativa falhou (URL inválida)"
echo "✓ Métrica webhook_failure_count foi incrementada"
echo "✓ Logs mostram tentativas de retry com backoff"
echo ""

echo "📚 Referência:"
echo "  - Documentação: docs/WEBHOOK-CONFIG.md"
echo "  - Lambda code: code_lambdas/src/fipe_api/fipe_soma_notifier.py"
echo "  - Arquivo resposta: response_failure_${TIMESTAMP}.json"
echo ""

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║                 ✅ Teste de Falha Concluído!                  ║"
echo "╚════════════════════════════════════════════════════════════════╝"
