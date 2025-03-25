import json
import os
import logging
import time
import psycopg2
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
    try:
        # Obter as informações de conexão das variáveis de ambiente
        host = os.environ.get("RDS_HOST")
        port = os.environ.get("RDS_PORT")
        database = os.environ.get("RDS_DATABASE")
        user = os.environ.get("RDS_USER")
        
        if not all([host, port, database, user]):
            raise ValueError("Variáveis de ambiente para conexão com o banco de dados não definidas")
        
        # Obter a senha do Secrets Manager
        password = get_db_password()
        
        logger.info(f"Tentando conexão com o banco de dados: {host}:{port}/{database} como {user}")
        
        # Construir a string de conexão com o banco de dados
        conn = psycopg2.connect(
            host=host,
            port=port,
            dbname=database,
            user=user,
            password=password
        )
        
        # Desativar autocommit para controlar transações manualmente
        conn.autocommit = False
        
        logger.info("Conexão com o banco de dados estabelecida com sucesso")
        return conn
    except Exception as e:
        logger.error(f"Erro de conexão com o banco de dados: {str(e)}")
        raise

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
            logger.info(f"Verificando fabricante: {manufacturer}, código: {manufacturer_code}, tipo: {vehicle_type}")
            cur.execute("""
                SELECT id FROM public.fipe_vehicle_manufacturer 
                WHERE name = %s AND code = %s AND vehicle_type = %s
            """, (manufacturer, manufacturer_code, vehicle_type))
            
            result = cur.fetchone()
            
            if result:
                # Fabricante existe, retornar o ID
                logger.info(f"Fabricante encontrado com ID: {result[0]}")
                return result[0]
            
            # Fabricante não existe, inserir novo registro
            logger.info(f"Criando novo fabricante: {manufacturer}")
            cur.execute("""
                INSERT INTO public.fipe_vehicle_manufacturer 
                (name, code, vehicle_type, create_date) 
                VALUES (%s, %s, %s, NOW()) 
                RETURNING id
            """, (manufacturer, manufacturer_code, vehicle_type))
            
            manufacturer_id = cur.fetchone()[0]
            conn.commit()
            logger.info(f"Novo fabricante criado com ID: {manufacturer_id}")
            
            return manufacturer_id
        except Exception as e:
            conn.rollback()
            logger.error(f"Erro ao processar fabricante: {str(e)}")
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
            logger.info(f"Verificando modelo: {model}, código: {model_code}, fabricante ID: {manufacturer_id}")
            cur.execute("""
                SELECT id FROM public.fipe_vehicle_model 
                WHERE name = %s AND code = %s AND manufacturer_id = %s
            """, (str(model), str(model_code), manufacturer_id))
            
            result = cur.fetchone()
            
            if result:
                # Modelo existe, retornar o ID
                logger.info(f"Modelo encontrado com ID: {result[0]}")
                return result[0]
            
            # Modelo não existe, inserir novo registro
            logger.info(f"Criando novo modelo: {model}")
            cur.execute("""
                INSERT INTO public.fipe_vehicle_model 
                (name, code, manufacturer_id, create_date) 
                VALUES (%s, %s, %s, NOW()) 
                RETURNING id
            """, (str(model), str(model_code), manufacturer_id))
            
            model_id = cur.fetchone()[0]
            conn.commit()
            logger.info(f"Novo modelo criado com ID: {model_id}")
            
            return model_id
        except Exception as e:
            conn.rollback()
            logger.error(f"Erro ao processar modelo: {str(e)}")
            raise

