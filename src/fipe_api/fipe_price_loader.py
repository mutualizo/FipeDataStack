import json
import requests
import os
import logging
import time
from fipe_api_service import FipeAPI

# Configuração do logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    fipe_api = FipeAPI()
    logger.info("Processing SQS messages...")
    output_queue_url = os.getenv("SQS_OUTPUT_URL")
    
    if not output_queue_url:
        logger.error("Variável de ambiente SQS_OUTPUT_URL não definida")
        return {
            "statusCode": 500,
            "body": json.dumps("Erro: SQS_OUTPUT_URL não definida"),
            "batchItemFailures": [{"itemIdentifier": record["messageId"]} for record in event["Records"]]
        }
    
    logger.info(f"Usando fila de saída: {output_queue_url}")

    batch = []
    batch_item_failures = []

    for record in event["Records"]:
        message_id = record["messageId"]
        try:
            message = json.loads(record["body"])
            logger.info(f"Message received: {message} (Message ID: {message_id})")

            # Ajuste das chaves
            reference_table_code = message["codigoTabelaReferencia"]
            vehicle_type = message["vehicle_type"]
            manufacturer_code = message["manufacturer_code"]
            model_code = message["model_code"]
            year_model = message.get("anoModelo", "Unknown")
            manufacturer_name = message.get("manufacturer", "Unknown")
            model_name = message.get("model", "Unknown")
            reference_month_name = message.get("mesReferenciaAno", "Desconhecido")

            retries = 2
            delay = 5
            success = False
            while retries > 0 and not success:
                try:
                    # Obtém os anos e tipos de combustível disponíveis
                    years, available_fuel_types = fipe_api.get_years(
                        manufacturer_code, model_code, vehicle_type
                    )

                    for year in years:
                        year_model = year.get("yearModel", "Unknown")
                        year_name = year.get("Label", "Unknown")
                        logger.info(f"Processing year: {year_model}, Label: {year_name}")

                        for fuel_type in available_fuel_types:
                            fuel_type_code = fuel_type.split("-")[-1] if "-" in fuel_type else fuel_type

                            logger.info(
                                f"Attempting to get price for fuel type: {fuel_type_code} (Year: {year_model}, Model: {model_name})"
                            )

                            price = fipe_api.get_price(
                                manufacturer_code,
                                model_code,
                                year_model,
                                vehicle_type,
                                fuel_type_code,
                            )

                            if price:
                                complete_data = {
                                    "manufacturer": manufacturer_name,
                                    "manufacturer_code": manufacturer_code,
                                    "model": model_name,
                                    "model_code": model_code,
                                    "model_year": year_name,
                                    "model_year_code": year_model,
                                    "fipe_value": price.get("Valor", ""),
                                    "fipe_code": price.get("CodigoFipe", ""),
                                    "fuel_type": fuel_type_code,
                                    "vehicle_type": vehicle_type,
                                    "mesReferenciaAno": reference_month_name,
                                    "codigoTabelaReferencia": reference_table_code,
                                }
                                logger.info(
                                    f"Data to be sent: {json.dumps(complete_data, indent=4, ensure_ascii=False)}"
                                )
                                batch.append(complete_data)
                    success = True
                    break

                except requests.HTTPError as e:
                    if hasattr(e, 'response') and e.response.status_code == 429:
                        logger.warning(
                            f"[429] - Rate limit exceeded. Waiting for {delay} seconds..."
                        )
                        time.sleep(delay)
                        retries -= 1
                        delay *= 2  # Exponential backoff
                    else:
                        logger.error(f"HTTP Error: {e}")
                        batch_item_failures.append({"itemIdentifier": message_id})
                        break

                except Exception as e:
                    logger.error(f"Error processing message: {e}")
                    batch_item_failures.append({"itemIdentifier": message_id})
                    break
            
            # Se esgotou as tentativas e ainda não teve sucesso
            if retries == 0 and not success:
                logger.error(f"Esgotadas as tentativas para a mensagem {message_id}")
                batch_item_failures.append({"itemIdentifier": message_id})
                
        except json.JSONDecodeError as e:
            logger.error(f"Erro ao decodificar mensagem JSON: {str(e)}")
            batch_item_failures.append({"itemIdentifier": message_id})
            
        except Exception as e:
            logger.error(f"Erro não tratado ao processar mensagem {message_id}: {str(e)}")
            batch_item_failures.append({"itemIdentifier": message_id})

    if batch:
        try:
            logger.info(f"Enviando lote com {len(batch)} mensagens para {output_queue_url}")
            failures = fipe_api.send_sqs_messages(output_queue_url, batch)  # Captura as falhas
            batch_item_failures.extend(failures)  # Adiciona as falhas à lista de falhas
            logger.info(f"Batch sent successfully.")
        except Exception as e:
            logger.error(f"Error sending batch to SQS: {e}")
            # Se falhar ao enviar o lote, marcar todas as mensagens do lote como falhas
            for record in event["Records"]:
                batch_item_failures.append({"itemIdentifier": record["messageId"]})

    total_failures = len(batch_item_failures)
    total_records = len(event["Records"])
    success_count = total_records - total_failures
    
    logger.info(f"Processamento concluído: {success_count}/{total_records} mensagens processadas com sucesso")
    
    if total_failures > 0:
        logger.warning(f"{total_failures} mensagens não puderam ser processadas")

    return {
        "statusCode": 200,
        "body": json.dumps("Processing completed successfully"),
        "batchItemFailures": batch_item_failures,
    }