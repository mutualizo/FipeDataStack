import json
import os
import logging
import time
import boto3
import urllib3
from datetime import datetime

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ssm_client = boto3.client('ssm')
cloudwatch_client = boto3.client('cloudwatch')
http = urllib3.PoolManager()


def get_webhooks_config():
    """Busca configuração de webhooks do Parameter Store."""
    parameter_path = os.environ.get("WEBHOOK_PARAMETER_PATH")
    if not parameter_path:
        raise ValueError("WEBHOOK_PARAMETER_PATH não definida")

    try:
        response = ssm_client.get_parameter(Name=parameter_path)
        config = json.loads(response['Parameter']['Value'])
        logger.info(f"NOTIFIER - Configuração de webhooks carregada: {len(config.get('webhooks', []))} endpoint(s)")
        return config.get('webhooks', [])
    except Exception as e:
        logger.error(f"NOTIFIER - Erro ao buscar configuração de webhooks: {str(e)}")
        raise


def call_webhook(url, payload, api_key, webhook_name, stage):
    """Chama webhook com retry exponencial backoff (5s, 10s, 20s, 40s, 80s)."""
    timeout_sec = int(os.environ.get("WEBHOOK_TIMEOUT", "10"))
    max_retries = 5
    backoff_delays = [5, 10, 20, 40, 80]

    headers = {
        'Content-Type': 'application/json',
        'X-API-Key': api_key
    }
    body = json.dumps(payload)

    for attempt in range(max_retries):
        try:
            logger.info(f"NOTIFIER - Tentativa {attempt + 1}/{max_retries} para webhook '{webhook_name}' ({url})")

            response = http.request(
                'POST',
                url,
                body=body,
                headers=headers,
                timeout=urllib3.Timeout(connect=timeout_sec, read=timeout_sec)
            )

            if 200 <= response.status < 300:
                logger.info(f"NOTIFIER - Webhook '{webhook_name}' disparado com sucesso (status {response.status})")
                emit_metric("webhook_success_count", 1, webhook_name, stage)
                return True
            else:
                logger.warning(f"NOTIFIER - Webhook '{webhook_name}' retornou status {response.status}")
                if attempt < max_retries - 1:
                    delay = backoff_delays[attempt]
                    logger.info(f"NOTIFIER - Aguardando {delay}s antes de retentar...")
                    time.sleep(delay)

        except Exception as e:
            logger.warning(f"NOTIFIER - Erro ao chamar webhook '{webhook_name}': {str(e)}")
            if attempt < max_retries - 1:
                delay = backoff_delays[attempt]
                logger.info(f"NOTIFIER - Aguardando {delay}s antes de retentar...")
                time.sleep(delay)

    logger.error(f"NOTIFIER - Webhook '{webhook_name}' falhou após {max_retries} tentativas")
    emit_metric("webhook_failure_count", 1, webhook_name, stage)
    return False


def emit_metric(metric_name, value, webhook_name, stage):
    """Emite métrica customizada para CloudWatch."""
    try:
        cloudwatch_client.put_metric_data(
            Namespace='FipeDataStack',
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
        logger.info(f"NOTIFIER - Métrica '{metric_name}' emitida para CloudWatch")
    except Exception as e:
        logger.error(f"NOTIFIER - Erro ao emitir métrica: {str(e)}")


def lambda_handler(event, context):
    """Dispara webhooks para aplicações consumidoras."""
    logger.info("NOTIFIER - Iniciando FipeSomaNotifier...")

    stage = os.environ.get("STAGE", "unknown")

    try:
        reference_month = event.get('reference_month')
        records_total = event.get('records_total')

        if not reference_month:
            raise ValueError("'reference_month' é obrigatório no evento")

        logger.info(f"NOTIFIER - Disparando webhooks para referência '{reference_month}' com {records_total} registros")

        webhooks = get_webhooks_config()

        if not webhooks:
            logger.warning("NOTIFIER - Nenhum webhook configurado")
            return {
                'statusCode': 200,
                'body': json.dumps({'message': 'Nenhum webhook configurado'})
            }

        payload = {
            'type': 'WEBHOOK_NOTIFY',
            'pipeline': 'fipe_monthly_load',
            'reference_month': reference_month,
            'records_total': records_total,
            'timestamp': datetime.utcnow().isoformat(),
            'stage': stage
        }

        success_count = 0
        for webhook in webhooks:
            webhook_name = webhook.get('name', 'unknown')
            webhook_url = webhook.get('url')
            api_key = webhook.get('api_key', '')

            if not webhook_url:
                logger.warning(f"NOTIFIER - Webhook '{webhook_name}' sem URL configurada")
                continue

            if call_webhook(webhook_url, payload, api_key, webhook_name, stage):
                success_count += 1

        logger.info(f"NOTIFIER - {success_count}/{len(webhooks)} webhooks disparados com sucesso")

        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': f'{success_count}/{len(webhooks)} webhooks disparados',
                'reference_month': reference_month,
                'records_total': records_total
            })
        }

    except Exception as e:
        logger.error(f"NOTIFIER - Erro ao disparar webhooks: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }
