import boto3
import os
import time

sqs = boto3.client("sqs")
ONE_HOUR_MS = 3600 * 1000

def handler(event, context):
    dlqs = os.environ["DLQ_URLS"].split(",")
    target_queues = os.environ["MAIN_QUEUE_URLS"].split(",")

    for dlq_url, main_url in zip(dlqs, target_queues):
        process_dlq(dlq_url, main_url)

def process_dlq(dlq_url, main_queue_url):
    while True:
        resp = sqs.receive_message(
            QueueUrl=dlq_url,
            MaxNumberOfMessages=10,
            MessageAttributeNames=["All"],
            AttributeNames=["All"],
            VisibilityTimeout=30,
            WaitTimeSeconds=0,
        )

        msgs = resp.get("Messages", [])
        if not msgs:
            return

        now_ms = int(time.time() * 1000)

        for msg in msgs:
            first_receive_ts = int(msg.get("Attributes", {}).get("ApproximateFirstReceiveTimestamp", now_ms))

            age_ms = now_ms - first_receive_ts
            if age_ms < ONE_HOUR_MS:
                continue  # ainda muito nova, deixar quieta

            # Reenviar para a fila principal
            sqs.send_message(
                QueueUrl=main_queue_url,
                MessageBody=msg["Body"],
                MessageAttributes=msg.get("MessageAttributes", {})
            )

            # Remover da DLQ
            sqs.delete_message(
                QueueUrl=dlq_url,
                ReceiptHandle=msg["ReceiptHandle"]
            )
