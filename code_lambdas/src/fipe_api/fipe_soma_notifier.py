import json
import os
import logging
import requests
import boto3
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ssm_client = boto3.client('ssm')
cloudwatch_client = boto3.client('cloudwatch')


def get_webhooks_config(stage: str) -> Dict:
    """
    Busca configuração de webhooks do Parameter Store.

    Args:
        stage: 'stg' ou 'prd'

    Returns:
        Dict com lista de webhooks ou dict vazio se não encontrado
    """
    try:
        param_name = f"/fipe/webhooks/{stage}"
        response = ssm_client.get_parameter(Name=param_name)
        config = json.loads(response['Parameter']['Value'])
        logger.info(f"NOTIFIER - Config carregada de {param_name}: {len(config.get('webhooks', []))} webhook(s)")
        return config
    except ssm_client.exceptions.ParameterNotFound:
        logger.warning(f"NOTIFIER - Parameter {param_name} não encontrado no SSM")
        return {"webhooks": []}
    except Exception as e:
        logger.error(f"NOTIFIER - Erro ao buscar config SSM: {str(e)}")
        return {"webhooks": []}


def call_webhook(url: str, payload: Dict, api_key: str, webhook_name: str, stage: str) -> bool:
    """
    Chama webhook com retry exponencial.

    Args:
        url: URL do webhook
        payload: Dados a enviar
        api_key: Token de autenticação
        webhook_name: Nome do webhook para logging
        stage: 'stg' ou 'prd'

    Returns:
        True se sucesso, False se falha após retries
    """
    timeout = int(os.environ.get("WEBHOOK_TIMEOUT", "10"))
    max_retries = 5
    retry_delays = [5, 10, 20, 40, 80]  # segundos

    headers = {
        "Content-Type": "application/json",
        "X-Webhook-Token": api_key
    }

    for attempt in range(max_retries):
        try:
            logger.info(f"NOTIFIER - Tentativa {attempt + 1}/{max_retries} para {webhook_name} em {stage}")
            response = requests.post(url, json=payload, headers=headers, timeout=timeout)

            if response.status_code == 200:
                logger.info(f"NOTIFIER - Webhook {webhook_name} chamado com sucesso (status={response.status_code})")
                emit_metric("webhook_success_count", 1, webhook_name, stage)
                return True
            else:
                logger.warning(f"NOTIFIER - Webhook {webhook_name} retornou status {response.status_code}")
                if attempt < max_retries - 1:
                    wait_time = retry_delays[attempt]
                    logger.info(f"NOTIFIER - Aguardando {wait_time}s antes de retry...")
                    import time
                    time.sleep(wait_time)
        except requests.exceptions.RequestException as e:
            logger.error(f"NOTIFIER - Erro ao chamar webhook {webhook_name}: {str(e)}")
            if attempt < max_retries - 1:
                wait_time = retry_delays[attempt]
                logger.info(f"NOTIFIER - Aguardando {wait_time}s antes de retry...")
                import time
                time.sleep(wait_time)

    logger.error(f"NOTIFIER - Webhook {webhook_name} falhou após {max_retries} tentativas")
    emit_metric("webhook_failure_count", 1, webhook_name, stage)
    return False


def emit_metric(metric_name: str, value: float, webhook_name: str, stage: str) -> None:
    """
    Emite métrica para CloudWatch.

    Args:
        metric_name: Nome da métrica (webhook_success_count ou webhook_failure_count)
        value: Valor a registrar
        webhook_name: Nome do webhook para dimensão
        stage: Stage para dimensão ('stg' ou 'prd')
    """
    try:
        cloudwatch_client.put_metric_data(
            Namespace="FipeWebhooks",
            MetricData=[
                {
                    'MetricName': metric_name,
                    'Value': value,
                    'Unit': 'Count',
                    'Timestamp': datetime.utcnow(),
                    'Dimensions': [
                        {'Name': 'WebhookName', 'Value': webhook_name},
                        {'Name': 'Stage', 'Value': stage}
                    ]
                }
            ]
        )
        logger.info(f"NOTIFIER - Métrica {metric_name} emitida para {webhook_name}")
    except Exception as e:
        logger.error(f"NOTIFIER - Erro ao emitir métrica: {str(e)}")


def lambda_handler(event, context):
    """
    Handler principal para disparar webhooks após sucesso do pipeline.

    Evento esperado:
    {
        "reference_month": "2026-05",
        "records_total": 45230,
        "stage": "stg" ou "prd"
    }
    """
    logger.info(f"NOTIFIER - Handler iniciado com evento: {json.dumps(event)}")

    try:
        # Extrair dados do evento
        reference_month = event.get("reference_month")
        records_total = event.get("records_total", 0)
        stage = event.get("stage", "stg")

        if not reference_month:
            logger.error("NOTIFIER - reference_month não fornecido no evento")
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "reference_month is required"})
            }

        logger.info(f"NOTIFIER - Disparando webhooks para stage={stage}, reference_month={reference_month}, records={records_total}")

        # Carregar configuração de webhooks
        config = get_webhooks_config(stage)
        webhooks = config.get("webhooks", [])

        if not webhooks:
            logger.warning(f"NOTIFIER - Nenhum webhook configurado para stage={stage}")
            return {
                "statusCode": 204,
                "body": json.dumps({"message": "No webhooks configured"})
            }

        # Preparar payload
        payload = {
            "type": "WEBHOOK_NOTIFY",
            "pipeline": "fipe_monthly_load",
            "reference_month": reference_month,
            "records_total": records_total,
            "timestamp": datetime.utcnow().isoformat(),
            "stage": stage
        }

        # Disparar para cada webhook
        successful_webhooks = 0
        for webhook in webhooks:
            name = webhook.get("name", "unnamed")
            url = webhook.get("url")
            api_key = webhook.get("api_key", "")

            if not url:
                logger.warning(f"NOTIFIER - Webhook {name} sem URL configurada, pulando...")
                continue

            if call_webhook(url, payload, api_key, name, stage):
                successful_webhooks += 1

        logger.info(f"NOTIFIER - Processamento concluído: {successful_webhooks}/{len(webhooks)} webhooks bem-sucedidos")

        return {
            "statusCode": 200,
            "body": json.dumps({
                "successful_webhooks": successful_webhooks,
                "total_webhooks": len(webhooks),
                "reference_month": reference_month
            })
        }

    except Exception as e:
        logger.error(f"NOTIFIER - Erro geral no handler: {str(e)}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
