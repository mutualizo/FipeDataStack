import json
import os
import logging
import time
import psycopg2
from datetime import datetime
from psycopg2 import sql
from get_db_password import get_db_password

# Configure logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def get_db_connection():
    """
    Estabelece uma conexão com o banco de dados PostgreSQL.
    
    Returns:
        Connection: Conexão com o banco de dados PostgreSQL
    """

    # Obter as informações de conexão das variáveis de ambiente
    host = os.environ.get("RDS_HOST")
    port = os.environ.get("RDS_PORT")
    database = os.environ.get("RDS_DATABASE")
    user = os.environ.get("RDS_USER")
    
    if not all([host, port, database, user]):
        raise ValueError("Variáveis de ambiente para conexão com o banco de dados não definidas")
    
    # Obter a senha do Secrets Manager
    password = get_db_password()
    
    logger.info(f"INGESTOR-DBCONECT - Tentando conexão com o banco de dados: {host}:{port}/{database} como {user}")
    
    # Conectar ao banco de dados
    is_connected = False
    attempts = 1
    conn = None
    while not is_connected and attempts < 5:
        try:
            conn = psycopg2.connect(
				host=host,
				port=port,
				dbname=database,
				user=user,
				password=password
			)
            is_connected = True
            logger.info("INGESTOR-DBCONECT - Conexão com o banco de dados estabelecida com sucesso")
            # Desativar autocommit para controlar transações manualmente
            conn.autocommit = False
        except Exception as e:
            logger.error(f"INGESTOR-DBCONECT - Erro de conexão com o banco de dados na tentativa {attempts}: {str(e)}")
            time.sleep(1)
        attempts += 1
    return conn

def get_or_create_reference_id(conn, code, name):
    """
	Verifica se a referência existe, cria se não existir, e retorna o ID da referência.
	Args:
	    conn: Conexão com o banco de dados
	    code: Código da referência	
	    name: Nome da referência    
    Returns:
        int: ID da referência
    """
    with conn.cursor() as cur:
        try:
            # Verificar se a referência existe
            logger.info(f"INGESTOR-REFID - Verificando referência: {code}, name: {name}")
            cur.execute("""
				SELECT id FROM public.fipe_reference_month 
				WHERE code = %s
			""", (code,))

            id_no = cur.fetchone()

            if bool(id_no):
                # Referência existe, retornar o ID
                logger.info(f"INGESTOR-REFID - Referência encontrada com ID: {id_no[0]}")
                id_no = id_no[0]
            else:
                # Referência não encontrada, criar nova referência
                logger.info(f"Referência não encontrada, criando nova referência: {code}")
                cur.execute("""
                    INSERT INTO public.fipe_reference_month 
                    (code, name, create_date, create_uid, write_date, write_uid) 
                    VALUES (%s, %s, %s, %s, %s, %s) 
                    RETURNING id
                    """, (code, name, datetime.now(), 1, datetime.now(), 1)
                )

                id_no = cur.fetchone()[0]
                logger.info(f"INGESTOR-REFID - Referência criada com ID: {id_no}")
                conn.commit()
            return id_no
        except Exception as e:
            logger.error(f"INGESTOR-REFID - Erro ao verificar ou criar referência: {str(e)}")
            return None

