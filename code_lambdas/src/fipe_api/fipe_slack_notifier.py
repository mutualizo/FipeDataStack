import json
import os
import logging
import urllib3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

http = urllib3.PoolManager()


def lambda_handler(event, context):
    """
    Recebe eventos do SNS e envia notificações formatadas ao Slack.
    """
    slack_webhook_url = os.environ.get("SLACK_WEBHOOK_URL")

    if not slack_webhook_url:
        logger.error("SLACK_NOTIFIER - SLACK_WEBHOOK_URL não definida")
        return {
            "statusCode": 500,
            "body": json.dumps("Erro: SLACK_WEBHOOK_URL não definida"),
        }

    try:
        # Extrair mensagem do SNS
        sns_message = json.loads(event["Records"][0]["Sns"]["Message"])
        subject = event["Records"][0]["Sns"].get("Subject", "Alerta FipeDataStack")

        # Formatar mensagem para Slack
        slack_message = format_slack_message(subject, sns_message)

        # Enviar para Slack
        encoded_msg = json.dumps(slack_message).encode("utf-8")
        response = http.request(
            "POST",
            slack_webhook_url,
            body=encoded_msg,
            headers={"Content-Type": "application/json"},
        )

        if response.status == 200:
            logger.info(f"SLACK_NOTIFIER - Mensagem enviada com sucesso: {subject}")
            return {"statusCode": 200, "body": json.dumps("Mensagem enviada para Slack")}
        else:
            logger.error(
                f"SLACK_NOTIFIER - Erro ao enviar para Slack (status {response.status}): {response.data}"
            )
            return {
                "statusCode": response.status,
                "body": json.dumps(f"Erro ao enviar para Slack: {response.data}"),
            }

    except Exception as e:
        logger.error(f"SLACK_NOTIFIER - Erro ao processar evento: {str(e)}")
        return {
            "statusCode": 500,
            "body": json.dumps(f"Erro ao processar evento: {str(e)}"),
        }


def format_slack_message(subject, alarm_data):
    """
    Formata uma mensagem de alerta CloudWatch para o Slack.
    """
    # Extrair informações do alerta CloudWatch
    alarm_name = alarm_data.get("AlarmName", "Alerta Desconhecido")
    new_state = alarm_data.get("NewStateValue", "UNKNOWN")
    state_reason = alarm_data.get("StateChangeReason", "Sem motivo fornecido")
    region = alarm_data.get("Region", "us-east-1")

    # Determinar cor baseado no estado
    color = "#FF0000" if new_state == "ALARM" else "#FFAA00"  # Vermelho para ALARM, Laranja para WARNING

    slack_payload = {
        "text": f"🚨 Alerta FipeDataStack: {alarm_name}",
        "attachments": [
            {
                "color": color,
                "title": alarm_name,
                "fields": [
                    {"title": "Estado", "value": new_state, "short": True},
                    {"title": "Região", "value": region, "short": True},
                    {
                        "title": "Motivo",
                        "value": state_reason,
                        "short": False,
                    },
                ],
                "footer": "FipeDataStack Alerts",
                "ts": int(__import__("time").time()),
            }
        ],
    }

    return slack_payload
