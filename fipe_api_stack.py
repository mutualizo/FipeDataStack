# fipe_api_stack.py

import os
from constructs import Construct
from aws_cdk import (
    NestedStack,
    Duration,
    CfnOutput,
    Tags,
)
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_sqs as sqs
from aws_cdk import aws_lambda_event_sources as lambda_event_sources
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_cloudwatch as cw
from aws_cdk import aws_cloudwatch_actions as cwa
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as sns_subscriptions

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
        sqs_forwarding_stg: str = None,
        sqs_forwarding_prd: str = None,
        **kwargs
    ) -> None:
        """
        Stack de Lambdas + SQS única em sa-east-1

        Args:
            sqs_forwarding_stg: URL da fila SQS STG para encaminhamento cross-region
            sqs_forwarding_prd: URL da fila SQS PRD para encaminhamento cross-region
        """
        super().__init__(scope, construct_id, **kwargs)

        script_dir = os.path.dirname(os.path.realpath(__file__))

        Tags.of(self).add("stage", stage)
        Tags.of(self).add("application", "FipeAPI")

        print(f"[FipeApiStack] Criando Lambdas + SQS em {stage}")
        if sqs_forwarding_stg and sqs_forwarding_prd:
            print(f"[FipeApiStack] SQS Forwarding: STG={sqs_forwarding_stg}, PRD={sqs_forwarding_prd}")
        
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


        Tags.of(lambda_role).add("stage", stage)
        print("[FipeApiStack] Role criada")

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
            encryption=sqs.QueueEncryption.KMS_MANAGED
        )
        Tags.of(manufacturer_dlq).add("stage", stage)

        model_dlq = sqs.Queue(
            self,
            "FipeModelDLQ",  # Sem sufixo
            visibility_timeout=Duration.seconds(600),
            retention_period=Duration.days(14),
            queue_name="fipe-model-dlq",
            encryption=sqs.QueueEncryption.KMS_MANAGED
        )
        Tags.of(model_dlq).add("stage", stage)

        price_dlq = sqs.Queue(
            self,
            "FipePriceDLQ",  # Sem sufixo
            visibility_timeout=Duration.seconds(600),
            retention_period=Duration.days(14),
            queue_name="fipe-price-dlq",
            encryption=sqs.QueueEncryption.KMS_MANAGED
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
            encryption=sqs.QueueEncryption.KMS_MANAGED
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
            encryption=sqs.QueueEncryption.KMS_MANAGED
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
            encryption=sqs.QueueEncryption.KMS_MANAGED
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

        # Permissões SQS cross-region para encaminhamento (STG e PRD)
        if sqs_forwarding_stg and sqs_forwarding_prd:
            def _url_to_arn(url):
                # https://sqs.REGION.amazonaws.com/ACCOUNT/NAME → arn:aws:sqs:REGION:ACCOUNT:NAME
                parts = url.replace("https://sqs.", "").split("/")
                region = parts[0].split(".")[0]
                account = parts[1]
                name = parts[2]
                return f"arn:aws:sqs:{region}:{account}:{name}"

            lambda_role.add_to_policy(iam.PolicyStatement(
                actions=["sqs:SendMessage"],
                resources=[
                    _url_to_arn(sqs_forwarding_stg),
                    _url_to_arn(sqs_forwarding_prd)
                ]
            ))
            print("[FipeApiStack] Permissão SQS cross-region adicionada para STG e PRD")

        # Lambda Layer (sem sufixo)
        lambda_layer = lambda_.LayerVersion(
            self,
            "FipeApiLayer",  # Sem sufixo
            code=lambda_.Code.from_asset(os.path.join(script_dir, "fipe_api_layer.zip")),
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_12],
            description="Layer for FIPE API Lambda functions"
        )
        Tags.of(lambda_layer).add("stage", stage)
        print("[FipeApiStack] Lambda Layer criada")
        
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
                        "SQS_URL_STG": sqs_forwarding_stg or "",
                        "SQS_URL_PRD": sqs_forwarding_prd or ""}
        
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
        print("[FipeApiStack] Lambda FipeManufacturerLoader criada")

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
        print("[FipeApiStack] EventBridge Rule criada para execução mensal")
        
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
        print("[FipeApiStack] Lambda FipeModelLoader criada")

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
        print("[FipeApiStack] Lambda FipePriceLoader criada")

        # 4. FipeSomaIngestor (encaminhamento cross-region via SQS)
        ingestor_lambda = lambda_.Function(
            self,
            "FipeSomaIngestor",  # Sem sufixo
            function_name="FipeSomaIngestor",  # Sem sufixo
            runtime=lambda_.Runtime.PYTHON_3_12,
            code=lambda_.Code.from_asset(os.path.join(script_dir, "code_lambdas/src/fipe_api"), exclude=["__pycache__", "*.pyc"]),
            handler="fipe_soma_ingestor.lambda_handler",
            timeout=Duration.minutes(2),
            memory_size=256,
            environment=ingestor_env,
            role=lambda_role,
            layers=[lambda_layer],
            description="FIPE - 04) Encaminha mensagens para filas SQS STG e PRD",
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
        print("[FipeApiStack] Lambda FipeSomaIngestor criada")

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

        # ====================================================================
        # CloudWatch Alarms + SNS Topic (Observabilidade - Dia 2)
        # ====================================================================
        print("[FipeApiStack] Criando SNS Topic para alertas...")
        alert_topic = sns.Topic(
            self,
            "FipeAlertTopic",
            display_name="Alertas FipeDataStack",
            topic_name="fipe-alerts"
        )
        Tags.of(alert_topic).add("stage", stage)
        print(f"[FipeApiStack] SNS Topic criado: {alert_topic.topic_arn}")

        # Alarms para DLQs - disparar quando houver mensagens
        print("[FipeApiStack] Criando Alarms para DLQs...")

        manufacturer_dlq_alarm = cw.Alarm(
            self,
            "ManufacturerDLQAlarm",
            metric=manufacturer_dlq.metric_approximate_number_of_messages_visible(),
            threshold=1,
            evaluation_periods=1,
            datapoints_to_alarm=1,
            alarm_name="FipeManufacturerDLQ-Alarm",
            alarm_description="Alerta quando há mensagens na DLQ de fabricantes"
        )
        manufacturer_dlq_alarm.add_alarm_action(cwa.SnsAction(alert_topic))
        Tags.of(manufacturer_dlq_alarm).add("stage", stage)

        model_dlq_alarm = cw.Alarm(
            self,
            "ModelDLQAlarm",
            metric=model_dlq.metric_approximate_number_of_messages_visible(),
            threshold=1,
            evaluation_periods=1,
            datapoints_to_alarm=1,
            alarm_name="FipeModelDLQ-Alarm",
            alarm_description="Alerta quando há mensagens na DLQ de modelos"
        )
        model_dlq_alarm.add_alarm_action(cwa.SnsAction(alert_topic))
        Tags.of(model_dlq_alarm).add("stage", stage)

        price_dlq_alarm = cw.Alarm(
            self,
            "PriceDLQAlarm",
            metric=price_dlq.metric_approximate_number_of_messages_visible(),
            threshold=1,
            evaluation_periods=1,
            datapoints_to_alarm=1,
            alarm_name="FipePriceDLQ-Alarm",
            alarm_description="Alerta quando há mensagens na DLQ de preços"
        )
        price_dlq_alarm.add_alarm_action(cwa.SnsAction(alert_topic))
        Tags.of(price_dlq_alarm).add("stage", stage)

        print("[FipeApiStack] Alarms para DLQs criados e conectados ao SNS")

        # Alarms para Lambda Errors
        print("[FipeApiStack] Criando Alarms para Lambda Errors...")

        manufacturer_error_alarm = cw.Alarm(
            self,
            "ManufacturerLambdaErrorAlarm",
            metric=manufacturer_lambda.metric_errors(),
            threshold=1,
            evaluation_periods=1,
            datapoints_to_alarm=1,
            alarm_name="FipeManufacturerLoader-Errors",
            alarm_description="Alerta quando FipeManufacturerLoader falha"
        )
        manufacturer_error_alarm.add_alarm_action(cwa.SnsAction(alert_topic))
        Tags.of(manufacturer_error_alarm).add("stage", stage)

        model_error_alarm = cw.Alarm(
            self,
            "ModelLambdaErrorAlarm",
            metric=model_lambda.metric_errors(),
            threshold=1,
            evaluation_periods=1,
            datapoints_to_alarm=1,
            alarm_name="FipeModelLoader-Errors",
            alarm_description="Alerta quando FipeModelLoader falha"
        )
        model_error_alarm.add_alarm_action(cwa.SnsAction(alert_topic))
        Tags.of(model_error_alarm).add("stage", stage)

        price_error_alarm = cw.Alarm(
            self,
            "PriceLambdaErrorAlarm",
            metric=price_lambda.metric_errors(),
            threshold=1,
            evaluation_periods=1,
            datapoints_to_alarm=1,
            alarm_name="FipePriceLoader-Errors",
            alarm_description="Alerta quando FipePriceLoader falha"
        )
        price_error_alarm.add_alarm_action(cwa.SnsAction(alert_topic))
        Tags.of(price_error_alarm).add("stage", stage)

        ingestor_error_alarm = cw.Alarm(
            self,
            "IngestorLambdaErrorAlarm",
            metric=ingestor_lambda.metric_errors(),
            threshold=1,
            evaluation_periods=1,
            datapoints_to_alarm=1,
            alarm_name="FipeSomaIngestor-Errors",
            alarm_description="Alerta quando FipeSomaIngestor falha"
        )
        ingestor_error_alarm.add_alarm_action(cwa.SnsAction(alert_topic))
        Tags.of(ingestor_error_alarm).add("stage", stage)

        print("[FipeApiStack] Alarms para Lambda Errors criados e conectados ao SNS")

        # ====================================================================
        # Slack Notifier Lambda (Dia 3)
        # ====================================================================
        print("[FipeApiStack] Criando Lambda Slack Notifier...")

        slack_webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "")

        slack_notifier = lambda_.Function(
            self,
            "SlackNotifier",
            function_name="FipeSlackNotifier",
            runtime=lambda_.Runtime.PYTHON_3_12,
            code=lambda_.Code.from_asset(
                os.path.join(script_dir, "code_lambdas/src/fipe_api"),
                exclude=["__pycache__", "*.pyc"]
            ),
            handler="fipe_slack_notifier.lambda_handler",
            timeout=Duration.seconds(30),
            memory_size=128,
            environment={
                "SLACK_WEBHOOK_URL": slack_webhook_url
            },
            role=lambda_role,
            description="FIPE - Envia alertas CloudWatch para Slack"
        )
        Tags.of(slack_notifier).add("stage", stage)
        Tags.of(slack_notifier).add("function", "SlackNotifier")

        # Inscrever Lambda ao SNS Topic
        alert_topic.add_subscription(
            sns_subscriptions.LambdaSubscription(slack_notifier)
        )

        print("[FipeApiStack] Lambda Slack Notifier criada e inscrita no SNS Topic")

        # CloudFormation Outputs (sem sufixo de stage)
        CfnOutput(self, "ManufacturerQueueUrl", value=manufacturer_queue.queue_url, description="URL da fila SQS para fabricantes")
        CfnOutput(self, "ModelQueueUrl", value=model_queue.queue_url, description="URL da fila SQS para modelos")
        CfnOutput(self, "PriceQueueUrl", value=price_queue.queue_url, description="URL da fila SQS para preços")
        CfnOutput(self, "ManufacturerDLQUrl", value=manufacturer_dlq.queue_url, description="URL da fila DLQ para fabricantes")
        CfnOutput(self, "ModelDLQUrl", value=model_dlq.queue_url, description="URL da fila DLQ para modelos")
        CfnOutput(self, "PriceDLQUrl", value=price_dlq.queue_url, description="URL da fila DLQ para preços")
        CfnOutput(self, "FipeManufacturerLambda", value=manufacturer_lambda.function_name, description="Nome da função Lambda para carregamento de fabricantes")
        CfnOutput(self, "MonthlyEventRuleArn", value=monthly_rule.rule_arn, description="ARN da regra CloudWatch Events para execução mensal")
        CfnOutput(self, "FipeAlertTopicArn", value=alert_topic.topic_arn, description="ARN do SNS Topic para alertas")
        CfnOutput(self, "FipeSlackNotifierLambda", value=slack_notifier.function_name, description="Nome da função Lambda para notificações Slack")

        print("[FipeApiStack] Criação concluída com sucesso")