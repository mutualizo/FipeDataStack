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
lambda_client = boto3.client('lambda')


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


def call_webhook(url: str, payload: Dict, api_key: str, proxy_nonce: str, webhook_name: str, stage: str) -> bool:
    """
    Chama webhook com retry exponencial.

    Args:
        url: URL do webhook
        payload: Dados a enviar
        api_key: Token de autenticação
        proxy_nonce: Nonce do proxy (lido do Parameter Store, por webhook)
        webhook_name: Nome do webhook para logging
        stage: 'stg' ou 'prd'

    Returns:
        True se sucesso, False se falha após retries
    """
    timeout = int(os.environ.get("WEBHOOK_TIMEOUT", "30"))
    max_retries = 5
    retry_delays = [5, 10, 20, 40, 80]  # segundos

    headers = {
        "Content-Type": "application/json",
        "X-Webhook-Token": api_key,
        "proxy_nonce": proxy_nonce
    }

    for attempt in range(max_retries):
        try:
            logger.info(f"NOTIFIER - Tentativa {attempt + 1}/{max_retries} para {webhook_name} em {stage}")
            logger.info(f"NOTIFIER - URL sendo chamada: {url}")
            logger.info(f"NOTIFIER - Headers enviados: {json.dumps(headers)}")
            logger.info(f"NOTIFIER - Payload enviado: {json.dumps(payload)}")
            response = requests.post(url, json=payload, headers=headers, timeout=timeout)

            if response.status_code == 200:
                logger.info(f"NOTIFIER - Webhook {webhook_name} chamado com sucesso (status={response.status_code})")
                emit_metric("webhook_success_count", 1, webhook_name, stage)
                return True
            else:
                logger.warning(f"NOTIFIER - Webhook {webhook_name} retornou status {response.status_code}")
                logger.warning(f"NOTIFIER - Corpo da resposta: {response.text}")
                if attempt < max_retries - 1:
                    wait_time = retry_delays[attempt]
                    logger.info(f"NOTIFIER - Aguardando {wait_time}s antes de retry...")
                    import time
                    time.sleep(wait_time)
        except requests.exceptions.RequestException as e:
            logger.error(f"NOTIFIER - Erro ao chamar webhook {webhook_name}: {str(e)}")
            logger.error(f"NOTIFIER - Tipo de erro: {type(e).__name__}")
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


def dispatch_webhooks(event, context):
    """
    Modo despachante: invocado pelo FipeSomaIngestor ao final do pipeline.
    Não chama nenhum webhook diretamente - só lê a configuração e dispara
    uma invocação assíncrona independente por webhook (cada uma com seus
    próprios 5 minutos de timeout). Isso evita que webhooks no fim da lista
    nunca cheguem a ser tentados quando os anteriores já consomem o timeout
    inteiro com retries (5 tentativas x backoff exponencial cada).
    """
    reference_month = event.get("reference_month", False)
    reference_month_code = event.get("reference_month_code", False)
    records_total = event.get("records_total", 0)
    stage = event.get("stage", "stg")

    logger.info(f"NOTIFIER - Disparando webhooks para stage={stage}, reference_month={reference_month}, records={records_total}")

    config = get_webhooks_config(stage)
    webhooks = config.get("webhooks", [])

    if not webhooks:
        logger.warning(f"NOTIFIER - Nenhum webhook configurado para stage={stage}")
        return {
            "statusCode": 204,
            "body": json.dumps({"message": "No webhooks configured"})
        }

    function_name = context.function_name
    dispatched = 0
    for webhook in webhooks:
        name = webhook.get("name", "unnamed")
        if not webhook.get("url"):
            logger.warning(f"NOTIFIER - Webhook {name} sem URL configurada, pulando...")
            continue

        sub_event = {
            "webhook": webhook,
            "reference_month": reference_month,
            "reference_month_code": reference_month_code,
            "records_total": records_total,
            "stage": stage
        }
        try:
            lambda_client.invoke(
                FunctionName=function_name,
                InvocationType="Event",
                Payload=json.dumps(sub_event)
            )
            dispatched += 1
            logger.info(f"NOTIFIER - Despachada invocação isolada para o webhook {name}")
        except Exception as e:
            logger.error(f"NOTIFIER - Erro ao despachar invocação para {name}: {str(e)}")

    logger.info(f"NOTIFIER - {dispatched}/{len(webhooks)} webhooks despachados para execução isolada")
    return {
        "statusCode": 200,
        "body": json.dumps({
            "dispatched_webhooks": dispatched,
            "total_webhooks": len(webhooks),
            "reference_month": reference_month
        })
    }


def notify_single_webhook(event):
    """
    Modo base única: invocado pela própria FipeSomaNotifier (a partir do
    modo despachante) para tratar uma única base, isolada, com o timeout
    inteiro da Lambda disponível só para ela.
    """
    webhook = event["webhook"]
    stage = event.get("stage", "stg")
    name = webhook.get("name", "unnamed")
    url = webhook.get("url")
    api_key = webhook.get("api_key", "")
    proxy_nonce = webhook.get("proxy_nonce", "")

    payload = {
        "type": "WEBHOOK_NOTIFY",
        "pipeline": "fipe_monthly_load",
        "reference_month": event.get("reference_month") or "unknown",
        "reference_month_code": event.get("reference_month_code") or "unknown",
        "records_total": event.get("records_total", 0),
        "timestamp": datetime.utcnow().isoformat(),
        "stage": stage
    }

    if not url:
        logger.warning(f"NOTIFIER - Webhook {name} sem URL configurada")
        return {
            "statusCode": 400,
            "body": json.dumps({"webhook": name, "message": "URL não configurada"})
        }

    success = call_webhook(url, payload, api_key, proxy_nonce, name, stage)
    return {
        "statusCode": 200 if success else 502,
        "body": json.dumps({"webhook": name, "success": success})
    }


def lambda_handler(event, context):
    """
    Handler principal para disparar webhooks após sucesso do pipeline.

    Dois modos, diferenciados pela presença da chave "webhook" no evento:
    - Despachante (evento vindo do FipeSomaIngestor): {"reference_month": ...,
      "reference_month_code": ..., "records_total": ..., "stage": "stg"|"prd"}
    - Base única (evento vindo do próprio despachante, auto-invocação):
      inclui também "webhook": {"name", "url", "api_key", "proxy_nonce"}
    """
    logger.info(f"NOTIFIER - Handler iniciado com evento: {json.dumps(event)}")

    try:
        if event.get("webhook"):
            return notify_single_webhook(event)
        return dispatch_webhooks(event, context)
    except Exception as e:
        logger.error(f"NOTIFIER - Erro geral no handler: {str(e)}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
