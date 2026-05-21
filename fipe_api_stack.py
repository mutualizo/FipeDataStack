# fipe_api_stack.py

import os
from pathlib import Path
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
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets

class FipeApiStack(NestedStack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        vpc: ec2.Vpc,
        db_cluster_endpoint: str,
        db_cluster_port: str,
        db_secret_arn: str,
        stage: str = "dev",
        rds_endpoints: dict = None,
        rds_secrets_arns: dict = None,
        **kwargs
    ) -> None:
        """
        MELHORIA 2: Stack de Lambdas + SQS única em sa-east-1

        Args:
            rds_endpoints: Dict com endpoints remotos {"stg": "...", "prd": "..."}
                          Usado para FipeSomaIngestor fazer dual-write
            rds_secrets_arns: Dict com ARNs das secrets {"stg": "...", "prd": "..."}
                            Usado para dual-write com senhas diferentes
        """
        super().__init__(scope, construct_id, **kwargs)

        script_dir = os.path.dirname(os.path.realpath(__file__))

        Tags.of(self).add("stage", stage)
        Tags.of(self).add("application", "FipeAPI")

        print(f"[FipeApiStack] Criando Lambdas + SQS em {stage}")
        print(f"[FipeApiStack] Endpoint RDS: {db_cluster_endpoint}")
        if rds_endpoints:
            print(f"[FipeApiStack] RDS Endpoints remotos: STG={rds_endpoints.get('stg')}, PRD={rds_endpoints.get('prd')}")
        
        # Security Group para Lambdas (sem sufixo de stage)
        self.lambda_security_group = ec2.SecurityGroup(
            self, "FipeApiLambdaSecurityGroup",  # Sem sufixo
            vpc=vpc,
            description="Security group for FIPE API Lambda functions",
            allow_all_outbound=True
        )
        Tags.of(self.lambda_security_group).add("stage", stage)
        print(f"[FipeApiStack] Security Group criado: {self.lambda_security_group.security_group_id}")

        # IAM Role para Lambdas (sem sufixo de stage)
        lambda_role = iam.Role(
            self, "FipeApiLambdaRole",  # Sem sufixo
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole")
            ]
        )


        # IAM Role para Lambdas com acesso a RDS (sem sufixo de stage)
        db_lambda_role = iam.Role(
            self, "FipeApiDBLambdaRole",  # Sem sufixo
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaVPCAccessExecutionRole"),
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole"),
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSQSFullAccess")
            ]
        )

        # Adicionar acesso IAM para RDS authentication (especificar clusters, não wildcard)
        # RDS STG em us-east-2 e RDS PRD em us-east-1
        db_lambda_role.add_to_policy(iam.PolicyStatement(
            actions=["rds-db:connect"],
            resources=[
                f"arn:aws:rds:us-east-2:*:db:fipedatacluster-stg",
                f"arn:aws:rds:us-east-1:*:db:fipedatacluster-prd"
            ]
        ))

        Tags.of(lambda_role).add("stage", stage)
        Tags.of(db_lambda_role).add("stage", stage)
        print(f"[FipeApiStack] Roles criadas com IAM RDS auth")

        # ====================================================================
        # SQS Queues (sem sufixo de stage - Standard)
        # ====================================================================

        # DLQs (Dead Letter Queues) - com KMS encryption
        manufacturer_dlq = sqs.Queue(
            self,
            "FipeManufacturerDLQ",  # Sem sufixo
            visibility_timeout=Duration.seconds(600),
            retention_period=Duration.days(14),
            queue_name="fipe-manufacturer-dlq",
            encryption=sqs.SqsEncryption.KMS_MANAGED
        )
        Tags.of(manufacturer_dlq).add("stage", stage)

        model_dlq = sqs.Queue(
            self,
            "FipeModelDLQ",  # Sem sufixo
            visibility_timeout=Duration.seconds(600),
            retention_period=Duration.days(14),
            queue_name="fipe-model-dlq",
            encryption=sqs.SqsEncryption.KMS_MANAGED
        )
        Tags.of(model_dlq).add("stage", stage)

        price_dlq = sqs.Queue(
            self,
            "FipePriceDLQ",  # Sem sufixo
            visibility_timeout=Duration.seconds(600),
            retention_period=Duration.days(14),
            queue_name="fipe-price-dlq",
            encryption=sqs.SqsEncryption.KMS_MANAGED
        )
        Tags.of(price_dlq).add("stage", stage)

        # Main Queues (com DLQ e KMS encryption)
        manufacturer_queue = sqs.Queue(
            self,
            "FipeManufacturerQueue",  # Sem sufixo
            visibility_timeout=Duration.seconds(1000),
            retention_period=Duration.days(4),
            queue_name="fipe-manufacturer-queue",
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=10,
                queue=manufacturer_dlq
            ),
            encryption=sqs.SqsEncryption.KMS_MANAGED
        )
        Tags.of(manufacturer_queue).add("stage", stage)
        print(f"[FipeApiStack] Fila Manufacturer criada: {manufacturer_queue.queue_name}")

        model_queue = sqs.Queue(
            self,
            "FipeModelQueue",  # Sem sufixo
            visibility_timeout=Duration.seconds(1000),
            retention_period=Duration.days(4),
            queue_name="fipe-model-queue",
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=10,
                queue=model_dlq
            ),
            encryption=sqs.SqsEncryption.KMS_MANAGED
        )
        Tags.of(model_queue).add("stage", stage)
        print(f"[FipeApiStack] Fila Model criada: {model_queue.queue_name}")

        price_queue = sqs.Queue(
            self,
            "FipePriceQueue",  # Sem sufixo
            visibility_timeout=Duration.seconds(1000),
            retention_period=Duration.days(4),
            queue_name="fipe-price-queue",
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=10,
                queue=price_dlq
            ),
            encryption=sqs.SqsEncryption.KMS_MANAGED
        )
        Tags.of(price_queue).add("stage", stage)
        print(f"[FipeApiStack] Fila Price criada: {price_queue.queue_name}")

        # Adicionar SQS permissions específicas após criar as filas (least privilege)
        lambda_role.add_to_policy(iam.PolicyStatement(
            actions=[
                "sqs:SendMessage",
                "sqs:ReceiveMessage",
                "sqs:DeleteMessage",
                "sqs:GetQueueAttributes",
                "sqs:ChangeMessageVisibility"
            ],
            resources=[
                manufacturer_queue.queue_arn,
                model_queue.queue_arn,
                price_queue.queue_arn,
                manufacturer_dlq.queue_arn,
                model_dlq.queue_arn,
                price_dlq.queue_arn
            ]
        ))

        # Lambda Layer (sem sufixo)
        lambda_layer = lambda_.LayerVersion(
            self,
            "FipeApiLayer",  # Sem sufixo
            code=lambda_.Code.from_asset(os.path.join(script_dir, "fipe_api_layer.zip")),
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_12],
            description="Layer for FIPE API Lambda functions"
        )
        Tags.of(lambda_layer).add("stage", stage)
        print(f"[FipeApiStack] Lambda Layer criada")
        
        common_env = {"STAGE": stage, "URL_FIPE": "https://veiculos.fipe.org.br/api/veiculos"}
        manufacturer_loader_env = {**common_env, 
                                   "SQS_OUTPUT_URL": manufacturer_queue.queue_url, 
                                   "TEST": "false"}
        model_loader_env = {**common_env, 
                            "SQS_INPUT_URL": manufacturer_queue.queue_url, 
                            "SQS_OUTPUT_URL": model_queue.queue_url}
        price_loader_env = {**common_env, 
                            "SQS_INPUT_URL": model_queue.queue_url, 
                            "SQS_OUTPUT_URL": price_queue.queue_url}
        ingestor_env = {**common_env,
                        "SQS_INPUT_URL": price_queue.queue_url,
                        "RDS_HOST": db_cluster_endpoint or "remote-rds",
                        "RDS_PORT": db_cluster_port or "5432",
                        "RDS_DATABASE": "fipedata",
                        "RDS_USER": "postgres"}
        
        # ====================================================================
        # LAMBDAS (sem sufixo de stage)
        # ====================================================================

        # 1. FipeManufacturerLoader
        manufacturer_lambda = lambda_.Function(
            self,
            "FipeManufacturerLoader",  # Sem sufixo
            function_name="FipeManufacturerLoader",  # Sem sufixo
            runtime=lambda_.Runtime.PYTHON_3_12,
            code=lambda_.Code.from_asset(
                os.path.join(script_dir, "code_lambdas/src/fipe_api"),
                exclude=["__pycache__", "*.pyc"]
            ),
            handler="fipe_manufacturer_loader.lambda_handler",
            timeout=Duration.minutes(10),
            memory_size=256,
            environment=manufacturer_loader_env,
            role=lambda_role,
            layers=[lambda_layer],
            description="FIPE - 01) Função para carregar fabricantes da API FIPE"
        )
        Tags.of(manufacturer_lambda).add("stage", stage)
        Tags.of(manufacturer_lambda).add("function", "FipeManufacturerLoader")
        print(f"[FipeApiStack] Lambda FipeManufacturerLoader criada")

        # EventBridge Rule para execução mensal (sem sufixo)
        monthly_rule = events.Rule(
            self,
            "FipeManufacturerMonthlyRule",  # Sem sufixo
            schedule=events.Schedule.cron(minute="0", hour="1", day="4", month="*", year="*"),
            description="Executa FipeManufacturerLoader no 4º dia do mês"
        )
        monthly_rule.add_target(targets.LambdaFunction(manufacturer_lambda))
        manufacturer_lambda.add_permission(
            "AllowEventBridgeInvoke",  # Sem sufixo
            principal=iam.ServicePrincipal("events.amazonaws.com"),
            source_arn=monthly_rule.rule_arn
        )
        print(f"[FipeApiStack] EventBridge Rule criada para execução mensal")
        
        # 2. FipeModelLoader
        model_lambda = lambda_.Function(
            self,
            "FipeModelLoader",  # Sem sufixo
            function_name="FipeModelLoader",  # Sem sufixo
            runtime=lambda_.Runtime.PYTHON_3_12,
            code=lambda_.Code.from_asset(os.path.join(script_dir, "code_lambdas/src/fipe_api"), exclude=["__pycache__", "*.pyc"]),
            handler="fipe_model_loader.lambda_handler",
            timeout=Duration.minutes(5),
            memory_size=256,
            environment=model_loader_env,
            role=lambda_role,
            layers=[lambda_layer],
            description="FIPE - 02) Função para carregar modelos da API FIPE",
            reserved_concurrent_executions=5
        )
        Tags.of(model_lambda).add("stage", stage)
        Tags.of(model_lambda).add("function", "FipeModelLoader")
        model_lambda.add_event_source(
            lambda_event_sources.SqsEventSource(
                manufacturer_queue,
                batch_size=10,
                report_batch_item_failures=True
            )
        )
        print(f"[FipeApiStack] Lambda FipeModelLoader criada")

        # 3. FipePriceLoader
        price_lambda = lambda_.Function(
            self,
            "FipePriceLoader",  # Sem sufixo
            function_name="FipePriceLoader",  # Sem sufixo
            runtime=lambda_.Runtime.PYTHON_3_12,
            code=lambda_.Code.from_asset(os.path.join(script_dir, "code_lambdas/src/fipe_api"), exclude=["__pycache__", "*.pyc"]),
            handler="fipe_price_loader.lambda_handler",
            timeout=Duration.minutes(5),
            memory_size=256,
            environment=price_loader_env,
            role=lambda_role,
            layers=[lambda_layer],
            description="FIPE - 03) Função para carregar preços da API FIPE",
            reserved_concurrent_executions=10
        )
        Tags.of(price_lambda).add("stage", stage)
        Tags.of(price_lambda).add("function", "FipePriceLoader")
        price_lambda.add_event_source(
            lambda_event_sources.SqsEventSource(
                model_queue,
                batch_size=10,
                report_batch_item_failures=True
            )
        )
        print(f"[FipeApiStack] Lambda FipePriceLoader criada")

        # 4. FipeSomaIngestor (com dual-write RDS)
        # Preparar environment com RDS endpoints remotos
        ingestor_env_final = ingestor_env.copy()
        if rds_endpoints:
            # Adicionar endpoints remotos para dual-write
            ingestor_env_final["RDS_ENDPOINTS_STG"] = rds_endpoints.get("stg", "")
            ingestor_env_final["RDS_ENDPOINTS_PRD"] = rds_endpoints.get("prd", "")
            print(f"[FipeApiStack] Ingestor configurado com RDS endpoints remotos para dual-write")


        ingestor_lambda = lambda_.Function(
            self,
            "FipeSomaIngestor",  # Sem sufixo
            function_name="FipeSomaIngestor",  # Sem sufixo
            runtime=lambda_.Runtime.PYTHON_3_12,
            code=lambda_.Code.from_asset(os.path.join(script_dir, "code_lambdas/src/fipe_api"), exclude=["__pycache__", "*.pyc"]),
            handler="fipe_soma_ingestor.lambda_handler",
            timeout=Duration.minutes(15),
            memory_size=512,
            environment=ingestor_env_final,
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            allow_public_subnet=False,
            security_groups=[self.lambda_security_group],
            role=db_lambda_role,
            layers=[lambda_layer],
            description="FIPE - 04) Função para ingerir dados da FIPE no banco de dados",
            reserved_concurrent_executions=20
        )
        Tags.of(ingestor_lambda).add("stage", stage)
        Tags.of(ingestor_lambda).add("function", "FipeSomaIngestor")
        ingestor_lambda.add_event_source(
            lambda_event_sources.SqsEventSource(
                price_queue,
                batch_size=10,
                report_batch_item_failures=True
            )
        )
        print(f"[FipeApiStack] Lambda FipeSomaIngestor criada")

        print("Criando função RedriveLambda...")
        redrive_lambda = lambda_.Function(
            self,
            "RedriveDLQLambda",  # Sem sufixo
            function_name="RedriveDLQLambda",  # Sem sufixo
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="fipe_redrive_flq.lambda_handler",
            code=lambda_.Code.from_asset(os.path.join(script_dir, "code_lambdas/src/fipe_api"), exclude=["__pycache__", "*.pyc"]),
            role=lambda_role,
            timeout=Duration.seconds(300),
            memory_size=256,
            description="FIPE - 05) Função para recuperar mensagens das DLQs e reenviá-las para as filas principais",
            environment={
                "DLQ_URLS": f"{manufacturer_dlq.queue_url},{model_dlq.queue_url},{price_dlq.queue_url}",
                "MAIN_QUEUE_URLS": f"{manufacturer_queue.queue_url},{model_queue.queue_url},{price_queue.queue_url}",
            },
        )
        Tags.of(redrive_lambda).add("stage", stage)
        Tags.of(redrive_lambda).add("function", "RedriveDLQLambda")
        print(f"Lambda RedriveDLQLambda criada: {redrive_lambda.function_name}")


        # CloudFormation Outputs (sem sufixo de stage)
        CfnOutput(self, "ManufacturerQueueUrl", value=manufacturer_queue.queue_url, description="URL da fila SQS para fabricantes")
        CfnOutput(self, "ModelQueueUrl", value=model_queue.queue_url, description="URL da fila SQS para modelos")
        CfnOutput(self, "PriceQueueUrl", value=price_queue.queue_url, description="URL da fila SQS para preços")
        CfnOutput(self, "ManufacturerDLQUrl", value=manufacturer_dlq.queue_url, description="URL da fila DLQ para fabricantes")
        CfnOutput(self, "ModelDLQUrl", value=model_dlq.queue_url, description="URL da fila DLQ para modelos")
        CfnOutput(self, "PriceDLQUrl", value=price_dlq.queue_url, description="URL da fila DLQ para preços")
        CfnOutput(self, "FipeManufacturerLambda", value=manufacturer_lambda.function_name, description="Nome da função Lambda para carregamento de fabricantes")
        CfnOutput(self, "MonthlyEventRuleArn", value=monthly_rule.rule_arn, description="ARN da regra CloudWatch Events para execução mensal")

        print(f"[FipeApiStack] Criação concluída com sucesso")