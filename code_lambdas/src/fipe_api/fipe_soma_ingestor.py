# code_lambdas/src/fipe_api/fipe_soma_ingestor.py

import json
import os
import logging
import time
import psycopg2
import boto3
from datetime import datetime
from psycopg2 import sql
from get_db_password import get_db_password
from logging_helper import log_structured

# Configure logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# AWS Lambda client para invocar FipeSomaNotifier
lambda_client = boto3.client('lambda')

def get_db_connection():
    # ... (esta função permanece a mesma)
    host = os.environ.get("RDS_HOST")
    port = os.environ.get("RDS_PORT")
    database = os.environ.get("RDS_DATABASE")
    user = os.environ.get("RDS_USER")
    if not all([host, port, database, user]):
        raise ValueError("Variáveis de ambiente para conexão com o banco de dados não definidas")
    password = get_db_password()
    logger.info(f"INGESTOR-DBCONECT - Tentando conexão com o banco de dados: {host}:{port}/{database} como {user}")
    is_connected = False
    attempts = 1
    conn = None
    sleep_vl = 0.5
    while not is_connected and attempts < 8:
        try:
            conn = psycopg2.connect(host=host, port=port, dbname=database, user=user, password=password)
            is_connected = True
            logger.info("INGESTOR-DBCONECT - Conexão com o banco de dados estabelecida com sucesso")
            conn.autocommit = False
        except Exception as e:
            if attempts < 8:
                logger.warning(f"INGESTOR-DBCONECT - Erro de conexão com o banco de dados na tentativa {attempts}: {str(e)}")
                time.sleep(sleep_vl * attempts)
        attempts += 1
    return conn

# ... (funções get_or_create_... e insert_edit_model_value permanecem as mesmas) ...
def get_or_create_reference_id(conn, code, name):
    with conn.cursor() as cur:
        try:
            logger.info(f"INGESTOR-REFID - Verificando referência: {code}, name: {name}")
            cur.execute("SELECT id FROM public.fipe_reference_month WHERE code = %s", (code,))
            id_no = cur.fetchone()
            if bool(id_no):
                logger.info(f"INGESTOR-REFID - Referência encontrada com ID: {id_no[0]}")
                id_no = id_no[0]
            else:
                logger.info(f"Referência não encontrada, criando nova referência: {code}")
                cur.execute("INSERT INTO public.fipe_reference_month (code, name, create_date, create_uid, write_date, write_uid) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id", (code, name, datetime.now(), 1, datetime.now(), 1))
                id_no = cur.fetchone()[0]
                logger.info(f"INGESTOR-REFID - Referência criada com ID: {id_no}")
                conn.commit()
            return id_no
        except Exception as e:
            logger.error(f"INGESTOR-REFID - Erro ao verificar ou criar referência: {str(e)}")
            return None

def get_or_create_manufacturer(conn, manufacturer, manufacturer_code, vehicle_type):
    with conn.cursor() as cur:
        try:
            logger.info(f"INGESTOR-MANUFACT - Verificando fabricante: {manufacturer}, código: {manufacturer_code}, tipo: {vehicle_type}")
            cur.execute("SELECT id FROM public.fipe_vehicle_manufacturer WHERE name = %s AND code = %s AND vehicle_type = %s", 
                        (manufacturer, manufacturer_code, vehicle_type))
            result = cur.fetchone()
            if result:
                logger.info(f"INGESTOR-MANUFACT - Fabricante encontrado com ID: {result[0]}")
                return result[0]
            logger.info(f"INGESTOR-MANUFACT - Criando novo fabricante: {manufacturer}")
            cur.execute("INSERT INTO public.fipe_vehicle_manufacturer (name, code, vehicle_type, create_date, create_uid, write_date, write_uid, active) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id", 
                        (manufacturer, manufacturer_code, vehicle_type, datetime.now(), 1, datetime.now(), 1, True))
            manufacturer_id = cur.fetchone()[0]
            conn.commit()
            logger.info(f"INGESTOR-MANUFACT - Novo fabricante criado com ID: {manufacturer_id}")
            return manufacturer_id
        except Exception as e:
            conn.rollback()
            logger.error(f"INGESTOR-MANUFACT - Erro ao processar fabricante: {str(e)}")
            raise

