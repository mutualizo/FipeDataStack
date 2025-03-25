import os
from constructs import Construct
from aws_cdk import (
    Stack,
    NestedStack,
    Duration,
    CfnOutput,
    RemovalPolicy,
    Tags,
)
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_sqs as sqs
from aws_cdk import aws_lambda_event_sources as lambda_event_sources
from aws_cdk import aws_secretsmanager as secretsmanager

class FipeApiStack(NestedStack):
    def __init__(self, scope: Construct, construct_id: str, 
                vpc: ec2.Vpc, 
                db_cluster_endpoint: str,
                db_cluster_port: str,
                db_secret_arn: str,
                stage: str = "dev",
                **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Adicionar tag de estágio (stage) ao stack
        Tags.of(self).add("Stage", stage)
        Tags.of(self).add("Application", "FipeAPI")
        
        # Log da criação do stack
        print(f"Iniciando criação do FipeApiStack para o estágio: {stage}")
        print(f"Usando endpoint do banco de dados: {db_cluster_endpoint}")
        
        # Criar um grupo de segurança para a função Lambda que acessa o banco de dados
        lambda_security_group = ec2.SecurityGroup(
            self, f"FipeApiLambdaSecurityGroup-{stage}",
            vpc=vpc,
            description=f"Security group for the FIPE API Lambda functions - {stage}",
            allow_all_outbound=True
        )
        Tags.of(lambda_security_group).add("Stage", stage)
        print(f"Grupo de segurança para as Lambdas criado: {lambda_security_group.security_group_id}")
        
        # Permissões para as Lambdas chamarem uns aos outros, acessarem SQS e PostgreSQL
        lambda_role = iam.Role(
            self, f"FipeApiLambdaRole-{stage}",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole"),
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSQSFullAccess")
            ]
        )
        
        # Permissões específicas para a Lambda que acessa o banco de dados
        db_lambda_role = iam.Role(
            self, f"FipeApiDBLambdaRole-{stage}",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaVPCAccessExecutionRole"),
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole"),
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSQSFullAccess")
            ]
        )
        
        # Adicionar permissão explícita para acessar o Secrets Manager
        db_lambda_role.add_to_policy(iam.PolicyStatement(
            actions=["secretsmanager:GetSecretValue"],
            resources=[db_secret_arn]
        ))
        
        Tags.of(lambda_role).add("Stage", stage)
        Tags.of(db_lambda_role).add("Stage", stage)
        print(f"Roles para as Lambdas criadas")

        # Extrair o nome do segredo do ARN
        # ARN formato: arn:aws:secretsmanager:region:account-id:secret:secret-name-suffix
        secret_name = db_secret_arn.split(':')[-1]
        
        # Adicionar permissão para acessar o segredo do banco de dados
        db_secret = secretsmanager.Secret.from_secret_name_v2(
            self, f"ImportedDBSecret-{stage}", 
            secret_name
        )
        db_secret.grant_read(db_lambda_role)
        print(f"Permissão para acessar o segredo do banco de dados concedida à role")
        
        # Configuração de DLQ (Dead Letter Queue) para lidar com mensagens não processadas
        manufacturer_dlq = sqs.Queue(
            self, f"FipeManufacturerDLQ-{stage}",
            visibility_timeout=Duration.seconds(300),
            retention_period=Duration.days(14),  # Maior período de retenção para DLQ
            queue_name=f"fipe-manufacturer-dlq-{stage}"
        )
        Tags.of(manufacturer_dlq).add("Stage", stage)
        
        model_dlq = sqs.Queue(
            self, f"FipeModelDLQ-{stage}",
            visibility_timeout=Duration.seconds(300),
            retention_period=Duration.days(14),
            queue_name=f"fipe-model-dlq-{stage}"
        )
        Tags.of(model_dlq).add("Stage", stage)
        
        price_dlq = sqs.Queue(
            self, f"FipePriceDLQ-{stage}",
            visibility_timeout=Duration.seconds(300),
            retention_period=Duration.days(14),
            queue_name=f"fipe-price-dlq-{stage}"
        )
        Tags.of(price_dlq).add("Stage", stage)
        
        # Criar as filas SQS com DLQs configuradas desde o início
        manufacturer_queue = sqs.Queue(
            self, f"FipeManufacturerQueue-{stage}",
            visibility_timeout=Duration.seconds(300),
            retention_period=Duration.days(4),
            queue_name=f"fipe-manufacturer-queue-{stage}",
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=5,
                queue=manufacturer_dlq
            )
        )
        Tags.of(manufacturer_queue).add("Stage", stage)
        print(f"Fila SQS para fabricantes criada: {manufacturer_queue.queue_name}")
        
        model_queue = sqs.Queue(
            self, f"FipeModelQueue-{stage}",
            visibility_timeout=Duration.seconds(300),
            retention_period=Duration.days(4),
            queue_name=f"fipe-model-queue-{stage}",
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=5,
                queue=model_dlq
            )
        )
        Tags.of(model_queue).add("Stage", stage)
        print(f"Fila SQS para modelos criada: {model_queue.queue_name}")
        
        price_queue = sqs.Queue(
            self, f"FipePriceQueue-{stage}",
            visibility_timeout=Duration.seconds(300),
            retention_period=Duration.days(4),
            queue_name=f"fipe-price-queue-{stage}",
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=5,
                queue=price_dlq
            )
        )
        Tags.of(price_queue).add("Stage", stage)
        print(f"Fila SQS para preços criada: {price_queue.queue_name}")
        print("Filas DLQ configuradas para todas as filas SQS")
        
        # Criar uma camada Lambda a partir do arquivo ZIP em vez do diretório de assets
        lambda_layer = lambda_.LayerVersion(
            self, f"FipeApiLayer-{stage}",
            code=lambda_.Code.from_asset("fipe_api_layer.zip"),  # Usar arquivo ZIP diretamente
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_10],
            description=f"Layer for FIPE API Lambda functions - {stage}"
        )
        Tags.of(lambda_layer).add("Stage", stage)
        print(f"Camada Lambda para FIPE API criada a partir do arquivo ZIP")
        
        # Variáveis de ambiente comuns para todas as Lambdas
        common_env = {
            "STAGE": stage,
            "URL_FIPE": "http://veiculos.fipe.org.br/api/veiculos",
        }
        
        # Variáveis de ambiente específicas para cada Lambda
        manufacturer_loader_env = {
            **common_env,
            "SQS_OUTPUT_URL": manufacturer_queue.queue_url,
        }
        
        model_loader_env = {
            **common_env,
            "SQS_INPUT_URL": manufacturer_queue.queue_url,
            "SQS_OUTPUT_URL": model_queue.queue_url,
        }
        
        price_loader_env = {
            **common_env,
            "SQS_INPUT_URL": model_queue.queue_url,
            "SQS_OUTPUT_URL": price_queue.queue_url,
        }
        
        ingestor_env = {
            **common_env,
            "SQS_INPUT_URL": price_queue.queue_url,
            "RDS_HOST": db_cluster_endpoint,
            "RDS_PORT": db_cluster_port,
            "RDS_DATABASE": "fipedata",
            "RDS_USER": "postgres",
            "DB_SECRET_ARN": db_secret_arn,
        }
        
        # Criar as funções Lambda de API SEM VPC para acesso à internet
        print("Criando função FipeManufacturerLoader...")
        manufacturer_lambda = lambda_.Function(
            self, f"FipeManufacturerLoader-{stage}",
            function_name=f"FipeManufacturerLoader-{stage}",
            runtime=lambda_.Runtime.PYTHON_3_10,
            code=lambda_.Code.from_asset("src/fipe_api", exclude=["__pycache__", "*.pyc"]),
            handler="fipe_manufacturer_loader.lambda_handler",
            timeout=Duration.minutes(5),
            memory_size=256,
            environment=manufacturer_loader_env,
            role=lambda_role,
            layers=[lambda_layer],
            description="Função para carregar fabricantes da API FIPE"
        )
        Tags.of(manufacturer_lambda).add("Stage", stage)
        Tags.of(manufacturer_lambda).add("Function", "FipeManufacturerLoader")
        print(f"Lambda FipeManufacturerLoader criada: {manufacturer_lambda.function_name}")
        
        print("Criando função FipeModelLoader...")
        model_lambda = lambda_.Function(
            self, f"FipeModelLoader-{stage}",
            function_name=f"FipeModelLoader-{stage}",
            runtime=lambda_.Runtime.PYTHON_3_10,
            code=lambda_.Code.from_asset("src/fipe_api", exclude=["__pycache__", "*.pyc"]),
            handler="fipe_model_loader.lambda_handler",
            timeout=Duration.minutes(5),
            memory_size=256,
            environment=model_loader_env,
            role=lambda_role,
            layers=[lambda_layer],
            description="Função para carregar modelos da API FIPE"
        )
        Tags.of(model_lambda).add("Stage", stage)
        Tags.of(model_lambda).add("Function", "FipeModelLoader")
        print(f"Lambda FipeModelLoader criada: {model_lambda.function_name}")
        
        # Configurar a fonte de eventos SQS para a Lambda de modelo com configurações otimizadas
        model_lambda.add_event_source(
            lambda_event_sources.SqsEventSource(
                manufacturer_queue, 
                batch_size=10,
                max_batching_window=Duration.seconds(30),  # Permitir até 30 segundos para agrupar mensagens
                report_batch_item_failures=True  # Habilitar relatório de falhas por item
            )
        )
        print(f"Fonte de evento SQS adicionada à Lambda {model_lambda.function_name}")
        
        print("Criando função FipePriceLoader...")
        price_lambda = lambda_.Function(
            self, f"FipePriceLoader-{stage}",
            function_name=f"FipePriceLoader-{stage}",
            runtime=lambda_.Runtime.PYTHON_3_10,
            code=lambda_.Code.from_asset("src/fipe_api", exclude=["__pycache__", "*.pyc"]),
            handler="fipe_price_loader.lambda_handler",
            timeout=Duration.minutes(5),
            memory_size=256,
            environment=price_loader_env,
            role=lambda_role,
            layers=[lambda_layer],
            description="Função para carregar preços da API FIPE"
        )
        Tags.of(price_lambda).add("Stage", stage)
        Tags.of(price_lambda).add("Function", "FipePriceLoader")
        print(f"Lambda FipePriceLoader criada: {price_lambda.function_name}")
        
        # Configurar a fonte de eventos SQS para a Lambda de preço com configurações otimizadas
        price_lambda.add_event_source(
            lambda_event_sources.SqsEventSource(
                model_queue, 
                batch_size=10,
                max_batching_window=Duration.seconds(30),
                report_batch_item_failures=True
            )
        )
        print(f"Fonte de evento SQS adicionada à Lambda {price_lambda.function_name}")
        
        # A função ingestora CONTINUA usando VPC para acessar o banco de dados
        print("Criando função FipeSomaIngestor...")
        ingestor_lambda = lambda_.Function(
            self, f"FipeSomaIngestor-{stage}",
            function_name=f"FipeSomaIngestor-{stage}",
            runtime=lambda_.Runtime.PYTHON_3_10,
            code=lambda_.Code.from_asset("src/fipe_api", exclude=["__pycache__", "*.pyc"]),
            handler="fipe_soma_ingestor.lambda_handler",  # Nome do handler corrigido
            timeout=Duration.minutes(5),
            memory_size=512,
            environment=ingestor_env,
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            allow_public_subnet=True,
            security_groups=[lambda_security_group],
            role=db_lambda_role,
            layers=[lambda_layer],
            description="Função para ingerir dados da FIPE no banco de dados"
        )
        Tags.of(ingestor_lambda).add("Stage", stage)
        Tags.of(ingestor_lambda).add("Function", "FipeSomaIngestor")
        print(f"Lambda FipeSomaIngestor criada: {ingestor_lambda.function_name}")
        
        # Configurar a fonte de eventos SQS para a Lambda ingestora com configurações otimizadas
        ingestor_lambda.add_event_source(
            lambda_event_sources.SqsEventSource(
                price_queue, 
                batch_size=10,
                max_batching_window=Duration.seconds(30),
                report_batch_item_failures=True
            )
        )
        print(f"Fonte de evento SQS adicionada à Lambda {ingestor_lambda.function_name}")
        
        # Outputs
        CfnOutput(
            self, f"ManufacturerQueueUrl-{stage}",
            value=manufacturer_queue.queue_url,
            description=f"URL da fila SQS para fabricantes - {stage}"
        )
        
        CfnOutput(
            self, f"ModelQueueUrl-{stage}",
            value=model_queue.queue_url,
            description=f"URL da fila SQS para modelos - {stage}"
        )
        
        CfnOutput(
            self, f"PriceQueueUrl-{stage}",
            value=price_queue.queue_url,
            description=f"URL da fila SQS para preços - {stage}"
        )
        
        CfnOutput(
            self, f"ManufacturerDLQUrl-{stage}",
            value=manufacturer_dlq.queue_url,
            description=f"URL da fila DLQ para fabricantes - {stage}"
        )
        
        CfnOutput(
            self, f"ModelDLQUrl-{stage}",
            value=model_dlq.queue_url,
            description=f"URL da fila DLQ para modelos - {stage}"
        )
        
        CfnOutput(
            self, f"PriceDLQUrl-{stage}",
            value=price_dlq.queue_url,
            description=f"URL da fila DLQ para preços - {stage}"
        )
        
        CfnOutput(
            self, f"FipeManufacturerLambda-{stage}",
            value=manufacturer_lambda.function_name,
            description=f"Nome da função Lambda para carregamento de fabricantes - {stage}"
        )
        
        print(f"Criação do FipeApiStack concluída com sucesso para o estágio: {stage}")