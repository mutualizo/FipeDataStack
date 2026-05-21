# code_lambdas/src/fipe_api/fipe_soma_ingestor.py

import json
import os
import logging
import time
import psycopg2
from datetime import datetime
from psycopg2 import sql
from get_db_password import get_db_auth_token

# Configure logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def get_db_connection(host=None, max_total_wait=60):
    """Conecta a um banco de dados PostgreSQL com backoff exponencial.

    Args:
        host: Se None, usa RDS_HOST da variável de ambiente (para local/STG)
              Se fornecido, conecta a esse host específico (para dual-write)
        max_total_wait: Tempo máximo total (segundos) para retry (padrão: 60s)
    """
    MAX_ATTEMPTS = 6

    if host is None:
        host = os.environ.get("RDS_HOST")

    port = os.environ.get("RDS_PORT", "5432")
    database = os.environ.get("RDS_DATABASE", "fipedata")
    user = os.environ.get("RDS_USER", "postgres")

    if not all([host, port, database, user]):
        raise ValueError("Variáveis de ambiente para conexão com o banco de dados não definidas")

    logger.info(f"INGESTOR-DBCONECT - Tentando conexão IAM: {host}:{port}/{database} como {user}")

    is_connected = False
    attempts = 1
    conn = None
    sleep_vl = 0.5
    total_waited = 0
    last_error = None

    while not is_connected and total_waited < max_total_wait and attempts <= MAX_ATTEMPTS:
        try:
            # Gerar token IAM (válido por 15 minutos)
            password = get_db_auth_token(host=host, port=port, user=user)

            conn = psycopg2.connect(
                host=host,
                port=int(port),
                dbname=database,
                user=user,
                password=password,
                connect_timeout=10,
                sslmode='require'
            )
            is_connected = True
            logger.info(f"INGESTOR-DBCONECT - Conexão IAM com {host} estabelecida com sucesso em tentativa {attempts}")
            conn.autocommit = False
        except Exception as e:
            last_error = str(e)
            wait_time = min(sleep_vl * (2 ** (attempts - 1)), max_total_wait - total_waited)
            if wait_time > 0:
                logger.warning(f"INGESTOR-DBCONECT - Erro na tentativa {attempts} ({wait_time:.1f}s espera): {last_error}")
                time.sleep(wait_time)
                total_waited += wait_time
            attempts += 1

    if not is_connected:
        if attempts > MAX_ATTEMPTS:
            error_msg = f"Máximo de tentativas ({MAX_ATTEMPTS}) atingidas. Último erro: {last_error}"
        else:
            error_msg = f"Timeout ({total_waited}s) ao conectar em {host}. Último erro: {last_error}"
        logger.error(f"INGESTOR-DBCONECT - {error_msg}")
        raise ConnectionError(error_msg)

    return conn


def get_dual_db_connections():
    """Obtém duas conexões para dual-write (RDS STG e PRD).

    Returns:
        Tupla (conn_stg, conn_prd) ou (None, None) se falhar
    """
    rds_endpoints_stg = os.environ.get("RDS_ENDPOINTS_STG")
    rds_endpoints_prd = os.environ.get("RDS_ENDPOINTS_PRD")

    if not rds_endpoints_stg or not rds_endpoints_prd:
        logger.error("INGESTOR-DUALWRITE - RDS_ENDPOINTS_STG ou RDS_ENDPOINTS_PRD não definidos")
        return None, None

    logger.info(f"INGESTOR-DUALWRITE - Obtendo conexões duais: STG={rds_endpoints_stg}, PRD={rds_endpoints_prd}")

    conn_stg = None
    conn_prd = None

    try:
        conn_stg = get_db_connection(host=rds_endpoints_stg)
        conn_prd = get_db_connection(host=rds_endpoints_prd)

        if not conn_stg or not conn_prd:
            logger.error("INGESTOR-DUALWRITE - Falha ao conectar em um dos bancos")
            if conn_stg:
                conn_stg.close()
            if conn_prd:
                conn_prd.close()
            return None, None

        logger.info("INGESTOR-DUALWRITE - Conexões duais estabelecidas com sucesso")
        return conn_stg, conn_prd

    except Exception as e:
        logger.error(f"INGESTOR-DUALWRITE - Erro ao obter conexões duais: {str(e)}")
        if conn_stg:
            try:
                conn_stg.close()
            except:
                pass
        if conn_prd:
            try:
                conn_prd.close()
            except:
                pass
        return None, None

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