def get_or_create_model(conn, model, model_code, manufacturer_id):
    with conn.cursor() as cur:
        try:
            logger.info(f"INGESTOR-MODEL - Verificando modelo: {model}, código: {model_code}, fabricante ID: {manufacturer_id}")
            cur.execute("SELECT id FROM public.fipe_vehicle_model WHERE name = %s AND code = %s AND manufacturer_id = %s", (str(model), str(model_code), manufacturer_id))
            result = cur.fetchone()
            if result:
                logger.info(f"INGESTOR-MODEL - Modelo encontrado com ID: {result[0]}")
                return result[0]
            logger.info(f"INGESTOR-MODEL - Criando novo modelo: {model}")
            cur.execute("INSERT INTO public.fipe_vehicle_model (name, code, manufacturer_id, create_date, create_uid, write_date, write_uid, active) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id", 
                        (str(model), str(model_code), manufacturer_id, datetime.now(), 1, datetime.now(), 1, True))
            model_id = cur.fetchone()[0]
            conn.commit()
            logger.info(f"INGESTOR-MODEL - Novo modelo criado com ID: {model_id}")
            return model_id
        except Exception as e:
            conn.rollback()
            logger.error(f"INGESTOR-MODEL - Erro ao processar modelo: {str(e)}")
            raise

def insert_edit_model_value(conn, data):
    with conn.cursor() as cur:
        try:
            logger.info(f"INGESTOR-INSERT - Inserindo valor do modelo: {data['model']} {data['model_year_code']}")
            fipe_value_str = str(data['fipe_value']).replace("R$ ", "").replace(".", "").replace(",", ".")
            fipe_value = float(fipe_value_str) if fipe_value_str else 0
            if fipe_value == 0:
                logger.warning(f"INGESTOR-INSERT - Valor Fipe é zero ou inválido para: {data['model']} {data['model_year_code']}. Verifique os dados de entrada.")
                data['active'] = False
                
            cur.execute("SELECT id FROM public.fipe_vehicle_model_value WHERE model_id = %s AND fipe_code = %s AND manufacture_year = %s AND reference_month_code = %s AND fuel_type = %s", (int(data['model_id']), str(data['fipe_code']), str(data['model_year_code']), str(data['reference_month_code']), str(data['fuel_type'])))
            existing_value = cur.fetchone()
            if existing_value:
                logger.info(f"INGESTOR-INSERT - Atualizando valor existente para: {data['model']} {data['model_year_code']}")
                cur.execute("UPDATE public.fipe_vehicle_model_value SET fipe_value = %s, reference_month_id = %s, write_date = %s WHERE id = %s", 
                            (fipe_value, int(data['reference_id']),datetime.now(), existing_value[0]))
            else:
                logger.info(f"INGESTOR-INSERT - Inserindo novo valor para: {data['model']} {data['model_year_code']}")
                cur.execute("INSERT INTO public.fipe_vehicle_model_value ( name, code, model_id, fipe_code, manufacturer_id, manufacture_year, reference_month, reference_month_code, reference_month_id, fipe_value, fuel_type, vehicle_type, active, create_date, create_uid, write_date, write_uid ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", 
                            (f"{data['model']} {data['model_year_code']}", str(data['model_code']), int(data['model_id']), str(data['fipe_code']), int(data['manufacturer_id']), str(data['model_year_code']), str(data['reference_month']), str(data['reference_month_code']), int(data['reference_id']), fipe_value, str(data['fuel_type']), int(data['vehicle_type']), data.get('active',True), datetime.now(), 1, datetime.now(), 1))
            conn.commit()
            logger.info(f"INGESTOR-INSERT - Valor do modelo processado com sucesso: {data['model']} {data['model_year_code']}")
        except Exception as e:
            conn.rollback()
            logger.error(f"INGESTOR-INSERT - Erro ao inserir/atualizar valor do modelo: {str(e)}")
            raise

