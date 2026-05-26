import boto3
import os
import re
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def get_db_auth_token(host, port, user, region=None):
    """
    Gera token IAM para autenticação RDS (válido por 15 minutos).

    Args:
        host: RDS endpoint hostname
        port: RDS port (padrão: 5432)
        user: Database user (para IAM auth, tipicamente 'iamdb')
        region: AWS region (detectada automaticamente se não fornecida)

    Returns:
        str: Token IAM temporário para autenticação
    """
    if not region:
        region = _extract_region_from_host(host)

    try:
        rds_client = boto3.client('rds', region_name=region)
        token = rds_client.generate_db_auth_token(
            DBHostname=host,
            Port=int(port),
            DBUsername=user,
            Region=region
        )
        logger.debug(f"Token IAM gerado para {user}@{host} (região: {region})")
        return token
    except ValueError as e:
        error_msg = f"Erro ao gerar token IAM RDS: Parâmetros inválidos - {str(e)}"
        logger.error(error_msg)
        raise
    except Exception as e:
        error_msg = f"Erro ao gerar token IAM RDS para {user}@{host} em {region}: {str(e)}"
        logger.error(error_msg)
        raise ValueError(error_msg)

def _extract_region_from_host(host):
    """Extrai a região do RDS endpoint usando regex.

    Exemplos:
    - fipedatacluster-stg.cluster-cdqeius2qmwf.us-east-2.rds.amazonaws.com → us-east-2
    - fipedatacluster-prd.cluster-chkg2mxlx9z0.us-east-1.rds.amazonaws.com → us-east-1
    """
    # Pattern: .REGION.rds.amazonaws.com onde REGION é 2 letras-palavra-dígito
    match = re.search(r'\.([a-z]{2}-[a-z]+-\d+)\.rds\.amazonaws\.com', host)
    if match:
        region = match.group(1)
        logger.debug(f"Região extraída de {host}: {region}")
        return region

    # Se não encontrar, erro explícito (não fallback silencioso)
    error_msg = f"Não foi possível extrair região de RDS endpoint: {host}"
    logger.error(error_msg)
    raise ValueError(error_msg)
