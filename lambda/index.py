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

# Adicionar um prefixo aos logs para facilitar a depuração
log_prefix = "SQLEXEC - "

def log_info(message):
    logger.info(f"{log_prefix}{message}")

def log_error(message):
    logger.error(f"{log_prefix}{message}")

def log_warning(message):
    logger.warning(f"{log_prefix}{message}")

def handler(event, context):
    log_info(f"Iniciando função Lambda com RequestType: {event.get('RequestType')}")
    log_info(f"Contexto: RequestID={context.aws_request_id}, RemainingTime={context.get_remaining_time_in_millis()}ms")
    
    response_data = {}
    
    try:
        # Verificar se o evento é um evento de CloudFormation Custom Resource
        request_type = event.get('RequestType')
        log_info(f"Tipo de evento recebido: {request_type if request_type else 'Evento direto (não CloudFormation)'}")
        
        # Se for um evento de CloudFormation e não for um evento Create, retornamos sucesso
        if request_type and request_type != 'Create':
            log_info(f"Evento {request_type} não requer ação. Retornando sucesso.")
            cfnresponse.send(event, context, cfnresponse.SUCCESS, {})
            return {'statusCode': 200, 'body': json.dumps('Nenhuma ação necessária')}
            
        # Se não for um evento CloudFormation ou for um evento Create, processamos normalmente
        log_info("Processando evento de criação/invocação direta...")
        
        # Obter as credenciais do banco de dados do Secrets Manager
        log_info("Obtendo credenciais do banco de dados do Secrets Manager...")
        secret_arn = os.environ.get('SECRET_ARN')
        log_info(f"Secret ARN: {secret_arn}")
        
        secrets_client = boto3.client('secretsmanager')
        secret_value = secrets_client.get_secret_value(SecretId=secret_arn)
        secret = json.loads(secret_value['SecretString'])
        username = secret['username']
        log_info(f"Nome de usuário obtido: {username}")
        log_info("Credenciais obtidas com sucesso.")
        
        # Ler o script SQL do sistema de arquivos local
        log_info("Lendo o script SQL do arquivo local...")
        try:
            script_path = os.path.join(os.path.dirname(__file__), "assets", "create_fipe_db.sql")
            log_info(f"Caminho do script SQL: {script_path}")
            log_info(f"Verificando existência do arquivo: {os.path.exists(script_path)}")
            log_info(f"Conteúdo do diretório: {os.listdir(os.path.dirname(script_path)) if os.path.exists(os.path.dirname(script_path)) else 'Diretório não encontrado'}")
            
            with open(script_path, 'r') as file:
                sql_script = file.read()
            log_info(f"Script SQL lido com sucesso. Tamanho: {len(sql_script)} caracteres")
            log_info(f"Primeiros 100 caracteres do script: {sql_script[:100]}...")
        except Exception as e:
            log_error(f"Erro ao ler script SQL do arquivo local: {str(e)}")
            raise
        
        # Obter informações do endpoint do banco de dados
        db_endpoint = os.environ.get('DB_ENDPOINT')
        db_port = int(os.environ.get('DB_PORT'))
        log_info(f"Endpoint do banco de dados: {db_endpoint}:{db_port}")
        
        # Aguardar que o banco de dados esteja disponível
        log_info("Aguardando 60 segundos para garantir que o cluster RDS esteja pronto...")
        time.sleep(60)
        log_info("Tempo de espera concluído.")
        
        # Tentar conectar ao banco de dados postgres padrão
        retry_count = 0
        max_retries = 5
        retry_delay = 30
        connected = False
        
        while not connected and retry_count < max_retries:
            try:
                log_info(f"Tentativa {retry_count + 1} de conexão ao banco postgres...")
                conn = psycopg2.connect(
                    host=db_endpoint,
                    port=db_port,
                    user=username,
                    password=secret['password'],
                    dbname='postgres',
                    connect_timeout=30
                )
                conn.autocommit = True
                log_info("Conexão estabelecida com sucesso ao banco postgres.")
                connected = True
            except Exception as conn_error:
                log_error(f"Erro ao conectar: {str(conn_error)}")
                retry_count += 1
                if retry_count < max_retries:
                    log_info(f"Aguardando {retry_delay} segundos antes da próxima tentativa...")
                    time.sleep(retry_delay)
                else:
                    log_error(f"Máximo de tentativas excedido. Falha na conexão.")
                    raise
        
        # Verificar se o banco de dados fipedata já existe
        log_info("Verificando se o banco de dados fipedata já existe...")
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM pg_database WHERE datname='fipedata'")
        exists = cursor.fetchone()
        
        if not exists:
            # Criar o banco de dados fipedata
            log_info("Criando o banco de dados fipedata...")
            try:
                cursor.execute("CREATE DATABASE fipedata")
                log_info("Banco de dados fipedata criado com sucesso.")
            except Exception as db_error:
                log_error(f"Erro ao criar banco de dados fipedata: {str(db_error)}")
                raise
        else:
            log_info("Banco de dados fipedata já existe.")
        
        cursor.close()
        conn.close()
        log_info("Conexão ao banco postgres fechada.")
        
        # Aguardar para garantir que o banco de dados seja criado
        log_info("Aguardando 20 segundos para garantir que o banco fipedata esteja disponível...")
        time.sleep(20)
        
        # Conectar ao novo banco de dados
        log_info("Conectando ao banco de dados fipedata...")
        retry_count = 0
        connected = False
        
        while not connected and retry_count < max_retries:
            try:
                log_info(f"Tentativa {retry_count + 1} de conexão ao banco fipedata...")
                conn = psycopg2.connect(
                    host=db_endpoint,
                    port=db_port,
                    user=username,
                    password=secret['password'],
                    dbname='fipedata',
                    connect_timeout=30
                )
                conn.autocommit = True
                log_info("Conexão estabelecida com sucesso ao banco fipedata.")
                connected = True
            except Exception as fipe_conn_error:
                log_error(f"Erro ao conectar: {str(fipe_conn_error)}")
                retry_count += 1
                if retry_count < max_retries:
                    log_info(f"Aguardando {retry_delay} segundos antes da próxima tentativa...")
                    time.sleep(retry_delay)
                else:
                    log_error(f"Máximo de tentativas excedido. Falha na conexão ao fipedata.")
                    raise
        
        # Executar o restante do script SQL
        log_info("Preparando para executar as sequências e tabelas...")
        cursor = conn.cursor()
        
        # Remover as partes do script que já executamos manualmente
        script_parts = sql_script.split('\\c fipedata;')
        if len(script_parts) > 1:
            # Remover a criação do banco de dados e a conexão a ele
            modified_script = script_parts[1]
            log_info(f"Script modificado. Tamanho: {len(modified_script)} caracteres")
            
            # Dividir o script em comandos separados
            commands = modified_script.split(';')
            log_info(f"Script dividido em {len(commands)} comandos.")
            
            # Executar cada comando separadamente
            successful_commands = 0
            failed_commands = 0
            
            for i, command in enumerate(commands):
                command = command.strip()
                if command and not command.startswith('--'):
                    try:
                        log_info(f"Executando comando {i+1}/{len(commands)}: {command[:50]}...")
                        cursor.execute(command)
                        log_info(f"Comando {i+1} executado com sucesso.")
                        successful_commands += 1
                    except Exception as cmd_error:
                        log_error(f"Erro ao executar comando {i+1}: {str(cmd_error)}")
                        log_error(f"Comando que falhou: {command[:100]}...")
                        failed_commands += 1
                        # Continuar com o próximo comando mesmo se este falhar
            
            log_info(f"Execução de comandos concluída. Sucesso: {successful_commands}, Falhas: {failed_commands}")
        else:
            log_warning("Não foi possível dividir o script corretamente. Tentando executar o script completo...")
            try:
                cursor.execute(sql_script)
                log_info("Script SQL completo executado com sucesso.")
            except Exception as full_script_error:
                log_error(f"Erro ao executar script SQL completo: {str(full_script_error)}")
                raise
        
        cursor.close()
        conn.close()
        log_info("Conexão ao banco fipedata fechada.")
        
        response_data['Message'] = 'Script SQL executado com sucesso'
        log_info("Operação concluída com sucesso.")
        
        # Enviar resposta ao CloudFormation apenas se for um evento do CloudFormation
        if event.get('RequestType'):
            log_info("Enviando resposta de SUCESSO para CloudFormation...")
            cfnresponse.send(event, context, cfnresponse.SUCCESS, response_data)
        log_info("Função Lambda concluída com sucesso.")
        return {
            'statusCode': 200,
            'body': json.dumps('Operação concluída com sucesso')
        }
    
    except Exception as e:
        log_error(f"Erro fatal na execução da função Lambda: {str(e)}")
        response_data['Error'] = str(e)
        
        # Enviar resposta ao CloudFormation apenas se for um evento do CloudFormation
        if event.get('RequestType'):
            log_info("Enviando resposta de FALHA para CloudFormation...")
            cfnresponse.send(event, context, cfnresponse.FAILED, response_data)
            log_info("Resposta de falha enviada.")
        else:
            log_info("Erro em invocação direta, não enviando resposta de CloudFormation.")
        return {
            'statusCode': 500,
            'body': json.dumps(f'Erro: {str(e)}')
        }