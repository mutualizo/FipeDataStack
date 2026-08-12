# fipe_api_stack.py

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
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_cloudwatch as cw
from aws_cdk import aws_cloudwatch_actions as cwa
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as sns_subscriptions

class FipeApiStack(NestedStack):
    def __init__(self, scope: Construct, construct_id: str,
                vpc: ec2.Vpc,
                db_cluster_endpoint: str,
                db_cluster_port: str,
                db_secret_arn: str,
                stage: str = "dev",
                sqs_forwarding_stg: str = None,
                sqs_forwarding_prd: str = None,
                **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ... (código inicial sem alterações) ...
        Tags.of(self).add("stage", stage)
        Tags.of(self).add("application", "FipeAPI")
        
        print(f"Iniciando criação do FipeApiStack para o estágio: {stage}")
        print(f"Usando endpoint do banco de dados (via proxy): {db_cluster_endpoint}")
        
        self.lambda_security_group = ec2.SecurityGroup(
            self, f"FipeApiLambdaSecurityGroup-{stage}",
            vpc=vpc,
            description=f"Security group for the FIPE API Lambda functions - {stage}",
            allow_all_outbound=True
        )
        Tags.of(self.lambda_security_group).add("stage", stage)
        print(f"Grupo de segurança para as Lambdas criado: {self.lambda_security_group.security_group_id}")
        
        lambda_role = iam.Role(
            self, f"FipeApiLambdaRole-{stage}",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole"),
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSQSFullAccess")
            ]
        )
        
        db_lambda_role = iam.Role(
            self, f"FipeApiDBLambdaRole-{stage}",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaVPCAccessExecutionRole"),
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole"),
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSQSFullAccess")
            ]
        )
        
        # Permissões de acesso ao secret do RDS: só fazem sentido quando existe
        # um RDS local (db_secret_arn é None em sa-east-1, onde create_rds=False
        # e o ingestor apenas encaminha via SQS, sem acessar nenhum banco).
        if db_secret_arn:
            db_lambda_role.add_to_policy(iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[db_secret_arn]
            ))

            secret_name = db_secret_arn.split(':')[-1]

            db_secret = secretsmanager.Secret.from_secret_name_v2(
                self, f"ImportedDBSecret-{stage}",
                secret_name
            )
            db_secret.grant_read(db_lambda_role)
            print(f"Permissão para acessar o segredo do banco de dados concedida à role")
        else:
            print("Sem RDS local (create_rds=False) - pulando permissões de acesso a secret de banco de dados")

        Tags.of(lambda_role).add("stage", stage)
        Tags.of(db_lambda_role).add("stage", stage)
        print(f"Roles para as Lambdas criadas")
        
        manufacturer_dlq = sqs.Queue(self, 
                                     f"FipeManufacturerDLQ-{stage}", 
                                     visibility_timeout=Duration.seconds(600), 
                                     retention_period=Duration.days(14), 
                                     queue_name=f"fipe-manufacturer-dlq-{stage}")
        Tags.of(manufacturer_dlq).add("stage", stage)
        model_dlq = sqs.Queue(self, 
                              f"FipeModelDLQ-{stage}", 
                              visibility_timeout=Duration.seconds(600), 
                              retention_period=Duration.days(14), 
                              queue_name=f"fipe-model-dlq-{stage}")
        Tags.of(model_dlq).add("stage", stage)
        price_dlq = sqs.Queue(self, 
                              f"FipePriceDLQ-{stage}", 
                              visibility_timeout=Duration.seconds(600), 
                              retention_period=Duration.days(14), 
                              queue_name=f"fipe-price-dlq-{stage}")
        Tags.of(price_dlq).add("stage", stage)
        
        manufacturer_queue = sqs.Queue(self, 
                                       f"FipeManufacturerQueue-{stage}", 
                                       visibility_timeout=Duration.seconds(1000), 
                                       retention_period=Duration.days(4), 
                                       queue_name=f"fipe-manufacturer-queue-{stage}", 
                                       dead_letter_queue=sqs.DeadLetterQueue(
                                           max_receive_count=10, 
                                           queue=manufacturer_dlq))
        Tags.of(manufacturer_queue).add("stage", stage)
        print(f"Fila SQS para fabricantes criada: {manufacturer_queue.queue_name}")
        model_queue = sqs.Queue(self, 
                                f"FipeModelQueue-{stage}", 
                                visibility_timeout=Duration.seconds(1000), 
                                retention_period=Duration.days(4), 
                                queue_name=f"fipe-model-queue-{stage}", 
                                dead_letter_queue=sqs.DeadLetterQueue(
                                    max_receive_count=10, 
                                    queue=model_dlq)
                                )
        Tags.of(model_queue).add("stage", stage)
        print(f"Fila SQS para modelos criada: {model_queue.queue_name}")
        price_queue = sqs.Queue(self, 
                                f"FipePriceQueue-{stage}", 
                                visibility_timeout=Duration.seconds(1000), 
                                retention_period=Duration.days(4), 
                                queue_name=f"fipe-price-queue-{stage}", 
                                dead_letter_queue=sqs.DeadLetterQueue(
                                    max_receive_count=10, 
                                    queue=price_dlq))
        Tags.of(price_queue).add("stage", stage)
        print(f"Fila SQS para preços criada: {price_queue.queue_name}")
        print("Filas DLQ configuradas para todas as filas SQS")
        
        lambda_layer = lambda_.LayerVersion(self, 
                                            f"FipeApiLayer-{stage}", 
                                            code=lambda_.Code.from_asset("fipe_api_layer.zip"), 
                                            compatible_runtimes=[lambda_.Runtime.PYTHON_3_12], 
                                            description=f"Layer for FIPE API Lambda functions - {stage}")
        Tags.of(lambda_layer).add("stage", stage)
        print(f"Camada Lambda para FIPE API criada a partir do arquivo ZIP")
        
        common_env = {"STAGE": stage, "URL_FIPE": "http://veiculos.fipe.org.br/api/veiculos"}
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
                        "SQS_INPUT_URL": price_queue.queue_url}
        # Variáveis de RDS: só fazem sentido quando existe um RDS local
        # (None em sa-east-1, onde create_rds=False) - CDK não aceita None
        # como valor de variável de ambiente da Lambda.
        if db_cluster_endpoint:
            ingestor_env["RDS_HOST"] = db_cluster_endpoint
            ingestor_env["RDS_PORT"] = db_cluster_port
            ingestor_env["RDS_DATABASE"] = "fipedata"
            ingestor_env["RDS_USER"] = "postgres"
            ingestor_env["DB_SECRET_ARN"] = db_secret_arn
        # Encaminhamento cross-region (sa-east-1: sem RDS local, ingestor só encaminha via SQS)
        if sqs_forwarding_stg:
            ingestor_env["SQS_URL_STG"] = sqs_forwarding_stg
        if sqs_forwarding_prd:
            ingestor_env["SQS_URL_PRD"] = sqs_forwarding_prd
        
        manufacturer_lambda = lambda_.Function(
            self, 
            f"FipeManufacturerLoader-{stage}", 
            function_name=f"FipeManufacturerLoader-{stage}", 
            runtime=lambda_.Runtime.PYTHON_3_12, 
            code=lambda_.Code.from_asset(
                "code_lambdas/src/fipe_api", 
                exclude=["__pycache__", "*.pyc"]), 
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
        print(f"Lambda FipeManufacturerLoader criada: {manufacturer_lambda.function_name}")
        
        monthly_rule = events.Rule(self, f"FipeManufacturerMonthlyRule-{stage}", schedule=events.Schedule.cron(minute="0", hour="11", day="1", month="*", year="*"), description=f"Executa a lambda FipeManufacturerLoader no dia 1º de cada mês às 08:00 Brasília (11:00 UTC) - {stage}")
        monthly_rule.add_target(targets.LambdaFunction(manufacturer_lambda))
        manufacturer_lambda.add_permission(f"AllowEventBridgeInvoke-{stage}", principal=iam.ServicePrincipal("events.amazonaws.com"), source_arn=monthly_rule.rule_arn)
        print(f"Regra CloudWatch Events criada para execução mensal da Lambda FipeManufacturerLoader")
        
        print("Criando função FipeModelLoader...")
        model_lambda = lambda_.Function(
            self, f"FipeModelLoader-{stage}",
            function_name=f"FipeModelLoader-{stage}",
            runtime=lambda_.Runtime.PYTHON_3_12,
            code=lambda_.Code.from_asset("code_lambdas/src/fipe_api", exclude=["__pycache__", "*.pyc"]),
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
        print(f"Lambda FipeModelLoader criada com limite de concorrência: {model_lambda.function_name}")
        
        model_lambda.add_event_source(lambda_event_sources.SqsEventSource(manufacturer_queue, batch_size=10, max_batching_window=Duration.seconds(30), report_batch_item_failures=True))
        print(f"Fonte de evento SQS adicionada à Lambda {model_lambda.function_name}")
        
        print("Criando função FipePriceLoader...")
        price_lambda = lambda_.Function(
            self, f"FipePriceLoader-{stage}",
            function_name=f"FipePriceLoader-{stage}",
            runtime=lambda_.Runtime.PYTHON_3_12,
            code=lambda_.Code.from_asset("code_lambdas/src/fipe_api", exclude=["__pycache__", "*.pyc"]),
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
        print(f"Lambda FipePriceLoader criada com limite de concorrência: {price_lambda.function_name}")
        
        price_lambda.add_event_source(
            lambda_event_sources.SqsEventSource(
                model_queue, 
                batch_size=10,
                max_batching_window=Duration.seconds(30),
                report_batch_item_failures=True
            )
        )
        print(f"Fonte de evento SQS adicionada à Lambda {price_lambda.function_name}")
        
        print("Criando função FipeSomaIngestor...")
        # VPC: só faz sentido quando existe um RDS local para o ingestor acessar
        # (stage/production). Em sa-east-1 (create_rds=False, db_cluster_endpoint=None)
        # o ingestor só encaminha mensagens via SQS para outras regiões - colocá-lo
        # numa VPC sem NAT Gateway/VPC Endpoint bloquearia essas chamadas cross-region
        # com ConnectTimeoutError, já que Lambdas em VPC perdem o acesso à internet
        # padrão do ambiente de execução.
        ingestor_vpc_kwargs = {}
        if db_cluster_endpoint:
            ingestor_vpc_kwargs = {
                "vpc": vpc,
                "vpc_subnets": ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
                "allow_public_subnet": True,
                "security_groups": [self.lambda_security_group],
            }
        ingestor_lambda = lambda_.Function(
            self, f"FipeSomaIngestor-{stage}",
            function_name=f"FipeSomaIngestor-{stage}",
            runtime=lambda_.Runtime.PYTHON_3_12,
            code=lambda_.Code.from_asset("code_lambdas/src/fipe_api", exclude=["__pycache__", "*.pyc"]),
            handler="fipe_soma_ingestor.lambda_handler",
            timeout=Duration.minutes(5),
            memory_size=512,
            environment=ingestor_env,
            **ingestor_vpc_kwargs,
            role=db_lambda_role,
            layers=[lambda_layer],
            description="FIPE - 04) Função para ingerir dados da FIPE no banco de dados",
            reserved_concurrent_executions=20
        )
        Tags.of(ingestor_lambda).add("stage", stage)
        Tags.of(ingestor_lambda).add("function", "FipeSomaIngestor")
        print(f"Lambda FipeSomaIngestor criada com limite de concorrência: {ingestor_lambda.function_name}")
        
        ingestor_lambda.add_event_source(
            lambda_event_sources.SqsEventSource(
                price_queue, 
                batch_size=10,
                max_batching_window=Duration.seconds(30),
                report_batch_item_failures=True
            )
        )
        print(f"Fonte de evento SQS adicionada à Lambda {ingestor_lambda.function_name}")

        print("Criando função RedriveLambda...")
        redrive_lambda = lambda_.Function(
            self,
            f"RedriveDLQLambda-{stage}",
            function_name=f"RedriveDLQLambda-{stage}",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="fipe_redrive_flq.lambda_handler",
            code=lambda_.Code.from_asset("code_lambdas/src/fipe_api", exclude=["__pycache__", "*.pyc"]),
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

        # ====================================================================
        # CloudWatch Alarms + SNS Topic para Ingestor (Melhoria 3)
        # ====================================================================
        print("[FipeApiStack-Ingestor] Criando SNS Topic e Alarms...")

        ingestor_alert_topic = sns.Topic(
            self,
            f"FipeIngestorAlertTopic-{stage}",
            display_name=f"Alertas FipeIngestor-{stage}",
            topic_name=f"fipe-ingestor-alerts-{stage}"
        )
        Tags.of(ingestor_alert_topic).add("stage", stage)

        # Alarm para DLQ do Ingestor
        price_dlq_alarm = cw.Alarm(
            self,
            f"PriceDLQAlarm-{stage}",
            metric=price_dlq.metric_approximate_number_of_messages_visible(),
            threshold=1,
            evaluation_periods=1,
            datapoints_to_alarm=1,
            alarm_name=f"FipePriceDLQ-Alarm-{stage}",
            alarm_description=f"Alerta quando há mensagens na DLQ de preços - {stage}"
        )
        price_dlq_alarm.add_alarm_action(cwa.SnsAction(ingestor_alert_topic))
        Tags.of(price_dlq_alarm).add("stage", stage)

        # Alarm para Lambda errors do Ingestor
        ingestor_error_alarm = cw.Alarm(
            self,
            f"IngestorLambdaErrorAlarm-{stage}",
            metric=ingestor_lambda.metric_errors(),
            threshold=1,
            evaluation_periods=1,
            datapoints_to_alarm=1,
            alarm_name=f"FipeSomaIngestor-Errors-{stage}",
            alarm_description=f"Alerta quando FipeSomaIngestor falha - {stage}"
        )
        ingestor_error_alarm.add_alarm_action(cwa.SnsAction(ingestor_alert_topic))
        Tags.of(ingestor_error_alarm).add("stage", stage)

        # Criar/copiar Lambda Slack Notifier (reutiliza código de sa-east-1)
        slack_webhook_url = self.node.try_get_context("slack_webhook_url")

        slack_notifier = lambda_.Function(
            self,
            f"SlackNotifier-{stage}",
            function_name=f"FipeSlackNotifier-{stage}",
            runtime=lambda_.Runtime.PYTHON_3_12,
            code=lambda_.Code.from_asset(
                "code_lambdas/src/fipe_api",
                exclude=["__pycache__", "*.pyc"]
            ),
            handler="fipe_slack_notifier.lambda_handler",
            timeout=Duration.seconds(30),
            memory_size=128,
            environment={
                "SLACK_WEBHOOK_URL": slack_webhook_url or ""
            },
            role=lambda_role,
            description=f"FIPE - Envia alertas CloudWatch para Slack ({stage})"
        )
        Tags.of(slack_notifier).add("stage", stage)
        Tags.of(slack_notifier).add("function", "SlackNotifier")

        # Inscrever Lambda ao SNS Topic
        ingestor_alert_topic.add_subscription(
            sns_subscriptions.LambdaSubscription(slack_notifier)
        )

        print(f"[FipeApiStack-Ingestor] Alarms e SNS configurados para {stage}")

        # Criar Lambda FipeSomaNotifier apenas para o stage apropriado
        print("Criando função FipeSomaNotifier para webhooks...")
        webhook_notifier_env = {
            "WEBHOOK_PARAMETER_PATH": f"/fipe/webhooks",
            "WEBHOOK_TIMEOUT": "10",
            "STAGE": stage
        }

        webhook_notifiers = []  # Lista para armazenar Lambdas de webhook criadas

        # Lambda de webhook: apenas para o stage apropriado
        if stage == "stg":
            # STG (us-east-2): FipeSomaNotifier-stg
            webhook_notifier = lambda_.Function(
                self, "WebhookNotifier-stg",
                function_name="FipeSomaNotifier-stg",
                runtime=lambda_.Runtime.PYTHON_3_12,
                code=lambda_.Code.from_asset("code_lambdas/src/fipe_api", exclude=["__pycache__", "*.pyc"]),
                handler="fipe_soma_notifier.lambda_handler",
                timeout=Duration.minutes(5),
                memory_size=256,
                environment=webhook_notifier_env,
                role=lambda_role,
                layers=[lambda_layer],
                description="FIPE - Dispara webhooks para notificar app consumidoras quando dados STG estão prontos"
            )
            Tags.of(webhook_notifier).add("stage", "stg")
            Tags.of(webhook_notifier).add("function", "WebhookNotifier")

            webhook_notifier.add_to_role_policy(
                iam.PolicyStatement(
                    actions=["ssm:GetParameter"],
                    resources=[f"arn:aws:ssm:*:*:parameter/fipe/webhooks/stg"]
                )
            )
            webhook_notifier.add_to_role_policy(
                iam.PolicyStatement(
                    actions=["cloudwatch:PutMetricData"],
                    resources=["*"]
                )
            )

            webhook_notifiers.append(webhook_notifier)
            print(f"Lambda FipeSomaNotifier-stg criada para STG (us-east-2)")

        elif stage == "prd":
            # PRD (us-east-1): FipeSomaNotifier-prd
            webhook_notifier = lambda_.Function(
                self, "WebhookNotifier-prd",
                function_name="FipeSomaNotifier-prd",
                runtime=lambda_.Runtime.PYTHON_3_12,
                code=lambda_.Code.from_asset("code_lambdas/src/fipe_api", exclude=["__pycache__", "*.pyc"]),
                handler="fipe_soma_notifier.lambda_handler",
                timeout=Duration.minutes(5),
                memory_size=256,
                environment=webhook_notifier_env,
                role=lambda_role,
                layers=[lambda_layer],
                description="FIPE - Dispara webhooks para notificar app consumidoras quando dados PRD estão prontos"
            )
            Tags.of(webhook_notifier).add("stage", "prd")
            Tags.of(webhook_notifier).add("function", "WebhookNotifier")

            webhook_notifier.add_to_role_policy(
                iam.PolicyStatement(
                    actions=["ssm:GetParameter"],
                    resources=[f"arn:aws:ssm:*:*:parameter/fipe/webhooks/prd"]
                )
            )
            webhook_notifier.add_to_role_policy(
                iam.PolicyStatement(
                    actions=["cloudwatch:PutMetricData"],
                    resources=["*"]
                )
            )

            webhook_notifiers.append(webhook_notifier)
            print(f"Lambda FipeSomaNotifier-prd criada para PRD (us-east-1)")

        elif stage == "sa-east-1":
            # DEV (sa-east-1): FipeSomaNotifier-dev apenas para TESTE
            webhook_notifier = lambda_.Function(
                self, "WebhookNotifier-dev",
                function_name="FipeSomaNotifier-dev",
                runtime=lambda_.Runtime.PYTHON_3_12,
                code=lambda_.Code.from_asset("code_lambdas/src/fipe_api", exclude=["__pycache__", "*.pyc"]),
                handler="fipe_soma_notifier.lambda_handler",
                timeout=Duration.minutes(5),
                memory_size=256,
                environment=webhook_notifier_env,
                role=lambda_role,
                layers=[lambda_layer],
                description="FIPE - Webhook notifier para TESTE em DEV (sa-east-1)"
            )
            Tags.of(webhook_notifier).add("stage", "dev")
            Tags.of(webhook_notifier).add("function", "WebhookNotifier")
            Tags.of(webhook_notifier).add("purpose", "test-only")

            webhook_notifier.add_to_role_policy(
                iam.PolicyStatement(
                    actions=["ssm:GetParameter"],
                    resources=[f"arn:aws:ssm:*:*:parameter/fipe/webhooks/*"]
                )
            )
            webhook_notifier.add_to_role_policy(
                iam.PolicyStatement(
                    actions=["cloudwatch:PutMetricData"],
                    resources=["*"]
                )
            )

            webhook_notifiers.append(webhook_notifier)
            print(f"Lambda FipeSomaNotifier-dev criada para DEV (sa-east-1) - APENAS PARA TESTE")

        # Adicionar permissão ao FipeSomaIngestor para invocar as Lambdas FipeSomaNotifier
        if webhook_notifiers:
            ingestor_lambda.add_to_role_policy(
                iam.PolicyStatement(
                    actions=["lambda:InvokeFunction"],
                    resources=[wn.function_arn for wn in webhook_notifiers]
                )
            )
            print(f"Permissões IAM configuradas para invocar {len(webhook_notifiers)} Lambda(s) de webhook")

        # ... (restante do código de outputs sem alterações) ...
        CfnOutput(self, f"ManufacturerQueueUrl-{stage}", value=manufacturer_queue.queue_url, description=f"URL da fila SQS para fabricantes - {stage}")
        CfnOutput(self, f"ModelQueueUrl-{stage}", value=model_queue.queue_url, description=f"URL da fila SQS para modelos - {stage}")
        CfnOutput(self, f"PriceQueueUrl-{stage}", value=price_queue.queue_url, description=f"URL da fila SQS para preços - {stage}")
        CfnOutput(self, f"ManufacturerDLQUrl-{stage}", value=manufacturer_dlq.queue_url, description=f"URL da fila DLQ para fabricantes - {stage}")
        CfnOutput(self, f"ModelDLQUrl-{stage}", value=model_dlq.queue_url, description=f"URL da fila DLQ para modelos - {stage}")
        CfnOutput(self, f"PriceDLQUrl-{stage}", value=price_dlq.queue_url, description=f"URL da fila DLQ para preços - {stage}")
        CfnOutput(self, f"FipeManufacturerLambda-{stage}", value=manufacturer_lambda.function_name, description=f"Nome da função Lambda para carregamento de fabricantes - {stage}")
        CfnOutput(self, f"MonthlyEventRuleArn-{stage}", value=monthly_rule.rule_arn, description=f"ARN da regra CloudWatch Events para execução mensal - {stage}")
        CfnOutput(self, f"FipeIngestorAlertTopicArn-{stage}", value=ingestor_alert_topic.topic_arn, description=f"ARN do SNS Topic para alertas do Ingestor - {stage}")
        CfnOutput(self, f"FipeSlackNotifierLambda-{stage}", value=slack_notifier.function_name, description=f"Nome da função Lambda para notificações Slack - {stage}")

        # Output condicional para Lambda de webhook
        if webhook_notifiers:
            webhook_name = webhook_notifiers[0].function_name
            CfnOutput(self, f"FipeSomaNotifier-{stage}", value=webhook_name, description=f"Nome da função Lambda para webhooks - {stage}")

        print(f"Criação do FipeApiStack concluída com sucesso para o estágio: {stage}")