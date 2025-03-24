# FipeData - Banco de Dados PostgreSQL Aurora na AWS com Stack de API FIPE

Este projeto utiliza AWS CDK em Python para provisionar dois componentes principais:

1. **FipeDataStack**: Um banco de dados PostgreSQL Aurora na AWS para armazenar dados da Tabela FIPE.
2. **FipeApiStack**: Um conjunto de funções Lambda e filas SQS para extrair, processar e armazenar dados da API FIPE.

## Sobre o Projeto

### FipeDataStack (Stack Principal)
A stack principal cria os seguintes recursos:
- Banco de dados PostgreSQL Aurora com instância T3.MEDIUM
- Grupo de segurança com acesso restrito ao IP especificado
- Secret no AWS Secrets Manager para armazenar credenciais do banco
- Função Lambda para executar o script SQL inicial
- Camada Lambda com a biblioteca psycopg2 para conectividade PostgreSQL

### FipeApiStack (Stack Filho)
O stack filho cria os seguintes recursos:
- 4 Funções Lambda para processar dados da API FIPE:
  - **FipeManufacturerLoader**: Carrega fabricantes de veículos
  - **FipeModelLoader**: Carrega modelos de veículos
  - **FipePriceLoader**: Carrega preços de veículos
  - **FipeSomaIngestor**: Insere dados processados no banco de dados
- 3 Filas SQS para coordenar o fluxo de dados entre as Lambdas
- 3 Filas DLQ (Dead Letter Queue) para mensagens não processadas
- Camada Lambda com todas as bibliotecas necessárias
- Grupo de segurança para as funções Lambda
- Permissões IAM para acesso às filas SQS e ao banco de dados

## Melhorias Implementadas

As seguintes melhorias foram implementadas para garantir robustez e manutenibilidade:

1. **Filas DLQ (Dead Letter Queue)**: Todas as filas SQS possuem uma DLQ associada para capturar mensagens que não puderam ser processadas após múltiplas tentativas.

2. **Variáveis de ambiente específicas**: As funções Lambda utilizam variáveis de ambiente claramente nomeadas:
   - `SQS_OUTPUT_URL`: URL da fila SQS para envio de mensagens
   - `SQS_INPUT_URL`: URL da fila SQS de entrada (implícita através do trigger)
   - `RDS_HOST`, `RDS_PORT`, `RDS_DATABASE`, `RDS_USER`: Parâmetros de conexão ao banco de dados

3. **Logs detalhados**: Todas as funções Lambda incluem logs detalhados para facilitar a depuração e o monitoramento.

4. **Relatório de falhas por item**: As funções Lambda reportam falhas por item em lotes SQS, permitindo o reprocessamento apenas das mensagens com falha.

5. **Gestão de throttling**: Implementação de backoffs exponenciais para lidar com limitações de taxa da API FIPE.

6. **Processamento em lotes otimizado**: As mensagens são enviadas em lotes para as filas SQS, com períodos de espera configuráveis para agrupar mensagens e melhorar a eficiência.

7. **Tratamento de duplicidades**: O ingestor verifica se um valor já existe no banco de dados antes de inserir, atualizando-o se necessário.

8. **Tratamento de erros robusto**: Cada função Lambda tem tratamento de erros granular, permitindo a continuidade do processamento mesmo quando ocorrem falhas em partes específicas.

9. **Marcação de recursos**: Todos os recursos AWS são marcados com tags para facilitar a identificação, organização e controle de custos.

10. **Arquitetura escalável**: O uso de filas SQS entre as etapas de processamento permite escalar cada componente independentemente.

## Pré-requisitos

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

A conta AWS será obtida automaticamente a partir do perfil utilizando a operação STS GetCallerIdentity.

## Estrutura do Projeto

