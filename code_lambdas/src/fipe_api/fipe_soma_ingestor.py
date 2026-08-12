# code_lambdas/src/fipe_api/fipe_soma_ingestor.py

import os
import logging
import boto3
from botocore.exceptions import ClientError
from logging_helper import log_structured

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def get_sqs_client(region):
    return boto3.client("sqs", region_name=region)

def forward_to_queue(sqs_client, queue_url, message_body, message_id):
    """Encaminha uma mensagem para uma fila SQS. Retorna True em sucesso."""
    try:
        sqs_client.send_message(
            QueueUrl=queue_url,
            MessageBody=message_body
        )
        logger.info(f"INGESTOR - Mensagem {message_id} encaminhada para {queue_url}")
        return True
    except ClientError as e:
        logger.error(f"INGESTOR - Falha ao encaminhar {message_id} para {queue_url}: {e}")
        return False

def lambda_handler(event, context):
    """
    Encaminha mensagens da fipe-price-queue (sa-east-1) para as filas SQS de
    STG e PRD. Não escreve em nenhum RDS local (sa-east-1 é create_rds=False) —
    quem grava e decide se dispara o webhook é FipeSomaIngestor-stg/-prd, cada
    um na sua própria região, de forma independente.

    Mensagens do tipo END_OF_RECORDS são encaminhadas como qualquer outra
    (o body é repassado como está) — não precisam de tratamento especial aqui.
    """
    sqs_url_stg = os.environ.get("SQS_URL_STG")
    sqs_url_prd = os.environ.get("SQS_URL_PRD")

    if not sqs_url_stg or not sqs_url_prd:
        error_msg = f"ERRO: SQS_URL_STG e SQS_URL_PRD são obrigatórios. STG={sqs_url_stg}, PRD={sqs_url_prd}"
        logger.error(error_msg)
        raise ValueError(error_msg)

    # Extrair regiões das URLs para criar clientes regionais
    # https://sqs.us-east-2.amazonaws.com/... → us-east-2
    region_stg = sqs_url_stg.split(".")[1]
    region_prd = sqs_url_prd.split(".")[1]

    sqs_stg = get_sqs_client(region_stg)
    sqs_prd = get_sqs_client(region_prd)

    records = event["Records"]
    logger.info(f"INGESTOR - Processando {len(records)} mensagens → STG ({region_stg}) + PRD ({region_prd})")

    batch_item_failures = []

    for record in records:
        message_id = record["messageId"]
        body = record["body"]

        ok_stg = forward_to_queue(sqs_stg, sqs_url_stg, body, message_id)
        ok_prd = forward_to_queue(sqs_prd, sqs_url_prd, body, message_id)

        if not ok_stg or not ok_prd:
            logger.warning(f"INGESTOR - Falha em pelo menos uma fila (msg {message_id}): STG={ok_stg}, PRD={ok_prd}")
            batch_item_failures.append({"itemIdentifier": message_id})

    success = len(records) - len(batch_item_failures)
    logger.info(f"INGESTOR - Concluído: {success}/{len(records)} sucesso, {len(batch_item_failures)} falhas")

    if len(batch_item_failures) == 0:
        log_structured("SUCCESS", "Mensagens encaminhadas via SQS para STG e PRD",
                     details={"total_messages": len(records), "regions": ["us-east-2", "us-east-1"]})
    else:
        log_structured("ERROR", "Falhas no encaminhamento de mensagens",
                     error_type="SQS_FORWARDING_FAILURE",
                     details={"failed_count": len(batch_item_failures), "total": len(records)})

    return {"batchItemFailures": batch_item_failures}
