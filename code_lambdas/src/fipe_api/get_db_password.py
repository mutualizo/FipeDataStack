import json
import boto3
import os

def get_db_password():
    """
    Recupera a senha do banco de dados do AWS Secrets Manager.
    Usado pelo fipe_soma_ingestor.py para estabelecer conexão com o RDS.
    
    Returns:
        str: A senha do banco de dados
    """
    secret_arn = os.environ.get('DB_SECRET_ARN')
    
    if not secret_arn:
        raise ValueError("DB_SECRET_ARN não está definido nas variáveis de ambiente")
    
    secrets_client = boto3.client('secretsmanager')
    secret_value = secrets_client.get_secret_value(SecretId=secret_arn)
    secret = json.loads(secret_value['SecretString'])
    
    return secret['password']