def process_message(conn_stg, conn_prd, record):
    """Processa uma mensagem SQS com dual-write (STG e PRD).

    Executa as mesmas operações em ambas as conexões. Se alguma falhar,
    faz rollback em ambas. Retorna True em sucesso, False em falha.

    Args:
        conn_stg: Conexão com RDS STG (us-east-2)
        conn_prd: Conexão com RDS PRD (us-east-1)
        record: Mensagem SQS
    """
    message_id = record["messageId"]
    try:
        logger.info(f"INGESTOR - Processando mensagem: {message_id} (DUAL-WRITE)")

        message_body = json.loads(record["body"])

        if message_body.get("tabela_referencia"):
            reference_table = message_body.get("tabela_referencia")
            for reference in reference_table:
                if reference.get("Codigo") and reference.get("Mes"):
                    logger.info(f"INGESTOR - Referência de tabela processada: {reference}")
                    get_or_create_reference_id(
                        conn_stg,
                        str(reference.get("Codigo")).strip(),
                        str(reference.get("Mes")).strip()
                    )
                    get_or_create_reference_id(
                        conn_prd,
                        str(reference.get("Codigo")).strip(),
                        str(reference.get("Mes")).strip()
                    )
        else:
            logger.info(f"INGESTOR - Conteúdo da mensagem: {json.dumps(message_body, ensure_ascii=False)[:500]}...")

            # Obter reference_id em ambas conexões (devem ser iguais)
            reference_id_stg = get_or_create_reference_id(
                conn_stg,
                str(message_body.get("codigoTabelaReferencia", "")).strip(),
                str(message_body.get("mesReferenciaAno", "")).strip()
            )
            reference_id_prd = get_or_create_reference_id(
                conn_prd,
                str(message_body.get("codigoTabelaReferencia", "")).strip(),
                str(message_body.get("mesReferenciaAno", "")).strip()
            )

            if reference_id_stg is None or reference_id_prd is None:
                logger.error(f"INGESTOR - Falha ao criar reference_id em um dos bancos (mensagem {message_id})")
                conn_stg.rollback()
                conn_prd.rollback()
                return False

            data = {
                "manufacturer": message_body.get("manufacturer"),
                "manufacturer_code": message_body.get("manufacturer_code"),
                "model": message_body.get("model"),
                "model_code": message_body.get("model_code"),
                "model_year_code": message_body.get("model_year_code"),
                "reference_month": message_body.get("mesReferenciaAno"),
                "reference_month_code": message_body.get("codigoTabelaReferencia"),
                "reference_id": reference_id_stg,  # Usa ID do STG
                "fipe_value": message_body.get("fipe_value"),
                "fipe_code": message_body.get("fipe_code"),
                "fuel_type": message_body.get("fuel_type"),
                "vehicle_type": message_body.get("vehicle_type"),
                "active": True
            }

            # Validação
            required_keys = ['manufacturer', 'manufacturer_code', 'model', 'model_code', 'fipe_code', 'vehicle_type', 'reference_id']
            if any(data.get(key) is None or data.get(key) is False for key in required_keys):
                logger.error(f"INGESTOR - Dados obrigatórios ausentes (mensagem {message_id}). Dados: {data}")
                conn_stg.rollback()
                conn_prd.rollback()
                return False

            # Processar em ambas conexões
            manufacturer_id_stg = get_or_create_manufacturer(conn_stg, data['manufacturer'], data['manufacturer_code'], data['vehicle_type'])
            manufacturer_id_prd = get_or_create_manufacturer(conn_prd, data['manufacturer'], data['manufacturer_code'], data['vehicle_type'])

            data['manufacturer_id'] = manufacturer_id_stg
            model_id_stg = get_or_create_model(conn_stg, data['model'], data['model_code'], manufacturer_id_stg)

            data['manufacturer_id'] = manufacturer_id_prd
            model_id_prd = get_or_create_model(conn_prd, data['model'], data['model_code'], manufacturer_id_prd)

            # Restaurar manufacturer_id para STG
            data['manufacturer_id'] = manufacturer_id_stg
            data['model_id'] = model_id_stg
            insert_edit_model_value(conn_stg, data)

            # Executar em PRD
            data['manufacturer_id'] = manufacturer_id_prd
            data['model_id'] = model_id_prd
            insert_edit_model_value(conn_prd, data)

            logger.info(f"INGESTOR - Mensagem {message_id} processada com sucesso em ambas conexões (STG + PRD)")

        return True

    except (KeyError, json.JSONDecodeError, ValueError) as e:
        logger.error(f"INGESTOR - Erro de dados na mensagem {message_id}: {str(e)}. Corpo: {record.get('body')}")
        try:
            conn_stg.rollback()
            conn_prd.rollback()
        except:
            pass
        return False

    except Exception as e:
        logger.error(f"INGESTOR - Erro inesperado (mensagem {message_id}): {str(e)}")
        try:
            conn_stg.rollback()
            conn_prd.rollback()
        except:
            pass
        return False

