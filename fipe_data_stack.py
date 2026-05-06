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
    def __init__(self, scope: Construct, construct_id: str, stage: str = "dev", **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        
        Tags.of(self).add("stage", stage)
        Tags.of(self).add("application", "FipeData")
        Tags.of(self).add("service", f"fipe-{stage}-database")

        vpc_id = self.node.try_get_context("vpc_id")
        if not vpc_id:
            raise ValueError("O parametro 'vpc_id' deve ser fornecido no contexto do CDK.")
        
        vpc = ec2.Vpc.from_lookup(self, "ImportedVpc", vpc_id=vpc_id)
        
        allowed_ip = self.node.try_get_context("allowed_ip")
        if not allowed_ip:
            raise ValueError("O parametro 'allowed_ip' deve ser fornecido no contexto do CDK.")

        # Security Group para o cluster do banco de dados
        db_security_group = ec2.SecurityGroup(
            self, f"FipeDataSecurityGroup-{stage}",
            vpc=vpc,
            description=f"Security group for FIPE PostgreSQL database - {stage}", # Descricao em ingles (ASCII)
            allow_all_outbound=True
        )
        Tags.of(db_security_group).add("stage", stage)
        
        db_security_group.add_ingress_rule(
            ec2.Peer.ipv4(f"{allowed_ip}/32"),
            ec2.Port.tcp(5432),
            description="PostgreSQL access from a specific IP" # Descricao em ingles (ASCII)
        )

        # Security Group para a Lambda de inicialização
        lambda_security_group = ec2.SecurityGroup(
            self, f"LambdaSecurityGroup-{stage}",
            vpc=vpc,
            description=f"Security group for the DB init Lambda function - {stage}", # Descricao em ingles (ASCII)
            allow_all_outbound=True
        )
        Tags.of(lambda_security_group).add("stage", stage)
        
        db_security_group.add_ingress_rule(
            lambda_security_group,
            ec2.Port.tcp(5432),
            description="Allows connection from the DB setup Lambda" # Descricao em ingles (ASCII)
        )

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
                version=rds.AuroraPostgresEngineVersion.of("15.5", "15")
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
            "Allow Lambda to access Secrets Manager via VPC endpoint" # Descricao em ingles (ASCII)
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
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_10],
            description=f"Layer with psycopg2 for PostgreSQL connectivity - {stage}"
        )
        Tags.of(psycopg2_layer).add("stage", stage)

        sql_execution_lambda = lambda_.Function(
            self, f"SQLExecutionLambda-{stage}",
            runtime=lambda_.Runtime.PYTHON_3_10,
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

        fipe_api_stack = FipeApiStack(
            self, 
            f"FipeApiStack-{stage}",
            vpc=vpc,
            db_cluster_endpoint=db_cluster.cluster_endpoint.hostname,
            db_cluster_port=str(db_cluster.cluster_endpoint.port),
            db_secret_arn=db_credentials.secret_arn,
            stage=stage
        )
        
        db_security_group.add_ingress_rule(
            fipe_api_stack.lambda_security_group,
            ec2.Port.tcp(5432),
            "Allow FipeApi Lambdas to connect to the RDS Cluster" # Descricao em ingles (ASCII)
        )
        
        print(f"Child stack FipeApiStack created successfully for stage: {stage}")