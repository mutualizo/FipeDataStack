#!/bin/bash

# Este script cria uma camada Lambda otimizada e a comprime em um arquivo ZIP
# Criado por Claude em 24/03/2025

set -e  # Sair imediatamente se algum comando falhar

echo "=== Criando camada Lambda otimizada para LambdaLayer ==="

# Criar estrutura de diretórios
mkdir -p lambda-layer/python/lib/python3.10/site-packages

# Instalar apenas as dependências essenciais
pip install psycopg2-binary -t lambda-layer/python/lib/python3.10/site-packages
cd lambda-layer
zip -r ../psycopg2-layer.zip python
cd ..


echo "=== Criando camada Lambda otimizada para FipeApiStack ==="

# Definir diretórios e arquivos
LAYER_DIR="fipe_api_layer/python/lib/python3.10/site-packages"
ZIP_FILE="fipe_api_layer.zip"
REQUIRED_PACKAGES="boto3 requests psycopg2-binary pydantic"

# Criar estrutura de diretórios
mkdir -p "$LAYER_DIR"

# Limpar diretório anterior se existir
echo "Limpando diretório anterior..."
rm -rf "$LAYER_DIR"/*

# Instalar apenas as dependências essenciais
echo "Instalando pacotes essenciais: $REQUIRED_PACKAGES"
pip install $REQUIRED_PACKAGES -t "$LAYER_DIR"

# Remover arquivos desnecessários para reduzir o tamanho
echo "Otimizando o tamanho da camada..."
find "$LAYER_DIR" -type d -name "__pycache__" -exec rm -rf {} +  2>/dev/null || true
find "$LAYER_DIR" -type f -name "*.pyc" -delete
find "$LAYER_DIR" -type f -name "*.pyo" -delete
find "$LAYER_DIR" -type d -name "tests" -exec rm -rf {} +  2>/dev/null || true
find "$LAYER_DIR" -type d -name "test" -exec rm -rf {} +  2>/dev/null || true
find "$LAYER_DIR" -type d -name ".pytest_cache" -exec rm -rf {} +  2>/dev/null || true

# Verificar o tamanho do diretório
LAYER_SIZE=$(du -sh "fipe_api_layer" | cut -f1)
echo "Tamanho da camada antes da compressão: $LAYER_SIZE"

# Criar o arquivo ZIP
echo "Criando arquivo ZIP..."
cd fipe_api_layer
zip -r "../$ZIP_FILE" .
cd ..

# Verificar o tamanho do arquivo ZIP
ZIP_SIZE=$(du -sh "$ZIP_FILE" | cut -f1)
echo "Tamanho do arquivo ZIP: $ZIP_SIZE"

echo "=== Camada Lambda criada com sucesso! ==="
echo "Arquivo ZIP: $ZIP_FILE"
echo ""
echo "Para usar este arquivo manualmente no AWS Lambda:"
echo "1. Acesse o console AWS Lambda"
echo "2. Vá para 'Layers' e clique em 'Create layer'"
echo "3. Dê um nome à camada (ex: 'fipe-api-layer')"
echo "4. Faça upload do arquivo $ZIP_FILE"
echo "5. Escolha runtime compatível: Python 3.10"
echo "6. Clique em 'Create'"
echo ""
echo "Para referenciar a camada em seu CDK:"
echo "lambda_layer = lambda_.LayerVersion.from_layer_version_arn("
echo "    self, 'ImportedLayer',"
echo "    'arn:aws:lambda:[REGION]:[ACCOUNT_ID]:layer:[LAYER_NAME]:[VERSION]'"
echo ")"