def get_or_create_manufacturer(conn, manufacturer, manufacturer_code, vehicle_type):
    """
    Verifica se o fabricante existe, cria se não existir, e retorna o ID do fabricante.
    
    Args:
        conn: Conexão com o banco de dados
        manufacturer: Nome do fabricante
        manufacturer_code: Código do fabricante
        vehicle_type: Tipo de veículo
        
    Returns:
        int: ID do fabricante
    """
    with conn.cursor() as cur:
        try:
            # Verificar se o fabricante existe
            logger.info(f"INGESTOR-MANUFACT - Verificando fabricante: {manufacturer}, código: {manufacturer_code}, tipo: {vehicle_type}")
            cur.execute("""
                SELECT id FROM public.fipe_vehicle_manufacturer 
                WHERE name = %s AND code = %s AND vehicle_type = %s
            """, (manufacturer, manufacturer_code, vehicle_type))
            
            result = cur.fetchone()
            
            if result:
                # Fabricante existe, retornar o ID
                logger.info(f"INGESTOR-MANUFACT - Fabricante encontrado com ID: {result[0]}")
                return result[0]
            
            # Fabricante não existe, inserir novo registro
            logger.info(f"INGESTOR-MANUFACT - Criando novo fabricante: {manufacturer}")
            cur.execute("""
                INSERT INTO public.fipe_vehicle_manufacturer 
                (name, code, vehicle_type, create_date, create_uid, write_date, write_uid) 
                VALUES (%s, %s, %s, %s, %s, %s, %s) 
                RETURNING id
            """, (manufacturer, manufacturer_code, vehicle_type, datetime.now(), 1, datetime.now(), 1))
            
            manufacturer_id = cur.fetchone()[0]
            conn.commit()
            logger.info(f"INGESTOR-MANUFACT - Novo fabricante criado com ID: {manufacturer_id}")
            
            return manufacturer_id
        except Exception as e:
            conn.rollback()
            logger.error(f"INGESTOR-MANUFACT - Erro ao processar fabricante: {str(e)}")
            raise

def get_or_create_model(conn, model, model_code, manufacturer_id):
    """
    Verifica se o modelo existe, cria se não existir, e retorna o ID do modelo.
    
    Args:
        conn: Conexão com o banco de dados
        model: Nome do modelo
        model_code: Código do modelo
        manufacturer_id: ID do fabricante
        
    Returns:
        int: ID do modelo
    """
    with conn.cursor() as cur:
        try:
            # Verificar se o modelo existe
            logger.info(f"INGESTOR-MODEL - Verificando modelo: {model}, código: {model_code}, fabricante ID: {manufacturer_id}")
            cur.execute("""
                SELECT id FROM public.fipe_vehicle_model 
                WHERE name = %s AND code = %s AND manufacturer_id = %s
            """, (str(model), str(model_code), manufacturer_id))
            
            result = cur.fetchone()
            
            if result:
                # Modelo existe, retornar o ID
                logger.info(f"INGESTOR-MODEL - Modelo encontrado com ID: {result[0]}")
                return result[0]
            
            # Modelo não existe, inserir novo registro
            logger.info(f"INGESTOR-MODEL - Criando novo modelo: {model}")
            cur.execute("""
                INSERT INTO public.fipe_vehicle_model 
                (name, code, manufacturer_id, create_date, create_uid, write_date, write_uid) 
                VALUES (%s, %s, %s, %s, %s, %s, %s) 
                RETURNING id
            """, (str(model), str(model_code), manufacturer_id, datetime.now(), 1, datetime.now(), 1))
            
            model_id = cur.fetchone()[0]
            conn.commit()
            logger.info(f"INGESTOR-MODEL - Novo modelo criado com ID: {model_id}")
            
            return model_id
        except Exception as e:
            conn.rollback()
            logger.error(f"INGESTOR-MODEL - Erro ao processar modelo: {str(e)}")
            raise