```
fipe-data-cdk/
├── app.py                      # Ponto de entrada da aplicação CDK
├── fipe_data_stack.py          # Definição da stack principal
├── fipe_api_stack.py           # Definição da stack filho para API FIPE
├── create_fipe_db.sql          # Script SQL para criar as tabelas FIPE
├── create_fipe_api_layer.sh    # Script para criar a camada Lambda da API FIPE
├── Makefile                    # Automatiza tarefas de instalação e deploy
├── README.md                   # Documentação principal
├── requirements.txt            # Dependências Python
├── lambda/                     # Código da função Lambda para inicialização do banco
│   ├── index.py                # Handler da função Lambda
│   ├── cfnresponse.py          # Utilitário para responder a eventos CloudFormation
│   └── assets/                 # Assets empacotados com a função Lambda
│       └── create_fipe_db.sql  # Cópia do script SQL
├── lambda-layer/               # Camada Lambda para psycopg2
│   └── README.md               # Instruções para preparar a camada Lambda
└── src/                        # Código fonte para as funções Lambda da API FIPE
    └── fipe_api/               # Código das funções Lambda para API FIPE
        ├── __init__.py                    # Inicialização do pacote
        ├── fipe_manufacturer_loader.py    # Lambda para carregar fabricantes
        ├── fipe_model_loader.py           # Lambda para carregar modelos
        ├── fipe_price_loader.py           # Lambda para carregar preços
        ├── fipe_soma_ingestor.py          # Lambda para inserir dados no banco
        ├── fipe_soma_ingestor_adapted.py  # Versão adaptada do ingestor
        ├── fipe_api_service.py            # Serviço compartilhado para API FIPE
        └── get_db_password.py             # Utilitário para obter senha do banco
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

4. Prepare as camadas Lambda usando o Makefile:
   ```bash
   make prepare-layers
   ```

   Ou manualmente:
   ```bash
   # Preparar a camada para psycopg2
   mkdir -p lambda-layer/python/lib/python3.10/site-packages
   pip install psycopg2-binary -t lambda-layer/python/lib/python3.10/site-packages
   
   # Preparar a camada para API FIPE
   mkdir -p fipe_api_layer/python/lib/python3.10/site-packages
   pip install -r requirements.txt -t fipe_api_layer/python/lib/python3.10/site-packages
   
   # Preparar o código fonte
   mkdir -p src
   cp -r soma-api-lambdas/src/fipe_api src/
   ```

## Deploy

Para facilitar o deploy, use o Makefile:

```bash
# Deploy no ambiente de desenvolvimento
make deploy-dev AWS_PROFILE=meu-perfil VPC_ID=vpc-xxxxxxxx ALLOWED_IP=123.456.789.0

# Deploy no ambiente de staging
make deploy-stg AWS_PROFILE=meu-perfil VPC_ID=vpc-xxxxxxxx ALLOWED_IP=123.456.789.0

