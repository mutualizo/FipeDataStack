import json
import requests
import os
import logging
import time
from fipe_api_service import FipeAPI

# Configure logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    """
    Função Lambda para carregar modelos da API FIPE com base nos fabricantes recebidos via SQS.
    
    Esta função é acionada pela fila SQS de fabricantes, processa os dados de fabricantes,
    consulta a API FIPE para obter os modelos e os envia para a fila SQS de modelos.
    
    Args:
        event: Evento AWS Lambda com mensagens da fila SQS
        context: Contexto AWS Lambda
        
    Returns:
        dict: Resultado do processamento, incluindo eventuais falhas
    """
    logger.info("Iniciando FipeModelLoader...")
    
    try:
        fipe_api = FipeAPI()
        
        # Obter URLs das filas a partir das variáveis de ambiente
        output_queue_url = os.environ.get("SQS_OUTPUT_URL")
        
        if not output_queue_url:
            logger.error("Variável de ambiente SQS_OUTPUT_URL não definida")
            return {
                "statusCode": 500,
                "body": "Erro: SQS_OUTPUT_URL não definida",
                "batchItemFailures": [{"itemIdentifier": record["messageId"]} for record in event["Records"]]
            }
        
        logger.info(f"Usando fila de saída: {output_queue_url}")
        logger.info(f"Processando {len(event['Records'])} mensagens da fila SQS...")
        
        batch = []
        batch_item_failures = []
        
        for record in event["Records"]:
            message_id = record["messageId"]
            logger.info(f"Processando mensagem: {message_id}")
            
            try:
                message = json.loads(record["body"])
                logger.info(f"Conteúdo da mensagem: {json.dumps(message, ensure_ascii=False)}")
                
                brand_code = message.get("codigoMarca")
                vehicle_type = message.get("codigoTipoVeiculo")
                reference_table_code = message.get("codigoTabelaReferencia")
                reference_month_name = message.get("mesReferenciaAno", "Desconhecido")
                manufacturer_name = message.get("nomeMarca", "Unknown")
                
                # Validar dados obrigatórios
                if not all([brand_code, vehicle_type, reference_table_code]):
                    logger.error("Dados obrigatórios ausentes na mensagem")
                    batch_item_failures.append({"itemIdentifier": message_id})
                    continue
                
                # Log do tipo de veículo
                vehicle_type_map = {1: "Carro", 2: "Moto", 3: "Caminhão"}
                vehicle_type_name = vehicle_type_map.get(vehicle_type, "Desconhecido")
                logger.info(f"Consultando modelos para: {manufacturer_name} ({vehicle_type_name})")
                
                # Tentar obter os modelos com retry em caso de erro 429 (rate limit)
                retries = 2
                delay = 5  # Delay inicial em segundos
                
                while retries > 0:
                    try:
                        models = fipe_api.get_models(brand_code, vehicle_type)
                        
                        if not isinstance(models, dict):
                            logger.error(f"Resposta inesperada da API: {models}")
                            batch_item_failures.append({"itemIdentifier": message_id})
                            break
                        
                        model_list = models.get("Modelos", [])
                        if not isinstance(model_list, list):
                            logger.error(f"Campo 'Modelos' não é uma lista: {models}")
                            batch_item_failures.append({"itemIdentifier": message_id})
                            break
                        
                        logger.info(f"Encontrados {len(model_list)} modelos para {manufacturer_name}")
                        
                        for model in model_list:
                            model_code = model.get("Value", "Unknown")
                            model_name = model.get("Label", "Unknown")
                            
                            message_to_send = {
                                "manufacturer": manufacturer_name,
                                "manufacturer_code": brand_code,
                                "model": model_name,
                                "model_code": model_code,
                                "vehicle_type": vehicle_type,
                                "mesReferenciaAno": reference_month_name,
                                "codigoTabelaReferencia": reference_table_code,
                            }
                            
                            batch.append(message_to_send)
                            
                            # Enviar em lotes para evitar exceder limites
                            if len(batch) >= 10:
                                failures = fipe_api.send_sqs_messages(output_queue_url, batch)
                                batch_item_failures.extend(failures)
                                batch = []  # Limpar o lote após envio
                                
                                # Pequeno delay entre lotes para evitar throttling
                                time.sleep(0.5)
                        
                        # Mensagem processada com sucesso
                        break
                        
                    except requests.HTTPError as e:
                        if hasattr(e, 'response') and e.response.status_code == 429:
                            logger.warning(f"[429] - Rate limit excedido. Aguardando {delay} segundos...")
                            time.sleep(delay)
                            retries -= 1
                            delay *= 2  # Aumento exponencial do delay
                        else:
                            logger.error(f"Erro HTTP ao consultar modelos: {str(e)}")
                            batch_item_failures.append({"itemIdentifier": message_id})
                            break
                            
                    except Exception as e:
                        logger.error(f"Erro ao processar mensagem: {str(e)}")
                        batch_item_failures.append({"itemIdentifier": message_id})
                        break
                
                # Se esgotou as tentativas e ainda está no loop, adicionar à lista de falhas
                if retries == 0:
                    logger.error(f"Esgotadas as tentativas para a mensagem {message_id}")
                    batch_item_failures.append({"itemIdentifier": message_id})
            
            except json.JSONDecodeError as e:
                logger.error(f"Erro ao decodificar mensagem JSON: {str(e)}")
                batch_item_failures.append({"itemIdentifier": message_id})
                
            except Exception as e:
                logger.error(f"Erro não tratado ao processar mensagem {message_id}: {str(e)}")
                batch_item_failures.append({"itemIdentifier": message_id})
        
        # Enviar qualquer item restante no lote
        if batch:
            try:
                logger.info(f"Enviando lote final com {len(batch)} mensagens")
                failures = fipe_api.send_sqs_messages(output_queue_url, batch)
                batch_item_failures.extend(failures)
            except Exception as e:
                logger.error(f"Erro ao enviar lote final: {str(e)}")
                # Se falhar ao enviar o lote final, marcar todas as mensagens do lote como falhas
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
            "body": json.dumps("Processamento concluído"),
            "batchItemFailures": batch_item_failures,
        }
    
    except Exception as e:
        logger.error(f"Erro crítico no lambda_handler: {str(e)}")
        return {
            "statusCode": 500,
            "body": json.dumps(f"Erro: {str(e)}"),
            "batchItemFailures": [{"itemIdentifier": record["messageId"]} for record in event["Records"]],
        }