def insert_edit_model_value(conn, data):
    """
    Insere um valor de modelo no banco de dados.
    
    Args:
        conn: Conexão com o banco de dados
        data: Dicionário contendo os dados do valor do modelo
    """
    with conn.cursor() as cur:
        try:
            logger.info(f"INGESTOR-INSERT - Inserindo valor do modelo: {data['model']} {data['model_year_code']}")
            
            # Processar o valor FIPE para float
            fipe_value_str = str(data['fipe_value']).replace("R$ ", "").replace(".", "").replace(",", ".")
            fipe_value = float(fipe_value_str) if fipe_value_str else 0
            
            # Verificar se o valor já existe no banco de dados
            cur.execute("""
                SELECT id FROM public.fipe_vehicle_model_value
                WHERE model_id = %s AND 
                      fipe_code = %s AND 
                      manufacture_year = %s AND 
                      reference_month_code = %s AND
                      fuel_type = %s
            """, (
                int(data['model_id']), 
                str(data['fipe_code']), 
                str(data['model_year_code']), 
                str(data['reference_month_code']),
                str(data['fuel_type']),
            ))
            
            existing_value = cur.fetchone()
            
            if existing_value:
                # Valor já existe, atualizar
                logger.info(f"INGESTOR-INSERT - Atualizando valor existente para: {data['model']} {data['model_year_code']}")
                cur.execute("""
                    UPDATE public.fipe_vehicle_model_value
                    SET fipe_value = %s,
                        reference_month_id = %s, 
                        write_date = %s
                    WHERE id = %s
                """, (fipe_value, int(data['reference_id']),datetime.now(), existing_value[0]))
            else:
                # Valor não existe, inserir novo
                logger.info(f"INGESTOR-INSERT - Inserindo novo valor para: {data['model']} {data['model_year_code']}")
                cur.execute("""
                    INSERT INTO public.fipe_vehicle_model_value (
                        name, code, model_id, fipe_code, manufacturer_id, 
                        manufacture_year, reference_month, reference_month_code, 
                        reference_month_id, fipe_value, fuel_type, vehicle_type, 
                        active, create_date, create_uid, write_date, write_uid
                    ) 
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    f"{data['model']} {data['model_year_code']}",
                    str(data['model_code']),
                    int(data['model_id']),
                    str(data['fipe_code']),
                    int(data['manufacturer_id']),
                    str(data['model_year_code']),
                    str(data['reference_month']),
                    str(data['reference_month_code']),
					int(data['reference_id']),
                    fipe_value,
                    str(data['fuel_type']),
                    int(data['vehicle_type']),
                    True,
					datetime.now(),
                    1,
					datetime.now(),
					1
                ))
            
            conn.commit()
            logger.info(f"INGESTOR-INSERT - Valor do modelo processado com sucesso: {data['model']} {data['model_year_code']}")
        except Exception as e:
            conn.rollback()
            logger.error(f"INGESTOR-INSERT - Erro ao inserir/atualizar valor do modelo: {str(e)}")
            raise

def process_message(conn, record):
    """
    Processa uma única mensagem SQS.
    
    Args:
        conn: Conexão com o banco de dados
        record: Registro da mensagem SQS
        
    Returns:
        bool: True se a mensagem foi processada com sucesso, False caso contrário
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
                    reference_id = get_or_create_reference_id(
                        conn, 
                        str(reference.get("Codigo")).strip(), 
                        str(reference.get("Mes")).strip()
                    )                    
        else:
            logger.info(f"INGESTOR - Conteúdo da mensagem: {json.dumps(message_body, ensure_ascii=False)[:500]}...")

            reference_id = get_or_create_reference_id(
                conn, 
                str(message_body.get("codigoTabelaReferencia", False)).strip(), 
                str(message_body.get("mesReferenciaAno", "")).strip()
            )                    
    
            # Preparar dados para processamento
            data = {
                "manufacturer": message_body.get("manufacturer", False),
                "manufacturer_code": message_body.get("manufacturer_code", False),
                "model": message_body.get("model", False),
                "model_code": message_body.get("model_code", False),
                "model_year_code": message_body.get("model_year_code", False),
                "reference_month": message_body.get("mesReferenciaAno", False),
                "reference_month_code": message_body.get("codigoTabelaReferencia", False),
                "reference_id": reference_id,
                "fipe_value": message_body.get("fipe_value", False),
                "fipe_code": message_body.get("fipe_code", False),
                "fuel_type": message_body.get("fuel_type", False),
                "vehicle_type": message_body.get("vehicle_type", False),
            }
            
            # Validar dados obrigatórios]
            not_included = [] 
            if data.get('manufacturer', False) == False:
                not_included.append('manufacturer')
    
            if data.get('manufacturer_code', False) == False:
                not_included.append('manufacturer_code')
    
            if data.get('model', False) == False:
                not_included.append('model')
    
            if data.get('model_code', False) == False:
                not_included.append('model_code')
    
            if data.get('fipe_code', False) == False:
                not_included.append('fipe_code')
    
            if data.get('vehicle_type', False) == False:
                not_included.append('vehicle_type')
    
            if not_included:
                logger.error(f"INGESTOR - Dados obrigatórios ausentes na mensagem {message_id}: {not_included}")
                return False
    
            if not bool(conn):
                logger.error(f"INGESTOR - Não foi possível processar a mensagem {message_id}: Conexão com o banco de dados inválida.")
                return False
    
            # Obter ou criar fabricante - usando uma conexão nova para cada operação
            data['manufacturer_id'] = get_or_create_manufacturer(
                conn, 
                data['manufacturer'], 
                data['manufacturer_code'], 
                data['vehicle_type']
            )
    
            # Obter ou criar modelo - usando uma conexão nova para cada operação
            data['model_id'] = get_or_create_model(
                conn, 
                data['model'], 
                data['model_code'], 
                data['manufacturer_id']
            )
    
            # Inserir valor do modelo - usando uma conexão nova para cada operação
            insert_edit_model_value(conn, data)
            
            logger.info(f"INGESTOR - Mensagem {message_id} processada com sucesso")
        return True
        
    except (KeyError, json.JSONDecodeError) as e:
        logger.error(f"INGESTOR - Erro de decodificação da mensagem {message_id}: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"INGESTOR - Erro ao processar mensagem {message_id}: {str(e)}")
        return False

def lambda_handler(event, context):
    """
    Manipulador AWS Lambda para processar mensagens SQS e inserir dados no PostgreSQL.
    
    Args:
        event: Evento AWS Lambda
        context: Contexto AWS Lambda
        
    Returns:
        dict: Resultado do processamento, incluindo eventuais falhas
    """
    logger.info("INGESTOR - Iniciando FipeSomaIngestor...")
    
    # Verificar variáveis de ambiente importantes
    input_queue_url = os.environ.get("SQS_INPUT_URL")
    if not input_queue_url:
        logger.error("INGESTOR - Variável de ambiente SQS_INPUT_URL não definida")
        return {
            "statusCode": 500,
            "body": json.dumps("Erro: SQS_INPUT_URL não definida"),
            "batchItemFailures": [{"itemIdentifier": record["messageId"]} for record in event["Records"]]
        }
    
    logger.info(f"INGESTOR - Usando fila de entrada: {input_queue_url}")
    logger.info(f"INGESTOR - Processando {len(event['Records'])} mensagens da fila SQS...")
    
    batch_item_failures = []
    total_processed = 0

    for record in event["Records"]:
        # Para cada mensagem, estabelecemos uma nova conexão
        # Isso evita problemas de transações abortadas afetando mensagens subsequentes

        conn = get_db_connection()
        success = False
        
        if bool(conn):
            # Processar a mensagem
            success = process_message(conn, record)
            try:
                # Fechar a conexão, garantindo que todas as transações sejam finalizadas
                conn.close()
            except Exception as e:
                logger.error(f"INGESTOR - Erro ao fechar conexão: {str(e)}")
        else:
            logger.error("INGESTOR - Erro fatal ao estabelecer conexão com o banco de dados")
            
        if success:
            total_processed += 1
        else:
            batch_item_failures.append({"itemIdentifier": record["messageId"]})
            logger.error(f"INGESTOR - Erro ao processar mensagem {str(record)}")
            batch_item_failures.append({"itemIdentifier": record["messageId"]})

    total_failures = len(batch_item_failures)
    total_records = len(event["Records"])
    success_count = total_records - total_failures
    
    logger.info(f"""INGESTOR - Resumo do Processamento Concluído:\n
    - {total_processed} total de valores FIPE processados;\n
	- {success_count}/{total_records} mensagens processadas com sucesso;\n
	- {total_failures}/{total_records} mensagens processadas com falhas;""")
    
    if total_failures > 0:
        logger.warning(f"INGESTOR - {total_failures} mensagens não puderam ser processadas;")

    return {
        "statusCode": 200,
        "body": json.dumps("Mensagens processadas com sucesso!"),
        "batchItemFailures": batch_item_failures,
    }