def process_message(conn, record):
    """
    Processa uma única mensagem SQS. Retorna True em sucesso, False em falha.
    """
    message_id = record["messageId"]
    try:
        logger.info(f"INGESTOR - Processando mensagem: {message_id}")
        
        message_body = json.loads(record["body"])
            
        if message_body.get("tabela_referencia"):
            reference_table = message_body.get("tabela_referencia")
            for reference in reference_table:
                if reference.get("Codigo") and reference.get("Mes"):
                    logger.info(f"INGESTOR - Referência de tabela processada: {reference}")
                    get_or_create_reference_id(
                        conn, 
                        str(reference.get("Codigo")).strip(), 
                        str(reference.get("Mes")).strip()
                    )
        else:
            logger.info(f"INGESTOR - Conteúdo da mensagem: {json.dumps(message_body, ensure_ascii=False)[:500]}...")

            reference_id = get_or_create_reference_id(
                conn, 
                str(message_body.get("codigoTabelaReferencia", "")).strip(), 
                str(message_body.get("mesReferenciaAno", "")).strip()
            )                    
    
            data = {
                "manufacturer": message_body.get("manufacturer"),
                "manufacturer_code": message_body.get("manufacturer_code"),
                "model": message_body.get("model"),
                "model_code": message_body.get("model_code"),
                "model_year_code": message_body.get("model_year_code"),
                "reference_month": message_body.get("mesReferenciaAno"),
                "reference_month_code": message_body.get("codigoTabelaReferencia"),
                "reference_id": reference_id,
                "fipe_value": message_body.get("fipe_value"),
                "fipe_code": message_body.get("fipe_code"),
                "fuel_type": message_body.get("fuel_type"),
                "vehicle_type": message_body.get("vehicle_type"),
                "active": True
            }
            
            # Validação mais robusta
            required_keys = ['manufacturer', 'manufacturer_code', 'model', 'model_code', 'fipe_code', 'vehicle_type', 'reference_id']
            if any(data.get(key) is None or data.get(key) is False for key in required_keys):
                logger.error(f"INGESTOR - Dados obrigatórios ausentes na mensagem {message_id}. Dados recebidos: {data}")
                return False

            data['manufacturer_id'] = get_or_create_manufacturer(conn, data['manufacturer'], data['manufacturer_code'], data['vehicle_type'])
            data['model_id'] = get_or_create_model(conn, data['model'], data['model_code'], data['manufacturer_id'])
            insert_edit_model_value(conn, data)
            
            logger.info(f"INGESTOR - Mensagem {message_id} processada com sucesso")
        
        return True # Retorna sucesso
        
    except (KeyError, json.JSONDecodeError, ValueError) as e:
        logger.error(f"INGESTOR - Erro de dados ou decodificação na mensagem {message_id}: {str(e)}. Corpo da mensagem: {record.get('body')}")
        return False # Retorna falha
    except Exception as e:
        logger.error(f"INGESTOR - Erro inesperado ao processar mensagem {message_id}: {str(e)}")
        # Em caso de erro de banco, a transação já sofreu rollback nas funções auxiliares
        return False # Retorna falha

def invoke_webhook_notifier(reference_month, reference_month_code, records_count, stage_target):
    """
    Invoca a Lambda FipeSomaNotifier para disparar webhooks após sucesso do pipeline.

    Args:
        reference_month: mês de referência (ex: "2026-05")
        reference_month_code: código da tabela de referência FIPE (ex: "336")
        records_count: número de registros processados
        stage_target: 'stg' ou 'prd' (ambiente destino dos webhooks)
    """
    try:
        payload = {
            "reference_month": reference_month,
            "reference_month_code": reference_month_code,
            "records_total": records_count,
            "stage": stage_target
        }

        lambda_client.invoke(
            FunctionName=f"FipeSomaNotifier-{stage_target}",
            InvocationType="Event",  # Async invocation
            Payload=json.dumps(payload)
        )
        logger.info(f"INGESTOR - Webhook notifier invocado para stage={stage_target}, reference_month={reference_month}")
    except Exception as e:
        logger.error(f"INGESTOR - Erro ao invocar webhook notifier ({stage_target}): {str(e)}")