# Deploy no ambiente de produção
make deploy-prd AWS_PROFILE=meu-perfil VPC_ID=vpc-xxxxxxxx ALLOWED_IP=123.456.789.0
```

Ou faça o deploy manualmente:

1. Bootstrap do ambiente CDK (se ainda não tiver sido feito):
   ```bash
   cdk bootstrap --profile meu-perfil
   ```

2. Configure os parâmetros de contexto para o deploy:
   ```bash
   # Parâmetros obrigatórios:
   # - vpc_id: ID da VPC onde o banco de dados será criado
   # - allowed_ip: Endereço IP que terá acesso ao banco de dados
   
   export AWS_PROFILE=meu-perfil
   export STACK_STAGE=dev  # ou stg ou prd
   
   cdk deploy --context vpc_id=vpc-xxxxxxxx --context allowed_ip=123.456.789.0
   ```

## Pós-Deploy

Após o deploy bem-sucedido, o CDK fornecerá os seguintes outputs:

### FipeDataStack
- **DBEndpoint**: O endpoint do cluster PostgreSQL Aurora
- **DBPort**: A porta do cluster PostgreSQL Aurora (padrão: 5432)
- **DBSecretArn**: O ARN do segredo contendo as credenciais do banco de dados

### FipeApiStack
- **ManufacturerQueueUrl**: URL da fila SQS para fabricantes
- **ModelQueueUrl**: URL da fila SQS para modelos
- **PriceQueueUrl**: URL da fila SQS para preços
- **ManufacturerDLQUrl**: URL da fila DLQ para fabricantes
- **ModelDLQUrl**: URL da fila DLQ para modelos
- **PriceDLQUrl**: URL da fila DLQ para preços
- **FipeManufacturerLambda**: Nome da função Lambda para carregamento de fabricantes

Para obter as credenciais do banco de dados:
```bash
aws secretsmanager get-secret-value --secret-id <DBSecretArn> --query 'SecretString' --output text
```

## Executando o processo de carga de dados da FIPE

Para iniciar o processo de carga de dados da FIPE, você precisa invocar a função Lambda FipeManufacturerLoader:

```bash
# Substitua o nome da função pelo output do CDK
aws lambda invoke --function-name FipeManufacturerLoader-dev response.json
```

Isso iniciará o processo de carga de dados, que seguirá o fluxo abaixo:
1. FipeManufacturerLoader obtém os fabricantes e envia para a fila SQS de fabricantes
2. FipeModelLoader processa os fabricantes e envia os modelos para a fila SQS de modelos
3. FipePriceLoader processa os modelos e envia os preços para a fila SQS de preços
4. FipeSomaIngestor processa os preços e insere os dados no banco de dados PostgreSQL

## Monitoramento e Solução de Problemas

### CloudWatch Logs
Todas as funções Lambda enviam logs detalhados para o CloudWatch Logs:
```bash
# Visualizar logs da função Lambda FipeManufacturerLoader
aws logs filter-log-events --log-group-name /aws/lambda/FipeManufacturerLoader-dev
```

### Verificando mensagens nas filas DLQ
Para verificar se há mensagens que falharam no processamento:
```bash
# Obter o número aproximado de mensagens na fila DLQ
aws sqs get-queue-attributes --queue-url <ManufacturerDLQUrl> --attribute-names ApproximateNumberOfMessages
```

### Reprocessando mensagens de DLQ
Para reprocessar mensagens das filas DLQ:
```bash
# Criar um script para mover mensagens da DLQ de volta para a fila principal
aws sqs receive-message --queue-url <ManufacturerDLQUrl> --max-number-of-messages 10 | \
jq -r '.Messages[] | @base64' | while read msg; do
    body=$(echo $msg | base64 --decode | jq -r '.Body')
    aws sqs send-message --queue-url <ManufacturerQueueUrl> --message-body "$body"
    receipt=$(echo $msg | base64 --decode | jq -r '.ReceiptHandle')
    aws sqs delete-message --queue-url <ManufacturerDLQUrl> --receipt-handle "$receipt"
done
```

## Conectando ao Banco de Dados

Usando o cliente PostgreSQL (psql):
```bash
# Obtenha a senha do Secrets Manager
DB_SECRET=$(aws secretsmanager get-secret-value --secret-id <DBSecretArn> --query 'SecretString' --output text)
DB_PASSWORD=$(echo $DB_SECRET | jq -r '.password')

# Conecte-se ao banco de dados
psql -h <DBEndpoint> -p 5432 -U postgres -d fipedata -W
# Digite a senha quando solicitado
```

## Customização

Para personalizar a implantação:

- Altere o tamanho da instância: modifique `ec2.InstanceSize.SMALL` para outro tamanho
- Configurações de backup: altere `backup_retention=Duration.days(7)` para o período desejado
- Nome do banco de dados: modifique `default_database_name="fipe-data"`
- Timeouts das funções Lambda: ajuste `timeout=Duration.minutes(5)` conforme necessidade
- Configurações de lote SQS: ajuste `batch_size=10` e `max_batching_window=Duration.seconds(30)`

## Limpeza

Para remover todos os recursos criados, use o Makefile:
```bash
# Remover recursos do ambiente de desenvolvimento
make destroy-dev AWS_PROFILE=meu-perfil

# Remover recursos do ambiente de staging
make destroy-stg AWS_PROFILE=meu-perfil

# Remover recursos do ambiente de produção
make destroy-prd AWS_PROFILE=meu-perfil

# Limpar diretórios temporários
make clean
```

Ou manualmente:
```bash
export AWS_PROFILE=meu-perfil
export STACK_STAGE=dev  # ou stg ou prd
cdk destroy
```

## Notas Importantes

- A instância é configurada para ser elegível ao tier gratuito da AWS
- O acesso é restrito ao IP especificado por motivos de segurança
- O usuário padrão do banco de dados é `postgres`
- A senha é gerada automaticamente e armazenada no AWS Secrets Manager
- As funções Lambda da API FIPE têm um timeout de 5 minutos
- As filas SQS têm um período de retenção de 4 dias
- As filas DLQ têm um período de retenção de 14 dias
- As mensagens são movidas para a DLQ após 5 tentativas de processamento
- A API FIPE tem limitações de taxa, por isso implementamos backoffs exponenciais
