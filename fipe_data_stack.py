# fipe_data_stack.py

import os
from constructs import Construct
from aws_cdk import (
    CfnOutput,
    CustomResource,
    Duration,
    RemovalPolicy,
    Stack,
    Tags,
)
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_rds as rds
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk import custom_resources as cr

# Importar o stack filho FipeApiStack
from fipe_api_stack import FipeApiStack

class FipeDataStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        stage: str = "dev",
        create_rds: bool = True,
        rds_endpoints: dict = None,
        sqs_forwarding_urls: dict = None,
        slack_webhook_url: str = None,
        **kwargs
    ) -> None:
        """
        Stack com suporte a RDS local ou remoto.

        Args:
            create_rds: Se True, cria novo RDS Aurora. Se False, usa RDS remoto
            rds_endpoints: Dict com endpoints remotos {"stg": "...", "prd": "..."}
                          Obrigatório quando create_rds=False
            sqs_forwarding_urls: Dict com URLs SQS para encaminhamento cross-region
                                 {"stg": "https://sqs...", "prd": "https://sqs..."}
            slack_webhook_url: URL do webhook Slack para notificações
        """
        super().__init__(scope, construct_id, **kwargs)

        Tags.of(self).add("stage", stage)
        Tags.of(self).add("application", "FipeData")
        Tags.of(self).add("service", f"fipe-{stage}-database")

        print(f"[FipeDataStack] create_rds={create_rds}, stage={stage}")

        # VPC (necessária para Lambda, mesmo com RDS remoto)
        vpc_id = self.node.try_get_context("vpc_id")
        if not vpc_id:
            raise ValueError("O parametro 'vpc_id' deve ser fornecido no contexto do CDK.")

        vpc = ec2.Vpc.from_lookup(self, "ImportedVpc", vpc_id=vpc_id)

        # ====================================================================
        # CONDICIONAL: Criar RDS ou acessar remotamente
        # ====================================================================

        if create_rds:
            # MODO 1: Criar novo RDS Aurora
            print(f"[FipeDataStack] Criando novo RDS em {stage}")

            allowed_ip = self.node.try_get_context("allowed_ip")
            if not allowed_ip:
                raise ValueError("O parametro 'allowed_ip' deve ser fornecido no contexto do CDK.")

            # Security Group para o cluster do banco de dados
            db_security_group = ec2.SecurityGroup(
                self, f"FipeDataSecurityGroup-{stage}",
                vpc=vpc,
                description=f"Security group for FIPE PostgreSQL database - {stage}",
                allow_all_outbound=True
            )
            Tags.of(db_security_group).add("stage", stage)

            db_security_group.add_ingress_rule(
                ec2.Peer.ipv4(f"{allowed_ip}/32"),
                ec2.Port.tcp(5432),
                description="PostgreSQL access from a specific IP"
            )

            # Security Group para a Lambda de inicialização
            lambda_security_group = ec2.SecurityGroup(
                self, f"LambdaSecurityGroup-{stage}",
                vpc=vpc,
                description=f"Security group for the DB init Lambda function - {stage}",
                allow_all_outbound=True
            )
            Tags.of(lambda_security_group).add("stage", stage)

            db_security_group.add_ingress_rule(
                lambda_security_group,
                ec2.Port.tcp(5432),
                description="Allows connection from the DB setup Lambda"
            )

        else:
            # MODO 2: Acessar RDS remoto (Ingestor usa SQS forwarding)
            print(f"[FipeDataStack] Modo RDS remoto em {stage}")

            # Security Group apenas para Lambdas
            lambda_security_group = ec2.SecurityGroup(
                self, f"LambdaSecurityGroup-{stage}",
                vpc=vpc,
                description=f"Security group for Lambda functions - {stage}",
                allow_all_outbound=True
            )
            Tags.of(lambda_security_group).add("stage", stage)

            # Não criar db_security_group nem RDS
            db_security_group = None

        # ====================================================================
        # CRIAR RDS (apenas se create_rds=True)
        # ====================================================================

        if create_rds:
            # Secret Manager para as credenciais do banco de dados
            db_credentials = secretsmanager.Secret(
                self, f"FipeDataDBCredentials-{stage}",
                description=f"Credentials for FIPE PostgreSQL database - {stage}",
                generate_secret_string=secretsmanager.SecretStringGenerator(
                    secret_string_template='{"username": "postgres"}',
                    generate_string_key="password",
                    exclude_punctuation=True,
                    include_space=False
                )
            )
            Tags.of(db_credentials).add("stage", stage)

            db_cluster = rds.DatabaseCluster(
                self, f"FipeDataCluster-{stage}",
                engine=rds.DatabaseClusterEngine.aurora_postgres(
                    version=rds.AuroraPostgresEngineVersion.of("15.15", "15")
                ),
                credentials=rds.Credentials.from_secret(db_credentials),
                serverless_v2_min_capacity=0,
                serverless_v2_max_capacity=1,
                vpc=vpc,
                vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
                security_groups=[db_security_group],
                default_database_name="fipedata",
                cluster_identifier=f"FipeDataCluster-{stage}",
                removal_policy=RemovalPolicy.DESTROY,
                writer=rds.ClusterInstance.serverless_v2("WriterInstance")
            )
            Tags.of(db_cluster).add("stage", stage)
        else:
            # Placeholder quando RDS é remoto
            db_cluster = None
            db_credentials = None

        # ====================================================================
        # INICIALIZAÇÃO DO RDS (Lambda que executa SQL - apenas se create_rds=True)
        # ====================================================================

        if create_rds:
            script_dir = os.path.dirname(os.path.realpath(__file__))
            lambda_assets_dir = os.path.join(script_dir, "lambda", "assets")
            if not os.path.exists(lambda_assets_dir):
                os.makedirs(lambda_assets_dir)

            with open(os.path.join(script_dir, "create_fipe_db.sql"), "r") as src_file, \
                 open(os.path.join(lambda_assets_dir, "create_fipe_db.sql"), "w") as dest_file:
                dest_file.write(src_file.read())

            secretsmanager_endpoint = ec2.InterfaceVpcEndpoint(
                self, f"SecretsManagerEndpoint-{stage}",
                vpc=vpc,
                service=ec2.InterfaceVpcEndpointAwsService.SECRETS_MANAGER,
                private_dns_enabled=True,
                subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC)
            )
            Tags.of(secretsmanager_endpoint).add("stage", stage)
            secretsmanager_endpoint.connections.allow_from(
                lambda_security_group,
                ec2.Port.tcp(443),
                "Allow Lambda to access Secrets Manager via VPC endpoint"
            )

            lambda_role = iam.Role(
                self, f"SQLScriptExecutionRole-{stage}",
                assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
                managed_policies=[
                    iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaVPCAccessExecutionRole"),
                    iam.ManagedPolicy.from_aws_managed_policy_name("SecretsManagerReadWrite")
                ]
            )
            Tags.of(lambda_role).add("stage", stage)
            db_credentials.grant_read(lambda_role)

            psycopg2_layer = lambda_.LayerVersion(
                self, f"Psycopg2Layer-{stage}",
                code=lambda_.Code.from_asset("lambda-layer"),
                compatible_runtimes=[lambda_.Runtime.PYTHON_3_12],
                description=f"Layer with psycopg2 for PostgreSQL connectivity - {stage}"
            )
            Tags.of(psycopg2_layer).add("stage", stage)

            sql_execution_lambda = lambda_.Function(
                self, f"SQLExecutionLambda-{stage}",
                runtime=lambda_.Runtime.PYTHON_3_12,
                handler="index.handler",
                code=lambda_.Code.from_asset("lambda"),
                timeout=Duration.minutes(15),
                memory_size=512,
                vpc=vpc,
                vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
                allow_public_subnet=True,
                security_groups=[lambda_security_group],
                environment={
                    "DB_ENDPOINT": db_cluster.cluster_endpoint.hostname,
                    "DB_PORT": str(db_cluster.cluster_endpoint.port),
                    "SECRET_ARN": db_credentials.secret_arn,
                    "STAGE": stage
                },
                role=lambda_role,
                layers=[psycopg2_layer]
            )
            Tags.of(sql_execution_lambda).add("stage", stage)
            sql_execution_lambda.node.add_dependency(db_cluster)

            provider = cr.Provider(
                self, f"SQLExecutionProvider-{stage}",
                on_event_handler=sql_execution_lambda
            )
            Tags.of(provider).add("stage", stage)

            CustomResource(
                self, f"SQLExecutionCustomResource-{stage}",
                service_token=provider.service_token
            )

            # Outputs apenas quando RDS é criado
            CfnOutput(
                self, f"DBEndpoint-{stage}",
                value=db_cluster.cluster_endpoint.hostname,
                description=f"Writer endpoint of the Aurora cluster - {stage}"
            )
            CfnOutput(
                self, f"DBReaderEndpoint-{stage}",
                value=db_cluster.cluster_read_endpoint.hostname,
                description=f"Reader endpoint of the Aurora cluster - {stage}"
            )
            CfnOutput(
                self, f"DBPort-{stage}",
                value=str(db_cluster.cluster_endpoint.port),
                description=f"Port of the Aurora PostgreSQL cluster - {stage}"
            )
            CfnOutput(
                self, f"DBSecretArn-{stage}",
                value=db_credentials.secret_arn,
                description=f"ARN of the secret containing database credentials - {stage}"
            )

        # ====================================================================
        # FIPEAPISTACK: Lambdas + SQS
        # ====================================================================

        # Determinar endpoints do RDS (novo ou remoto)
        if create_rds:
            db_endpoint = db_cluster.cluster_endpoint.hostname
            db_port = str(db_cluster.cluster_endpoint.port)
            db_secret_arn = db_credentials.secret_arn
            print(f"[FipeDataStack] Usando RDS criado em {stage}")
        else:
            db_endpoint = None
            db_port = "5432"
            db_secret_arn = None
            print("[FipeDataStack] RDS remoto (ingestor usa SQS forwarding)")

        # Extrair URLs SQS para forwarding cross-region
        sqs_stg = sqs_forwarding_urls.get("stg") if sqs_forwarding_urls else None
        sqs_prd = sqs_forwarding_urls.get("prd") if sqs_forwarding_urls else None

        # Criar FipeApiStack (sempre cria, com ou sem RDS local)
        # slack_webhook_url não é passado aqui: FipeApiStack já busca via
        # self.node.try_get_context("slack_webhook_url") internamente.
        fipe_api_stack = FipeApiStack(
            self,
            "FipeApiStack",  # Sem sufixo - stack única
            vpc=vpc,
            db_cluster_endpoint=db_endpoint,
            db_cluster_port=db_port,
            db_secret_arn=db_secret_arn,
            stage=stage,
            sqs_forwarding_stg=sqs_stg,
            sqs_forwarding_prd=sqs_prd,
        )

        # Adicionar regra de segurança apenas se RDS foi criado localmente
        if create_rds and db_security_group:
            db_security_group.add_ingress_rule(
                fipe_api_stack.lambda_security_group,
                ec2.Port.tcp(5432),
                "Allow FipeApi Lambdas to connect to the RDS Cluster"
            )

        print(f"[FipeDataStack] FipeApiStack criada com sucesso em {stage}")