def lambda_handler(event, context):
    """
    Manipulador AWS Lambda para processar mensagens SQS e inserir dados no PostgreSQL.
    """
    logger.info("INGESTOR - Iniciando FipeSomaIngestor...")
    
    # #############################################################
    # INÍCIO DA MODIFICAÇÃO
    # #############################################################

    # Lista para armazenar os identificadores das mensagens que falharam
    batch_item_failures = []
    reference_month = None  # Será extraído da primeira mensagem de dados
    reference_month_code = None  # Código da tabela de referência FIPE (ex: "336")
    records_processed = 0  # Contador de registros processados
    end_of_records_received = False  # Flag para saber se recebeu END_OF_RECORDS

    logger.info(f"INGESTOR - Processando {len(event['Records'])} mensagens da fila SQS...")

    for record in event["Records"]:
        conn = None
        success = False
        try:
            # Verificar se é mensagem END_OF_RECORDS
            message_body = json.loads(record["body"])

            if message_body.get("type") == "END_OF_RECORDS":
                logger.info(f"INGESTOR - END_OF_RECORDS recebido para mês: {message_body.get('reference_month')}")
                end_of_records_received = True
                reference_month = message_body.get("reference_month")
                reference_month_code = message_body.get("reference_month_code")
                success = True  # Marca como sucesso (não é erro)
                continue

            # Para cada mensagem de dados, estabelecemos uma nova conexão para isolar as transações
            conn = get_db_connection()
            if conn:
                # Processa a mensagem. A função process_message agora retorna True/False.
                success = process_message(conn, record)

                # Se processou com sucesso, extrai o reference_month/reference_month_code da mensagem
                if success and reference_month is None:
                    try:
                        extracted_month = message_body.get("mesReferenciaAno")
                        if extracted_month:
                            reference_month = extracted_month
                            logger.info(f"INGESTOR - Reference month extraído: {reference_month}")
                    except Exception as e:
                        logger.warning(f"INGESTOR - Erro ao extrair reference_month: {str(e)}")
                if success and reference_month_code is None:
                    try:
                        extracted_code = message_body.get("codigoTabelaReferencia")
                        if extracted_code:
                            reference_month_code = extracted_code
                            logger.info(f"INGESTOR - Reference month code extraído: {reference_month_code}")
                    except Exception as e:
                        logger.warning(f"INGESTOR - Erro ao extrair reference_month_code: {str(e)}")

                # Incrementar contador de registros processados com sucesso
                if success:
                    records_processed += 1
            else:
                logger.error(f"INGESTOR - Falha ao obter conexão com o BD para a mensagem {record['messageId']}")
                # 'success' permanece False

        except json.JSONDecodeError as e:
            logger.error(f"INGESTOR - Erro ao decodificar JSON: {str(e)}")
            success = False

        except Exception as e:
            # Captura exceções que podem ocorrer fora do 'process_message' (ex: falha de conexão)
            logger.error(f"INGESTOR - Erro crítico no loop para a mensagem {record['messageId']}: {str(e)}")
            # 'success' permanece False

        finally:
            if conn:
                try:
                    conn.close()
                except Exception as e:
                    logger.error(f"INGESTOR - Erro ao fechar conexão para msg {record['messageId']}: {str(e)}")

        # Se o processamento da mensagem não foi bem-sucedido, adiciona seu ID à lista de falhas
        if not success:
            batch_item_failures.append({"itemIdentifier": record["messageId"]})
            logger.warning(f"INGESTOR - Mensagem {record['messageId']} marcada para reprocessamento.")

    total_failures = len(batch_item_failures)
    total_records = len(event["Records"])
    success_count = total_records - total_failures

    logger.info(f"INGESTOR - Processamento concluído: {success_count}/{total_records} mensagens processadas com sucesso.")

    own_region = os.environ.get("AWS_REGION", "unknown")
    if total_failures > 0:
        logger.warning(f"INGESTOR - {total_failures} mensagens falharam e serão reenviadas para a fila.")
        log_structured("ERROR", f"Falhas no processamento de mensagens em {own_region}",
                     error_type="DB_WRITE_FAILURE",
                     details={"failed_count": total_failures, "total": total_records, "region": own_region})
    else:
        log_structured("SUCCESS", f"Todos os dados foram persistidos no RDS em {own_region}",
                     details={"total_messages": total_records, "region": own_region})

    # ⚠️ WEBHOOK DISPARA APENAS QUANDO END_OF_RECORDS É RECEBIDO
    # Cada ingestor só dispara o SEU PRÓPRIO notifier (STAGE=stg em us-east-2
    # dispara FipeSomaNotifier-stg; STAGE=prd em us-east-1 dispara -prd). Não
    # dispara o do outro lado — cada região tem seu próprio RDS independente,
    # este ingestor não sabe (nem deveria decidir) se o outro lado teve sucesso.
    if end_of_records_received and reference_month and records_processed > 0 and total_failures == 0:
        own_stage = os.environ.get("STAGE", "")
        if own_stage in ("stg", "prd"):
            logger.info(f"INGESTOR - 🚀 FIM DO PIPELINE MENSAL - Disparando webhook para {own_stage}")
            logger.info(f"INGESTOR - Reference month: {reference_month} (code: {reference_month_code}), Total de registros: {records_processed}")
            invoke_webhook_notifier(reference_month, reference_month_code, records_processed, own_stage)
        else:
            logger.warning(f"INGESTOR - STAGE de ambiente desconhecido ('{own_stage}'), não sei qual webhook notifier invocar")
    elif end_of_records_received and total_failures > 0:
        logger.warning(f"INGESTOR - END_OF_RECORDS recebido, mas houve {total_failures} falhas no processamento")
        logger.warning(f"INGESTOR - Webhook NÃO será disparado (dados incompletos ou corrompidos)")
    elif not end_of_records_received:
        logger.info(f"INGESTOR - END_OF_RECORDS não recebido ainda (pipeline ainda em andamento)")

    # Retorna o dicionário contendo a lista de falhas.
    # A AWS Lambda usará isso para gerenciar o reprocessamento.
    return {
        "batchItemFailures": batch_item_failures
    }
    # #############################################################
    # FIM DA MODIFICAÇÃO
    # #############################################################