## Notas sobre o Script SQL

Este projeto utiliza uma abordagem otimizada para transferir o script SQL para a função Lambda:

1. **Script SQL empacotado com a função Lambda**:
   - O script SQL é incluído diretamente no pacote da função Lambda
   - Armazenado no diretório `lambda/assets/create_fipe_db.sql`
   - Eliminando a necessidade de acesso ao S3 ou uso de variáveis de ambiente grandes

2. **Endpoint Secrets Manager**:
   - Um endpoint de interface para Secrets Manager é criado automaticamente
   - Necessário para permitir que a função Lambda acesse segredos na VPC

Esta solução resolve o problema de timeout ao acessar o S3 e também evita 
limitações de tamanho das variáveis de ambiente.## Notas sobre VPC Endpoints

Este projeto utiliza uma abordagem otimizada para conexão com serviços AWS em VPCs:

1. **Endpoint Secrets Manager**:
   - Um endpoint de interface para Secrets Manager é criado automaticamente
   - Necessário para permitir que a função Lambda acesse segredos na VPC

2. **Endpoint S3**:
   - O projeto **não** cria um endpoint S3 por padrão, assumindo que já existe um na VPC
   - O script SQL é passado diretamente para a função Lambda via variáveis de ambiente
   - Não há necessidade de acesso ao S3 durante a execução

Essa abordagem resolve problemas comuns de conectividade em ambientes VPC, especialmente 
quando os endpoints já estão configurados previamente na VPC ou quando há firewalls
ou configurações de rede que podem causar problemas de conectividade.## Pré-requisitos

