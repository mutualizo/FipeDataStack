# Camada Lambda para psycopg2

Esta pasta deve conter a biblioteca psycopg2 compilada para ser usada como uma camada Lambda. A estrutura do diretório deve ser:

```
lambda-layer/
└── python/
    └── lib/
        └── python3.10/
            └── site-packages/
                └── psycopg2/
```

## Como preparar a camada

No Linux (similar ao ambiente Lambda), execute:

```bash
# Crie os diretórios necessários
mkdir -p lambda-layer/python/lib/python3.10/site-packages

# Instale o psycopg2-binary no diretório da camada
pip install psycopg2-binary -t lambda-layer/python/lib/python3.10/site-packages

# Opcionalmente, crie um arquivo zip se necessário
cd lambda-layer
zip -r ../psycopg2-layer.zip python
cd ..
```

Alternativamente, você pode baixar uma versão pré-compilada para o ambiente Lambda ou usar uma imagem Docker para preparar a camada.