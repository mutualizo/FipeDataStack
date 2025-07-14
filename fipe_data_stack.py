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
        
        # Adicionar tag de estágio (stage) ao stack
        Tags.of(self).add("Stage", stage)
        Tags.of(self).add("Application", "FipeData")

        # Obter a VPC do contexto
        vpc_id = self.node.try_get_context("vpc_id")
        if not vpc_id:
            raise ValueError("vpc_id deve ser fornecido no contexto")
        
        vpc = ec2.Vpc.from_lookup(self, "ImportedVpc", vpc_id=vpc_id)
        
        # Obter o IP permitido do contexto
        allowed_ip = self.node.try_get_context("allowed_ip")
        if not allowed_ip:
            raise ValueError("allowed_ip deve ser fornecido no contexto")
        
        # Criar um grupo de segurança para o banco de dados
        db_security_group = ec2.SecurityGroup(
            self, f"FipeDataSecurityGroup-{stage}",
            vpc=vpc,
            description=f"Security group for the FIPE PostgreSQL database - {stage}",
            allow_all_outbound=True
        )
        Tags.of(db_security_group).add("Stage", stage)
        
        # Adicionar regra de entrada para permitir acesso PostgreSQL do IP específico
        db_security_group.add_ingress_rule(
            ec2.Peer.ipv4(f"{allowed_ip}/32"),
            ec2.Port.tcp(5432),
            description="PostgreSQL access from specific IP"
        )
        
        # Criar grupo de segurança para a função Lambda de inicialização
        lambda_security_group = ec2.SecurityGroup(
            self, f"LambdaSecurityGroup-{stage}",
            vpc=vpc,
            description=f"Security group for Lambda function - {stage}",
            allow_all_outbound=True
        )
        Tags.of(lambda_security_group).add("Stage", stage)
        
        # Permitir que a função Lambda de inicialização se conecte ao banco de dados
        db_security_group.add_ingress_rule(
            lambda_security_group,
            ec2.Port.tcp(5432),
            "Allow initial setup Lambda to connect to database"
        )
        
        # Criar um segredo para as credenciais do banco de dados
        db_credentials = secretsmanager.Secret(
            self, f"FipeDataDBCredentials-{stage}",
            description=f"FIPE PostgreSQL database credentials - {stage}",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template='{"username": "postgres"}',
                generate_string_key="password",
                exclude_punctuation=True,
                include_space=False
            )
        )
        Tags.of(db_credentials).add("Stage", stage)
        
        # Criar o cluster Aurora PostgreSQL
        db_cluster = rds.DatabaseCluster(
            self, f"FipeDataCluster-{stage}",
            engine=rds.DatabaseClusterEngine.aurora_postgres(
                version=rds.AuroraPostgresEngineVersion.VER_15_3
            ),
            credentials=rds.Credentials.from_secret(db_credentials),
            instances=2,
            instance_props=rds.InstanceProps(
                vpc=vpc,
                vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
                instance_type=ec2.InstanceType.of(
                    ec2.InstanceClass.BURSTABLE3,
                    ec2.InstanceSize.MEDIUM  # Instância t3.medium
                ),
                security_groups=[db_security_group],
                publicly_accessible=True
            ),
            default_database_name="fipedata",
            cluster_identifier=f"FipeDataCluster-{stage}",
            removal_policy=RemovalPolicy.DESTROY
        )
        Tags.of(db_cluster).add("Stage", stage)

        # #################################################################
        # INÍCIO DAS MODIFICAÇÕES PARA ADICIONAR O RDS PROXY
        # #################################################################

        # Criar um grupo de segurança para o RDS Proxy
        proxy_security_group = ec2.SecurityGroup(
            self, f"FipeProxySecurityGroup-{stage}",
            vpc=vpc,
            description=f"Security group for the FIPE RDS Proxy - {stage}"
        )
        Tags.of(proxy_security_group).add("Stage", stage)

        # Permitir que o proxy se conecte ao cluster do banco de dados
        db_cluster.connections.allow_from(proxy_security_group, ec2.Port.tcp(5432))

        # Criar o RDS Proxy
        db_proxy = rds.DatabaseProxy(
            self, f"FipeDataProxy-{stage}",
            proxy_target=rds.ProxyTarget.from_cluster(db_cluster),
            secrets=[db_credentials],
            vpc=vpc,
            security_groups=[proxy_security_group],
            iam_auth=False,
            # Uma role é criada automaticamente pelo CDK para o proxy acessar o secret
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            db_proxy_name=f"fipe-data-proxy-{stage}",
            idle_client_timeout=Duration.minutes(30)
        )

        # Adicionar um novo output para o endpoint do proxy
        CfnOutput(
            self, f"DBProxyEndpoint-{stage}",
            value=db_proxy.endpoint,
            description=f"Endpoint do RDS Proxy - {stage}"
        )

        # #################################################################
        # FIM DAS MODIFICAÇÕES
        # #################################################################
            
        # Ler o script SQL
        script_dir = os.path.dirname(os.path.realpath(__file__))
        with open(os.path.join(script_dir, "create_fipe_db.sql"), "r") as file:
            sql_script = file.read()
            
        # ... (código para a Lambda de inicialização permanece o mesmo)
        lambda_assets_dir = os.path.join(os.path.dirname(os.path.realpath(__file__)), "lambda", "assets")
        if not os.path.exists(lambda_assets_dir):
            os.makedirs(lambda_assets_dir)
        with open(os.path.join(lambda_assets_dir, "create_fipe_db.sql"), "w") as file:
            file.write(sql_script)
        secretsmanager_endpoint = ec2.InterfaceVpcEndpoint(
            self, f"SecretsManagerEndpoint-{stage}",
            vpc=vpc,
            service=ec2.InterfaceVpcEndpointAwsService.SECRETS_MANAGER,
            private_dns_enabled=True,
            subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC)
        )
        Tags.of(secretsmanager_endpoint).add("Stage", stage)
        secretsmanager_endpoint.connections.allow_from(
            lambda_security_group,
            ec2.Port.tcp(443),
            "Allow Lambda to access Secrets Manager through VPC endpoint"
        )
        lambda_role = iam.Role(
            self, f"SQLScriptExecutionRole-{stage}",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaVPCAccessExecutionRole"),
                iam.ManagedPolicy.from_aws_managed_policy_name("SecretsManagerReadWrite")
            ]
        )
        Tags.of(lambda_role).add("Stage", stage)
        db_credentials.grant_read(lambda_role)
        psycopg2_layer = lambda_.LayerVersion(
            self, f"Psycopg2Layer-{stage}",
            code=lambda_.Code.from_asset("lambda-layer"),
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_10],
            description=f"Camada contendo psycopg2 para conectividade PostgreSQL - {stage}"
        )
        Tags.of(psycopg2_layer).add("Stage", stage)
        lambda_env = {
            "DB_ENDPOINT": db_cluster.cluster_endpoint.hostname,
            "DB_PORT": str(db_cluster.cluster_endpoint.port),
            "SECRET_ARN": db_credentials.secret_arn,
            "STAGE": stage
        }
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
            environment=lambda_env,
            role=lambda_role,
            layers=[psycopg2_layer]
        )
        Tags.of(sql_execution_lambda).add("Stage", stage)
        sql_execution_lambda.node.add_dependency(db_cluster)
        provider = cr.Provider(
            self, f"SQLExecutionProvider-{stage}",
            on_event_handler=sql_execution_lambda
        )
        Tags.of(provider).add("Stage", stage)
        sql_execution_custom_resource = CustomResource(
            self, f"SQLExecutionCustomResource-{stage}",
            service_token=provider.service_token
        )
        
        # Outputs para endpoints de escrita e de leitura
        CfnOutput(
            self, f"DBEndpoint-{stage}",
            value=db_cluster.cluster_endpoint.hostname,
            description=f"Writer endpoint do cluster Aurora - {stage}"
        )
        CfnOutput(
            self, f"DBReaderEndpoint-{stage}",
            value=db_cluster.cluster_read_endpoint.hostname,
            description=f"Reader endpoint do cluster Aurora - {stage}"
        )
        CfnOutput(
            self, f"DBPort-{stage}",
            value=str(db_cluster.cluster_endpoint.port),
            description=f"A porta do cluster PostgreSQL Aurora - {stage}"
        )
        CfnOutput(
            self, f"DBSecretArn-{stage}",
            value=db_credentials.secret_arn,
            description=f"O ARN do segredo contendo as credenciais do banco de dados - {stage}"
        )
        CfnOutput(
            self, "Stage",
            value=stage,
            description="Estágio da implantação (dev, stg, prd)"
        )
        
        # Criar o stack filho FipeApiStack, passando o endpoint do PROXY
        print(f"Criando stack filho FipeApiStack para o estágio: {stage}")
        fipe_api_stack = FipeApiStack(
            self, 
            f"FipeApiStack-{stage}",
            vpc=vpc,
            db_cluster_endpoint=db_proxy.endpoint,  # << MODIFICADO: Usa o endpoint do proxy
            db_cluster_port=str(db_proxy.port),   # << MODIFICADO: Usa a porta do proxy
            db_secret_arn=db_credentials.secret_arn,
            stage=stage
        )
        
        # Permitir que as funções Lambda do FipeApiStack se conectem ao RDS Proxy
        proxy_security_group.add_ingress_rule(
            fipe_api_stack.lambda_security_group, # << MODIFICADO: obtém o SG do stack filho
            ec2.Port.tcp(5432),
            "Allow FipeApi Lambda functions to connect to RDS Proxy"
        )
        
        print(f"Stack filho FipeApiStack criado com sucesso para o estágio: {stage}")