def insert_model_value(conn, data):
    """
    Insere um valor de modelo no banco de dados.
    
    Args:
        conn: Conexão com o banco de dados
        data: Dicionário contendo os dados do valor do modelo
    """
    with conn.cursor() as cur:
        try:
            logger.info(f"Inserindo valor do modelo: {data['model']} {data['model_year_code']}")
            
            # Processar o valor FIPE para float
            fipe_value_str = str(data['fipe_value']).replace("R$ ", "").replace(".", "").replace(",", ".")
            fipe_value = float(fipe_value_str) if fipe_value_str else 0
            
            # Verificar se o valor já existe no banco de dados
            cur.execute("""
                SELECT id FROM public.fipe_vehicle_model_value
                WHERE model_id = %s AND fipe_code = %s AND 
                      manufacture_year = %s AND reference_month_code = %s
            """, (
                int(data['model_id']), 
                str(data['fipe_code']), 
                str(data['model_year_code']), 
                str(data['reference_month_code']),
            ))
            
            existing_value = cur.fetchone()
            
            if existing_value:
                # Valor já existe, atualizar
                logger.info(f"Atualizando valor existente para: {data['model']} {data['model_year_code']}")
                cur.execute("""
                    UPDATE public.fipe_vehicle_model_value
                    SET fipe_value = %s, write_date = NOW()
                    WHERE id = %s
                """, (fipe_value, existing_value[0]))
            else:
                # Valor não existe, inserir novo
                logger.info(f"Inserindo novo valor para: {data['model']} {data['model_year_code']}")
                cur.execute("""
                    INSERT INTO public.fipe_vehicle_model_value (
                        name, code, model_id, fipe_code, manufacturer_id, 
                        manufacture_year, reference_month, reference_month_code, 
                        fipe_value, fuel_type, vehicle_type, active, create_date
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()
                    )
                """, (
                    f"{data['model']} {data['model_year_code']}",
                    str(data['model_code']),
                    int(data['model_id']),
                    str(data['fipe_code']),
                    int(data['manufacturer_id']),
                    str(data['model_year_code']),
                    str(data['reference_month']),
                    str(data['reference_month_code']),
                    fipe_value,
                    str(data['fuel_type']),
                    int(data['vehicle_type']),
                    True
                ))
            
            conn.commit()
            logger.info(f"Valor do modelo processado com sucesso: {data['model']} {data['model_year_code']}")
        except Exception as e:
            conn.rollback()
            logger.error(f"Erro ao inserir/atualizar valor do modelo: {str(e)}")
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
        logger.info(f"Processando mensagem: {message_id}")
        
        message_body = json.loads(record["body"])
        logger.info(f"Conteúdo da mensagem: {json.dumps(message_body, ensure_ascii=False)[:500]}...")

        # Preparar dados para processamento
        data = {
            "manufacturer": message_body.get("manufacturer", "Unknown"),
            "manufacturer_code": message_body.get("manufacturer_code", 0),
            "model": message_body.get("model", "Unknown"),
            "model_code": message_body.get("model_code", 0),
            "model_year_code": message_body.get("model_year_code", "Unknown"),
            "reference_month": message_body.get("mesReferenciaAno", "Unknown"),
            "reference_month_code": message_body.get("codigoTabelaReferencia", 0),
            "fipe_value": message_body.get("fipe_value", "Unknown"),
            "fipe_code": message_body.get("fipe_code", "Unknown"),
            "fuel_type": message_body.get("fuel_type", "Unknown"),
            "vehicle_type": message_body.get("vehicle_type", 0),
        }
        
        # Validar dados obrigatórios
        if not all([
            data['manufacturer'], data['manufacturer_code'], data['model'], 
            data['model_code'], data['fipe_code'], data['vehicle_type']
        ]):
            logger.error(f"Dados obrigatórios ausentes na mensagem {message_id}")
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
        insert_model_value(conn, data)
        
        logger.info(f"Mensagem {message_id} processada com sucesso")
        return True
        
    except (KeyError, json.JSONDecodeError) as e:
        logger.error(f"Erro ao analisar mensagem {message_id}: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"Erro ao processar mensagem {message_id}: {str(e)}")
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
    logger.info("Iniciando FipeSomaIngestor...")
    
    # Verificar variáveis de ambiente importantes
    input_queue_url = os.environ.get("SQS_INPUT_URL")
    if not input_queue_url:
        logger.error("Variável de ambiente SQS_INPUT_URL não definida")
        return {
            "statusCode": 500,
            "body": json.dumps("Erro: SQS_INPUT_URL não definida"),
            "batchItemFailures": [{"itemIdentifier": record["messageId"]} for record in event["Records"]]
        }
    
    logger.info(f"Usando fila de entrada: {input_queue_url}")
    logger.info(f"Processando {len(event['Records'])} mensagens da fila SQS...")
    
    batch_item_failures = []
    total_processed = 0

    for record in event["Records"]:
        # Para cada mensagem, estabelecemos uma nova conexão
        # Isso evita problemas de transações abortadas afetando mensagens subsequentes
        conn = None
        try:
            conn = get_db_connection()
            
            # Processar a mensagem
            success = process_message(conn, record)
            
            if success:
                total_processed += 1
            else:
                batch_item_failures.append({"itemIdentifier": record["messageId"]})
                
        except Exception as e:
            logger.error(f"Erro ao processar mensagem {record['messageId']}: {str(e)}")
            batch_item_failures.append({"itemIdentifier": record["messageId"]})
        finally:
            # Fechar a conexão, garantindo que todas as transações sejam finalizadas
            if conn:
                try:
                    conn.close()
                except Exception as e:
                    logger.error(f"Erro ao fechar conexão: {str(e)}")

    total_failures = len(batch_item_failures)
    total_records = len(event["Records"])
    success_count = total_records - total_failures
    
    logger.info(f"Processamento concluído: {success_count}/{total_records} mensagens processadas com sucesso")
    logger.info(f"Total de valores FIPE processados: {total_processed}")
    
    if total_failures > 0:
        logger.warning(f"{total_failures} mensagens não puderam ser processadas")

    return {
        "statusCode": 200,
        "body": json.dumps("Mensagens processadas com sucesso!"),
        "batchItemFailures": batch_item_failures,
    }