def lambda_handler(event, context):
    """Manipulador AWS Lambda para processar mensagens SQS com dual-write RDS.

    OBRIGATÓRIO: RDS_ENDPOINTS_STG e RDS_ENDPOINTS_PRD devem estar definidos.
    Não suporta modo SINGLE (sempre dual-write).
    """
    logger.info("INGESTOR - Iniciando FipeSomaIngestor (DUAL-WRITE obrigatório)...")

    # Validar variáveis obrigatórias
    rds_endpoints_stg = os.environ.get("RDS_ENDPOINTS_STG")
    rds_endpoints_prd = os.environ.get("RDS_ENDPOINTS_PRD")

    if not rds_endpoints_stg or not rds_endpoints_prd:
        error_msg = f"ERRO CRÍTICO: RDS_ENDPOINTS_STG e RDS_ENDPOINTS_PRD são obrigatórios. STG={rds_endpoints_stg}, PRD={rds_endpoints_prd}"
        logger.error(error_msg)
        raise ValueError(error_msg)

    logger.info(f"INGESTOR - DUAL-WRITE configurado: STG={rds_endpoints_stg}, PRD={rds_endpoints_prd}")

    batch_item_failures = []
    logger.info(f"INGESTOR - Processando {len(event['Records'])} mensagens em DUAL-WRITE...")

    for record in event["Records"]:
        success = False
        conn_stg = None
        conn_prd = None
        message_id = record['messageId']

        try:
            # Obter conexões duais (STG e PRD)
            conn_stg, conn_prd = get_dual_db_connections()
            if not conn_stg or not conn_prd:
                logger.error(f"INGESTOR - Falha ao conectar em um dos RDS (msg {message_id})")
            else:
                # Processar mensagem com ambas conexões
                success = process_message(conn_stg, conn_prd, record)

        except Exception as e:
            logger.error(f"INGESTOR - Erro crítico (msg {message_id}): {str(e)}")

        finally:
            # Fechar conexões
            if conn_stg:
                try:
                    conn_stg.close()
                except Exception as e:
                    logger.error(f"INGESTOR - Erro ao fechar conexão STG (msg {message_id}): {str(e)}")
            if conn_prd:
                try:
                    conn_prd.close()
                except Exception as e:
                    logger.error(f"INGESTOR - Erro ao fechar conexão PRD (msg {message_id}): {str(e)}")

        # Se falhou, adiciona à lista de reprocessamento (vai para DLQ)
        if not success:
            batch_item_failures.append({"itemIdentifier": message_id})
            logger.warning(f"INGESTOR - Mensagem {message_id} adicionada ao reprocessamento")
            logger.warning(f"INGESTOR - Mensagem {record['messageId']} marcada para reprocessamento.")

    total_failures = len(batch_item_failures)
    total_records = len(event["Records"])
    success_count = total_records - total_failures

    logger.info(f"INGESTOR - Processamento concluído: {success_count}/{total_records} sucesso, {total_failures} falhas")

    if total_failures > 0:
        logger.warning(f"INGESTOR - {total_failures} mensagens falharam e serão reenviadas para a fila.")

    return {
        "batchItemFailures": batch_item_failures
    }