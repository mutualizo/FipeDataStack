import os
import time
import logging
from .fipe_api_service import FipeAPI

# Configuração do logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    """
    Função Lambda para carregar fabricantes da API FIPE e enviar para a fila SQS.
    
    Esta função consulta a API FIPE para obter a lista de fabricantes para cada tipo
    de veículo (carro, moto, caminhão) e envia os dados para a fila SQS.
    
    Args:
        event: Evento AWS Lambda
        context: Contexto AWS Lambda
        
    Returns:
        dict: Resultado da execução
    """
    logger.info("Iniciando FipeManufacturerLoader...")
    
    try:
        fipe_api = FipeAPI()
        # Usar a variável de ambiente específica para a fila de saída
        queue_url = os.environ.get('SQS_OUTPUT_URL')
        
        if not queue_url:
            logger.error("Variável de ambiente SQS_OUTPUT_URL não definida")
            return {
                'statusCode': 500,
                'body': 'Erro: SQS_OUTPUT_URL não definida'
            }
        
        logger.info(f"Usando fila SQS: {queue_url}")
        
        # Tipos de veículos: 1=Carro, 2=Moto, 3=Caminhão
        vehicle_types = [3, 1, 2]
        delay = 1.0  # Delay para evitar limitação de taxa da API
        total_manufacturers = 0
        
        for vehicle_type in vehicle_types:
            try:
                logger.info(f"Processando tipo de veículo {vehicle_type}...")
                
                # Mapear códigos para nomes legíveis
                vehicle_type_name = {1: "Carro", 2: "Moto", 3: "Caminhão"}.get(vehicle_type, "Desconhecido")
                logger.info(f"Consultando fabricantes para: {vehicle_type_name}")
                
                brands = fipe_api.get_brands(vehicle_type)
                
                if not brands:
                    logger.warning(f"Nenhum fabricante encontrado para o tipo de veículo {vehicle_type_name}")
                    continue
                
                logger.info(f"Encontrados {len(brands)} fabricantes para o tipo de veículo {vehicle_type_name}")
                
                for brand in brands:
                    brand_code = brand.get('Value')
                    brand_name = brand.get('Label')
                    
                    if not (brand_code and brand_name):
                        logger.warning(f"Dados incompletos para fabricante: {brand}")
                        continue
                    
                    logger.info(f"Processando fabricante '{brand_name}' (Código: {brand_code}) para tipo {vehicle_type_name}")
                    
                    message = {
                        "codigoTabelaReferencia": fipe_api.reference_table_code,
                        "mesReferenciaAno": fipe_api.reference_month_name,
                        "codigoMarca": brand_code,
                        "nomeMarca": brand_name,
                        "codigoTipoVeiculo": vehicle_type
                    }
                    
                    fipe_api.send_message_sqs(queue_url, message)
                    total_manufacturers += 1
                    
                    # Adicionar um pequeno delay para evitar atingir limites de API
                    time.sleep(delay)
            
            except Exception as e:
                logger.error(f"Erro ao processar tipo de veículo {vehicle_type_name}: {str(e)}")
                # Continuar com o próximo tipo de veículo mesmo se houver um erro
        
        logger.info(f"Processamento concluído. Total de fabricantes enviados: {total_manufacturers}")
        
        return {
            'statusCode': 200,
            'body': f'Processamento concluído com sucesso! Total de fabricantes: {total_manufacturers}'
        }
    
    except Exception as e:
        logger.error(f"Erro não tratado: {str(e)}")
        return {
            'statusCode': 500,
            'body': f'Erro inesperado: {str(e)}'
        }