- [AWS CLI](https://aws.amazon.com/cli/) configurado com credenciais adequadas
- [Node.js](https://nodejs.org/) (≥ 12.x)
- [Python](https://www.python.org/) (≥ 3.10)
- [AWS CDK](https://aws.amazon.com/cdk/) instalado globalmente: `npm install -g aws-cdk`
- [Docker](https://www.docker.com/) (para construir a camada Lambda com psycopg2)

## Configuração de Credenciais AWS

Este projeto utiliza exclusivamente o sistema de perfis do AWS CLI para gerenciar credenciais:

1. **Configurando um perfil AWS**:
   ```bash
   # Configurar um perfil AWS com todas as informações necessárias
   aws configure --profile meu-perfil
   
   # Ou editar manualmente o arquivo ~/.aws/credentials:
   [meu-perfil]
   aws_access_key_id = AKIAXXXXXXXXXXXXXXXX
   aws_secret_access_key = xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   region = us-east-1
   ```

2. **Definindo o perfil a ser usado para o deploy**:
   ```bash
   # Especificar o perfil a ser usado
   export AWS_PROFILE=meu-perfil
   
   # Opcionalmente, sobrescrever a região do perfil
   export AWS_REGION=us-east-2
   ```

O script exige que `AWS_PROFILE` seja definido e que o perfil contenha:
- Credenciais AWS válidas (access key e secret key)
- Uma região AWS válida (ou a variável `AWS_REGION` definida)

A conta AWS será obtida automaticamente a partir do perfil utilizando a operação STS GetCallerIdentity.# FipeData - Banco de Dados PostgreSQL Aurora na AWS

Este projeto utiliza AWS CDK em Python para provisionar um banco de dados PostgreSQL Aurora na AWS para armazenar dados da Tabela FIPE. A infraestrutura inclui uma instância PostgreSQL Aurora elegível para o tier gratuito, com acesso restrito a um IP específico.

## Sobre o Projeto

A stack CDK cria os seguintes recursos:
- Banco de dados PostgreSQL Aurora com instância T3.MEDIUM
- Grupo de segurança com acesso restrito ao IP especificado
- Secret no AWS Secrets Manager para armazenar credenciais do banco
- Função Lambda para executar o script SQL inicial
- Camada Lambda com a biblioteca psycopg2 para conectividade PostgreSQL

## Configuração de Credenciais AWS

Você pode configurar as credenciais da AWS de várias maneiras:

1. **Usando o AWS CLI** (recomendado para desenvolvimento local):
   ```bash
   aws configure
   ```

2. **Usando variáveis de ambiente para o perfil AWS**:
   ```bash
   # Método 1: Definir o perfil diretamente
   export AWS_PROFILE=meu-perfil
   
   # Método 2: Definir o perfil apenas para o deploy do CDK
   export CDK_DEPLOY_PROFILE=meu-perfil
   ```

3. **Usando variáveis de ambiente para credenciais específicas**:
   ```bash
   export AWS_ACCESS_KEY_ID="SUACHAVE"
   export AWS_SECRET_ACCESS_KEY="SUASECRETA"
   export AWS_DEFAULT_REGION="us-east-2"
   ```

O script vai procurar por credenciais na seguinte ordem:
1. Perfil definido em `AWS_PROFILE`
2. Perfil definido em `CDK_DEPLOY_PROFILE`
3. Credenciais padrão (~/.aws/credentials ou variáveis de ambiente)

```
fipe-data-cdk/
├── app.py                      # Ponto de entrada da aplicação CDK
├── fipe_data_stack.py          # Definição da stack principal
├── create_fipe_db.sql          # Script SQL original para criar as tabelas FIPE
├── README.md                   # Documentação principal
├── requirements.txt            # Dependências Python
├── lambda/                     # Código da função Lambda
│   ├── index.py                # Handler da função Lambda
│   ├── cfnresponse.py          # Utilitário para responder a eventos CloudFormation
│   └── assets/                 # Assets empacotados com a função Lambda
│       └── create_fipe_db.sql  # Cópia do script SQL
└── lambda-layer/               # Camada Lambda para psycopg2
    └── README.md               # Instruções para preparar a camada Lambda
```

## Preparação do Ambiente

1. Clone este repositório:
   ```bash
   git clone <url-do-repositorio>
   cd fipe-data-cdk
   ```

2. Crie um ambiente virtual Python e ative-o:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Linux/Mac
   .venv\Scripts\activate     # Windows
   ```

3. Instale as dependências:
   ```bash
   pip install -r requirements.txt
   ```

4. Prepare a camada Lambda com psycopg2:
   ```bash
   # Crie os diretórios necessários
   mkdir -p lambda-layer/python/lib/python3.10/site-packages

   # Instale o psycopg2-binary no diretório da camada
   pip install psycopg2-binary -t lambda-layer/python/lib/python3.10/site-packages
   ```

   Alternativamente, use Docker para garantir compatibilidade com o ambiente Lambda:
   ```bash
   docker run --rm -v $(pwd)/lambda-layer:/opt amazonlinux:2 \
     bash -c "yum install -y python3.10 python3.10-devel postgresql-devel gcc && \
              pip3 install psycopg2-binary -t /opt/python/lib/python3.10/site-packages/"
   ```

## Deploy

1. Bootstrap do ambiente CDK (se ainda não tiver sido feito):
   ```bash
   cdk bootstrap
   ```

2. Configure os parâmetros de contexto para o deploy:
   ```bash
   # Parâmetros obrigatórios:
   # - vpc_id: ID da VPC onde o banco de dados será criado
   # - allowed_ip: Endereço IP que terá acesso ao banco de dados
   
   cdk deploy --context vpc_id=vpc-xxxxxxxx --context allowed_ip=123.456.789.0
   ```

3. Escolha o estágio de implantação (dev, stg, prd) e o perfil AWS:
   
   **Usando variável de ambiente para estágio:**
   ```bash
   export STACK_STAGE=dev  # ou stg ou prd
   export AWS_PROFILE=meu-perfil  # Perfil do arquivo ~/.aws/credentials
   cdk deploy
   ```
   
   **Ou passando o estágio como argumento:**
   ```bash
   # Para ambiente de desenvolvimento com perfil específico
   export AWS_PROFILE=perfil-dev
   python app.py dev
   cdk deploy
   
   # Para ambiente de staging com outro perfil
   export AWS_PROFILE=perfil-stg
   python app.py stg
   cdk deploy
   
   # Para ambiente de produção com perfil de produção
   export AWS_PROFILE=perfil-prod
   python app.py prd
   cdk deploy
   ```

3. Escolha o estágio de implantação (dev, stg, prd) e o perfil AWS:
   
   ```bash
   # Para ambiente de desenvolvimento
   export AWS_PROFILE=perfil-dev
   python app.py dev
   cdk deploy --context vpc_id=vpc-xxxxxxxx --context allowed_ip=123.456.789.0
   
   # Para ambiente de staging
   export AWS_PROFILE=perfil-stg
   python app.py stg
   cdk deploy --context vpc_id=vpc-xxxxxxxx --context allowed_ip=123.456.789.0
   
   # Para ambiente de produção
   export AWS_PROFILE=perfil-prod
   python app.py prd
   cdk deploy --context vpc_id=vpc-xxxxxxxx --context allowed_ip=123.456.789.0
   ```

   Cada ambiente (dev, stg, prd) pode ter seu próprio perfil AWS diferente,
   permitindo implantações em contas AWS diferentes.

3. Realize o deploy da stack:
   ```bash
   cdk deploy
   ```

## Pós-Deploy

Após o deploy bem-sucedido, o CDK fornecerá os seguintes outputs:
- **DBEndpoint**: O endpoint do cluster PostgreSQL Aurora
- **DBPort**: A porta do cluster PostgreSQL Aurora (padrão: 5432)
- **DBSecretArn**: O ARN do segredo contendo as credenciais do banco de dados

Para obter as credenciais do banco de dados:
```bash
aws secretsmanager get-secret-value --secret-id <DBSecretArn> --query 'SecretString' --output text
```

## Conectando ao Banco de Dados

Usando o cliente PostgreSQL (psql):
```bash
# Obtenha a senha do Secrets Manager
DB_SECRET=$(aws secretsmanager get-secret-value --secret-id <DBSecretArn> --query 'SecretString' --output text)
DB_PASSWORD=$(echo $DB_SECRET | jq -r '.password')

# Conecte-se ao banco de dados
psql -h <DBEndpoint> -p 5432 -U postgres -d fipe-data -W
# Digite a senha quando solicitado
```

## Customização

Para personalizar a implantação:

- Altere o tamanho da instância: modifique `ec2.InstanceSize.SMALL` para outro tamanho
- Configurações de backup: altere `backup_retention=Duration.days(7)` para o período desejado
- Nome do banco de dados: modifique `default_database_name="fipe-data"`

## Limpeza

Para remover todos os recursos criados:
```bash
cdk destroy
```

## Notas Importantes

- A instância é configurada para ser elegível ao tier gratuito da AWS
- O acesso é restrito ao IP especificado por motivos de segurança
- O usuário padrão do banco de dados é `postgres`
- A senha é gerada automaticamente e armazenada no AWS Secrets Manager