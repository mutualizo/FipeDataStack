import json
import boto3
import psycopg2
import os
import cfnresponse
import time
import logging

# Configurar o logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def handler(event, context):
    logger.info(f"SQLEXEC - Iniciando função Lambda com RequestType: {event.get('RequestType')}")
    logger.info(f"SQLEXEC - Contexto: RequestID={context.aws_request_id}, RemainingTime={context.get_remaining_time_in_millis()}ms")
    
    response_data = {}
    
    try:
        # Verificar se o evento é um evento de CloudFormation Custom Resource
        request_type = event.get('RequestType')
        logger.info(f"SQLEXEC - Tipo de evento recebido: {request_type if request_type else 'Evento direto (não CloudFormation)'}")
        
        # Se for um evento de CloudFormation e não for um evento Create, retornamos sucesso
        if request_type and request_type != 'Create':
            logger.info(f"SQLEXEC - Evento {request_type} não requer ação. Retornando sucesso.")
            cfnresponse.send(event, context, cfnresponse.SUCCESS, {})
            return {'statusCode': 200, 'body': json.dumps('Nenhuma ação necessária')}
            
        # Se não for um evento CloudFormation ou for um evento Create, processamos normalmente
        logger.info("SQLEXEC - Processando evento de criação/invocação direta...")
            
        # Obter as credenciais do banco de dados do Secrets Manager
        logger.info("SQLEXEC - Obtendo credenciais do banco de dados do Secrets Manager...")
        secret_arn = os.environ.get('SECRET_ARN')
        logger.info(f"SQLEXEC - Secret ARN: {secret_arn}")
        
        secrets_client = boto3.client('secretsmanager')
        secret_value = secrets_client.get_secret_value(SecretId=secret_arn)
        secret = json.loads(secret_value['SecretString'])
        username = secret['username']
        logger.info(f"SQLEXEC - Nome de usuário obtido: {username}")
        logger.info("SQLEXEC - Credenciais obtidas com sucesso.")
        
        # Obter o script SQL do S3
        logger.info("SQLEXEC - Obtendo script SQL do S3...")
        s3_client = boto3.client('s3')
        bucket_name = os.environ.get('SQL_BUCKET')
        key = os.environ.get('SQL_KEY')
        logger.info(f"SQLEXEC - Bucket: {bucket_name}, Key: {key}")
            
        try:
            response = s3_client.get_object(Bucket=bucket_name, Key=key)
            sql_script = response['Body'].read().decode('utf-8')
            logger.info(f"SQLEXEC - Script SQL obtido. Tamanho: {len(sql_script)} caracteres")
            logger.info(f"SQLEXEC - Primeiros 100 caracteres do script: {sql_script[:100]}...")
        except Exception as s3_error:
            logger.error(f"SQLEXEC - Erro ao obter script SQL do S3: {str(s3_error)}")
            raise
            
        # Obter informações do endpoint do banco de dados
        db_endpoint = os.environ.get('DB_ENDPOINT')
        db_port = int(os.environ.get('DB_PORT'))
        logger.info(f"SQLEXEC - Endpoint do banco de dados: {db_endpoint}:{db_port}")
        
        # Aguardar que o banco de dados esteja disponível
        logger.info("SQLEXEC - Aguardando 60 segundos para garantir que o cluster RDS esteja pronto...")
        time.sleep(60)
        logger.info("SQLEXEC - Tempo de espera concluído.")
        
        # Tentar conectar ao banco de dados postgres padrão
        retry_count = 0
        max_retries = 5
        retry_delay = 30
        connected = False
            
        while not connected and retry_count < max_retries:
            try:
                logger.info(f"SQLEXEC - Tentativa {retry_count + 1} de conexão ao banco postgres...")
                conn = psycopg2.connect(
                    host=db_endpoint,
                    port=db_port,
                    user=username,
                    password=secret['password'],
                    dbname='postgres',
                    connect_timeout=30
                )
                conn.autocommit = True
                logger.info("SQLEXEC - Conexão estabelecida com sucesso ao banco postgres.")
                connected = True
            except Exception as conn_error:
                logger.error(f"SQLEXEC - Erro ao conectar: {str(conn_error)}")
                retry_count += 1
                if retry_count < max_retries:
                    logger.info(f"SQLEXEC - Aguardando {retry_delay} segundos antes da próxima tentativa...")
                    time.sleep(retry_delay)
                else:
                    logger.error(f"SQLEXEC - Máximo de tentativas excedido. Falha na conexão.")
                    raise
            
        # Verificar se o banco de dados fipedata já existe
        logger.info("SQLEXEC - Verificando se o banco de dados fipedata já existe...")
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM pg_database WHERE datname='fipedata'")
        exists = cursor.fetchone()
        
        if not exists:
            # Criar o banco de dados fipedata
            logger.info("SQLEXEC - Criando o banco de dados fipedata...")
            try:
                cursor.execute("CREATE DATABASE fipedata")
                logger.info("SQLEXEC - Banco de dados fipedata criado com sucesso.")
            except Exception as db_error:
                logger.error(f"SQLEXEC - Erro ao criar banco de dados fipedata: {str(db_error)}")
                raise
        else:
            logger.info("SQLEXEC - Banco de dados fipedata já existe.")
            
        cursor.close()
        conn.close()
        logger.info("SQLEXEC - Conexão ao banco postgres fechada.")
        
        # Aguardar para garantir que o banco de dados seja criado
        logger.info("SQLEXEC - Aguardando 20 segundos para garantir que o banco fipedata esteja disponível...")
        time.sleep(20)
        
        # Conectar ao novo banco de dados
        logger.info("SQLEXEC - Conectando ao banco de dados fipedata...")
        retry_count = 0
        connected = False
            
        while not connected and retry_count < max_retries:
            try:
                logger.info(f"SQLEXEC - Tentativa {retry_count + 1} de conexão ao banco fipedata...")
                conn = psycopg2.connect(
                    host=db_endpoint,
                    port=db_port,
                    user=username,
                    password=secret['password'],
                    dbname='fipedata',
                    connect_timeout=30
                )
                conn.autocommit = True
                logger.info("SQLEXEC - Conexão estabelecida com sucesso ao banco fipedata.")
                connected = True
            except Exception as fipe_conn_error:
                logger.error(f"SQLEXEC - Erro ao conectar: {str(fipe_conn_error)}")
                retry_count += 1
                if retry_count < max_retries:
                    logger.info(f"SQLEXEC - Aguardando {retry_delay} segundos antes da próxima tentativa...")
                    time.sleep(retry_delay)
                else:
                    logger.error(f"SQLEXEC - Máximo de tentativas excedido. Falha na conexão ao fipedata.")
                    raise
            
        # Executar o restante do script SQL
        logger.info("SQLEXEC - Preparando para executar as sequências e tabelas...")
        cursor = conn.cursor()
            
        # Remover as partes do script que já executamos manualmente
        script_parts = sql_script.split('\\c fipedata;')
        if len(script_parts) > 1:
            # Remover a criação do banco de dados e a conexão a ele
            modified_script = script_parts[1]
            logger.info(f"SQLEXEC - Script modificado. Tamanho: {len(modified_script)} caracteres")
            
            # Dividir o script em comandos separados
            commands = modified_script.split(';')
            logger.info(f"SQLEXEC - Script dividido em {len(commands)} comandos.")
            
            # Executar cada comando separadamente
            successful_commands = 0
            failed_commands = 0
                
            for i, command in enumerate(commands):
                command = command.strip()
                if command and not command.startswith('--'):
                    try:
                        logger.info(f"SQLEXEC - Executando comando {i+1}/{len(commands)}: {command[:50]}...")
                        cursor.execute(command)
                        logger.info(f"SQLEXEC - Comando {i+1} executado com sucesso.")
                        successful_commands += 1
                    except Exception as cmd_error:
                        logger.error(f"SQLEXEC - Erro ao executar comando {i+1}: {str(cmd_error)}")
                        logger.error(f"SQLEXEC - Comando que falhou: {command[:100]}...")
                        failed_commands += 1
                        # Continuar com o próximo comando mesmo se este falhar
                
            logger.info(f"SQLEXEC - Execução de comandos concluída. Sucesso: {successful_commands}, Falhas: {failed_commands}")
        else:
            logger.warning("SQLEXEC - Não foi possível dividir o script corretamente. Tentando executar o script completo...")
            try:
                cursor.execute(sql_script)
                logger.info("SQLEXEC - Script SQL completo executado com sucesso.")
            except Exception as full_script_error:
                logger.error(f"SQLEXEC - Erro ao executar script SQL completo: {str(full_script_error)}")
                raise
            
        cursor.close()
        conn.close()
        logger.info("SQLEXEC - Conexão ao banco fipedata fechada.")
        
        response_data['Message'] = 'Script SQL executado com sucesso'
        logger.info("SQLEXEC - Operação concluída com sucesso.")
        logger.info("SQLEXEC - Enviando resposta de SUCESSO...")
        # Enviar resposta ao CloudFormation apenas se for um evento do CloudFormation
        if event.get('RequestType'):
            logger.info("SQLEXEC - Enviando resposta de SUCESSO para CloudFormation...")
            cfnresponse.send(event, context, cfnresponse.SUCCESS, response_data)
        logger.info("SQLEXEC - Resposta enviada. Função Lambda concluída com sucesso.")
        return {
            'statusCode': 200,
            'body': json.dumps('Operação concluída com sucesso')
        }
    
    except Exception as e:
        logger.error(f"SQLEXEC - Erro fatal na execução da função Lambda: {str(e)}", exc_info=True)
        response_data['Error'] = str(e)
        
        # Enviar resposta ao CloudFormation apenas se for um evento do CloudFormation
        if event.get('RequestType'):
            logger.info("SQLEXEC - Enviando resposta de FALHA para CloudFormation...")
            cfnresponse.send(event, context, cfnresponse.FAILED, response_data)
            logger.info("SQLEXEC - Resposta de falha enviada.")
        else:
            logger.info("SQLEXEC - Erro em invocação direta, não enviando resposta de CloudFormation.")
        return {
            'statusCode': 500,
            'body': json.dumps(f'Erro: {str(e)}')
        }