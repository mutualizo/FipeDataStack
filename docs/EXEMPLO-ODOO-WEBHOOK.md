# Integração Webhook FIPE - Odoo v19

## Visão Geral

Exemplo de como receber webhooks da Melhoria 4 (FipeSomaNotifier) em uma instância Odoo v19 e processar os dados no banco de dados.

## Estrutura do Módulo Odoo

```
fipe_webhook/
├── __init__.py
├── __manifest__.py
├── models/
│   ├── __init__.py
│   └── fipe_data.py
├── controllers/
│   ├── __init__.py
│   └── webhook.py
└── security/
    └── ir.model.access.csv
```

## 1. Manifesto do Módulo

**File: `fipe_webhook/__manifest__.py`**

```python
{
    'name': 'FIPE Webhook Integration',
    'version': '19.0.1.0.0',
    'category': 'Tools',
    'summary': 'Recebe webhooks da Melhoria 4 (FipeDataStack) e processa dados FIPE',
    'author': 'Mutualizo',
    'license': 'LGPL-3',
    'depends': ['base', 'web'],
    'data': [
        'security/ir.model.access.csv',
    ],
    'installable': True,
    'auto_install': False,
}
```

## 2. Modelo de Dados

**File: `fipe_webhook/models/fipe_data.py`**

```python
from odoo import models, fields, api
from datetime import datetime
import logging

_logger = logging.getLogger(__name__)


class FipeWebhookData(models.Model):
    _name = 'fipe.webhook.data'
    _description = 'FIPE Webhook Data'
    _order = 'date_received desc'

    # Campos principais
    reference_month = fields.Char(
        string='Reference Month',
        required=True,
        index=True,
        help='Mês de referência (YYYY-MM)'
    )
    records_total = fields.Integer(
        string='Total Records',
        required=True,
        help='Total de registros recebidos'
    )
    pipeline = fields.Char(
        string='Pipeline',
        default='fipe_monthly_load',
        help='Nome do pipeline FIPE'
    )
    stage = fields.Char(
        string='Stage',
        required=True,
        help='Estágio (sa-east-1, stg, prd)'
    )
    
    # Metadata
    date_received = fields.Datetime(
        string='Date Received',
        default=lambda self: datetime.now(),
        required=True,
        index=True
    )
    webhook_timestamp = fields.Char(
        string='Webhook Timestamp',
        help='Timestamp ISO enviado pelo webhook'
    )
    
    # Status e logs
    status = fields.Selection([
        ('received', 'Recebido'),
        ('processed', 'Processado'),
        ('error', 'Erro'),
    ], string='Status', default='received')
    
    processing_log = fields.Text(
        string='Processing Log',
        help='Log de processamento'
    )
    
    error_message = fields.Text(
        string='Error Message',
        help='Mensagem de erro (se houver)'
    )
    
    # Relações
    product_ids = fields.Many2many(
        'product.product',
        string='Products Updated',
        help='Produtos afetados por esta atualização'
    )
    
    @api.model
    def create_from_webhook(self, webhook_data):
        """
        Processa dados do webhook e cria/atualiza registros no banco.
        
        Args:
            webhook_data (dict): Dados recebidos do webhook
                {
                    "type": "WEBHOOK_NOTIFY",
                    "pipeline": "fipe_monthly_load",
                    "reference_month": "2026-06",
                    "records_total": 45230,
                    "timestamp": "2026-06-15T14:30:00Z",
                    "stage": "sa-east-1"
                }
        
        Returns:
            fipe.webhook.data: Registro criado
        """
        try:
            # Validar dados obrigatórios
            required_fields = ['reference_month', 'records_total', 'stage']
            for field in required_fields:
                if field not in webhook_data:
                    raise ValueError(f"Campo obrigatório ausente: {field}")
            
            # Verificar se já existe registro para este mês
            existing = self.search([
                ('reference_month', '=', webhook_data['reference_month']),
                ('stage', '=', webhook_data['stage']),
            ])
            
            webhook_values = {
                'reference_month': webhook_data['reference_month'],
                'records_total': webhook_data['records_total'],
                'stage': webhook_data['stage'],
                'pipeline': webhook_data.get('pipeline', 'fipe_monthly_load'),
                'webhook_timestamp': webhook_data.get('timestamp'),
                'status': 'received',
                'processing_log': f"Webhook recebido em {datetime.now()}"
            }
            
            if existing:
                # Atualizar registro existente
                _logger.info(
                    f"FIPE: Atualizando webhook data para {webhook_data['reference_month']} - {webhook_data['stage']}"
                )
                existing.write(webhook_values)
                fipe_record = existing[0]
            else:
                # Criar novo registro
                _logger.info(
                    f"FIPE: Criando webhook data para {webhook_data['reference_month']} - {webhook_data['stage']}"
                )
                fipe_record = self.create(webhook_values)
            
            # Processar dados (atualizar produtos, etc)
            fipe_record._process_webhook_data(webhook_data)
            
            return fipe_record
            
        except Exception as e:
            _logger.error(f"FIPE: Erro ao processar webhook: {str(e)}")
            raise
    
    def _process_webhook_data(self, webhook_data):
        """
        Processa os dados do webhook e executa ações no banco de dados.
        
        Exemplos de ações:
        - Atualizar preços de produtos
        - Sincronizar catálogo de veículos
        - Gerar relatórios
        - Notificar outros sistemas
        """
        self.ensure_one()
        
        try:
            _logger.info(
                f"FIPE: Iniciando processamento de {self.records_total} registros "
                f"para {self.reference_month} ({self.stage})"
            )
            
            # EXEMPLO 1: Atualizar produtos baseado em dados FIPE
            self._update_vehicle_products()
            
            # EXEMPLO 2: Criar movimento de estoque
            self._create_inventory_movement()
            
            # EXEMPLO 3: Notificar gerente de vendas
            self._notify_sales_manager()
            
            # EXEMPLO 4: Gerar relatório de precificação
            self._generate_pricing_report()
            
            # Marcar como processado
            self.write({
                'status': 'processed',
                'processing_log': f"{self.processing_log}\n[{datetime.now()}] Processamento concluído com sucesso"
            })
            
            _logger.info(f"FIPE: Webhook processado com sucesso (ID: {self.id})")
            
        except Exception as e:
            _logger.error(f"FIPE: Erro no processamento de webhook: {str(e)}")
            self.write({
                'status': 'error',
                'error_message': str(e),
                'processing_log': f"{self.processing_log}\n[{datetime.now()}] ERRO: {str(e)}"
            })
            raise
    
    def _update_vehicle_products(self):
        """Atualizar preços de produtos de veículos baseado em dados FIPE."""
        _logger.info(f"FIPE: Atualizando preços de produtos para {self.reference_month}")
        
        Product = self.env['product.product']
        
        # Exemplo: buscar produtos relacionados a FIPE
        products = Product.search([
            ('categ_id.name', '=', 'Veículos'),
            ('type', '=', 'product'),
        ])
        
        for product in products:
            # Aqui você buscaria dados reais da API FIPE
            # Por enquanto, apenas um exemplo de atualização
            
            # Exemplo: atualizar lista_price baseado em reference_month
            if hasattr(product, 'fipe_reference_month'):
                product.fipe_reference_month = self.reference_month
            
            _logger.info(f"FIPE: Produto atualizado: {product.name} ({product.id})")
        
        self.product_ids = products
        _logger.info(f"FIPE: {len(products)} produtos atualizados")
    
    def _create_inventory_movement(self):
        """Criar movimento de inventário para rastrear alterações FIPE."""
        _logger.info(f"FIPE: Criando movimento de inventário")
        
        # Exemplo de criação de movimento
        inventory_log = {
            'name': f'FIPE Update - {self.reference_month}',
            'date': datetime.now(),
            'reference': f'FIPE/{self.reference_month}/{self.stage}',
            'description': f'Atualização FIPE com {self.records_total} registros',
        }
        
        _logger.info(f"FIPE: Movimento criado: {inventory_log['reference']}")
    
    def _notify_sales_manager(self):
        """Notificar gerente de vendas sobre atualização FIPE."""
        _logger.info(f"FIPE: Notificando gerente de vendas")
        
        # Buscar gerente de vendas
        User = self.env['res.users']
        sales_manager = User.search([
            ('groups_id.name', '=', 'Sales / Manager'),
        ], limit=1)
        
        if sales_manager:
            # Criar notificação ou enviar email
            message = (
                f"Atualização FIPE disponível\n\n"
                f"Mês: {self.reference_month}\n"
                f"Registros: {self.records_total}\n"
                f"Stage: {self.stage}\n"
                f"Data: {self.date_received}"
            )
            
            _logger.info(f"FIPE: Notificação enviada para {sales_manager.name}")
    
    def _generate_pricing_report(self):
        """Gerar relatório de precificação baseado em dados FIPE."""
        _logger.info(f"FIPE: Gerando relatório de precificação")
        
        report_data = {
            'reference_month': self.reference_month,
            'total_records': self.records_total,
            'stage': self.stage,
            'date_generated': datetime.now(),
            'products_updated': len(self.product_ids),
        }
        
        _logger.info(f"FIPE: Relatório gerado: {report_data}")
```

**File: `fipe_webhook/models/__init__.py`**

```python
from . import fipe_data
```

## 3. Controller - Receber Webhook

**File: `fipe_webhook/controllers/webhook.py`**

```python
import logging
import json
import hashlib
import hmac
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class FipeWebhookController(http.Controller):
    """
    Controller para receber webhooks da Melhoria 4 (FipeDataStack)
    
    Segurança:
    - Token de acesso no header X-Webhook-Token
    - Validação de token contra lista de tokens autorizados
    - Logging de tentativas de acesso não autorizado
    """
    
    # Tokens de acesso esperados (deve estar em variável de ambiente ou configuração)
    # Formato: {environment: token}
    WEBHOOK_TOKENS = {
        'sa-east-1': 'fipe_webhook_token_sa_east_1_abc123xyz789',
        'stg': 'fipe_webhook_token_stg_def456uvw012',
        'prd': 'fipe_webhook_token_prd_ghi789rst345',
    }
    
    @http.route('/api/fipe/webhook', type='json', auth='public', methods=['POST'])
    def receive_fipe_webhook(self, **kwargs):
        """
        Endpoint para receber webhooks da Melhoria 4
        
        POST /api/fipe/webhook
        
        Headers (OBRIGATÓRIO):
            X-Webhook-Token: <token_de_acesso>
            Content-Type: application/json
        
        Body:
        {
            "type": "WEBHOOK_NOTIFY",
            "pipeline": "fipe_monthly_load",
            "reference_month": "2026-06",
            "records_total": 45230,
            "timestamp": "2026-06-15T14:30:00Z",
            "stage": "sa-east-1"
        }
        
        Response (Sucesso):
        {
            "status": 200,
            "message": "Webhook recebido e processado com sucesso",
            "webhook_id": 1,
            "reference_month": "2026-06",
            "records_total": 45230
        }
        
        Response (Erro - Token inválido):
        {
            "status": 401,
            "message": "Token de acesso inválido",
            "error": true
        }
        """
        try:
            # ═══════════════════════════════════════════════════════════
            # 1. VALIDAÇÃO DE TOKEN (SEGURANÇA)
            # ═══════════════════════════════════════════════════════════
            
            webhook_token = request.httprequest.headers.get('X-Webhook-Token')
            
            if not webhook_token:
                _logger.warning(
                    "FIPE: Webhook rejeitado - X-Webhook-Token não fornecido | "
                    f"IP: {request.httprequest.remote_addr}"
                )
                return self._error_response('Token de acesso não fornecido', 401)
            
            # Validar token contra lista de tokens autorizados
            if not self._verify_webhook_token(webhook_token):
                _logger.warning(
                    f"FIPE: Webhook rejeitado - Token inválido | "
                    f"Token: {self._mask_token(webhook_token)} | "
                    f"IP: {request.httprequest.remote_addr}"
                )
                return self._error_response('Token de acesso inválido ou expirado', 401)
            
            _logger.info(
                f"FIPE: Token validado com sucesso | "
                f"Token: {self._mask_token(webhook_token)}"
            )
            
            # ═══════════════════════════════════════════════════════════
            # 2. VALIDAÇÃO DE DADOS
            # ═══════════════════════════════════════════════════════════
            
            webhook_data = request.get_json_data()
            
            if not webhook_data:
                _logger.warning("FIPE: Webhook recebido com body vazio")
                return self._error_response("Body JSON não fornecido", 400)
            
            # Validar campos obrigatórios
            required_fields = ['reference_month', 'records_total', 'stage', 'type']
            missing_fields = [f for f in required_fields if f not in webhook_data]
            
            if missing_fields:
                _logger.warning(f"FIPE: Campos obrigatórios ausentes: {missing_fields}")
                return self._error_response(
                    f"Campos obrigatórios ausentes: {', '.join(missing_fields)}", 
                    400
                )
            
            # Validar tipo de dados
            if not isinstance(webhook_data['records_total'], int) or webhook_data['records_total'] <= 0:
                _logger.warning("FIPE: records_total deve ser um inteiro positivo")
                return self._error_response("records_total deve ser um inteiro positivo", 400)
            
            if webhook_data['type'] != 'WEBHOOK_NOTIFY':
                _logger.warning(f"FIPE: Tipo de webhook inválido: {webhook_data['type']}")
                return self._error_response("Tipo de webhook não suportado", 400)
            
            # ═══════════════════════════════════════════════════════════
            # 3. PROCESSAR WEBHOOK
            # ═══════════════════════════════════════════════════════════
            
            _logger.info(
                f"FIPE: Webhook autorizado e validado | "
                f"Mês: {webhook_data['reference_month']} | "
                f"Registros: {webhook_data['records_total']} | "
                f"Stage: {webhook_data['stage']}"
            )
            
            # Criar registro no banco de dados
            fipe_webhook_model = request.env['fipe.webhook.data']
            fipe_record = fipe_webhook_model.create_from_webhook(webhook_data)
            
            # ═══════════════════════════════════════════════════════════
            # 4. RESPOSTA DE SUCESSO
            # ═══════════════════════════════════════════════════════════
            
            _logger.info(
                f"FIPE: Webhook processado com sucesso | "
                f"ID: {fipe_record.id} | "
                f"Status: {fipe_record.status}"
            )
            
            return {
                'status': 200,
                'message': 'Webhook recebido e processado com sucesso',
                'webhook_id': fipe_record.id,
                'reference_month': fipe_record.reference_month,
                'records_total': fipe_record.records_total,
            }
            
        except Exception as e:
            _logger.error(f"FIPE: Erro ao processar webhook: {str(e)}")
            return self._error_response(f"Erro interno: {str(e)}", 500)
    
    def _verify_webhook_token(self, token):
        """
        Verifica se o token fornecido é válido.
        
        Args:
            token (str): Token de acesso fornecido no header
            
        Returns:
            bool: True se o token é válido, False caso contrário
        """
        # Verificar contra tokens conhecidos
        if token in self.WEBHOOK_TOKENS.values():
            return True
        
        # Verificar contra variável de ambiente (para produção)
        import os
        allowed_tokens = os.environ.get('FIPE_WEBHOOK_TOKENS', '').split(',')
        if token in allowed_tokens:
            return True
        
        # Verificar contra ir.config.parameter do Odoo
        try:
            config = request.env['ir.config_parameter'].sudo()
            odoo_tokens = config.get_param('fipe.webhook.tokens', '').split(',')
            if token in odoo_tokens:
                return True
        except:
            pass
        
        return False
    
    def _mask_token(self, token):
        """
        Mascara o token para logging (mostra apenas primeiros e últimos 4 caracteres).
        
        Args:
            token (str): Token completo
            
        Returns:
            str: Token mascarado (ex: fipe_...xyz789)
        """
        if len(token) <= 8:
            return '****'
        return f"{token[:7]}...{token[-6:]}"
    
    def _error_response(self, message, status_code):
        """
        Retorna resposta de erro padronizada.
        
        Args:
            message (str): Mensagem de erro
            status_code (int): Código HTTP (401, 400, 500, etc)
            
        Returns:
            dict: Dicionário com status, message e error=True
        """
        return {
            'status': status_code,
            'message': message,
            'error': True,
        }
    
    @http.route('/api/fipe/webhook/status', type='json', auth='public', methods=['GET'])
    def webhook_status(self, **kwargs):
        """
        Endpoint para verificar status do webhook (health check)
        
        GET /api/fipe/webhook/status
        """
        try:
            fipe_webhook_model = request.env['fipe.webhook.data']
            
            # Contar webhooks por status
            stats = {
                'total': fipe_webhook_model.search_count([]),
                'received': fipe_webhook_model.search_count([('status', '=', 'received')]),
                'processed': fipe_webhook_model.search_count([('status', '=', 'processed')]),
                'error': fipe_webhook_model.search_count([('status', '=', 'error')]),
            }
            
            return {
                'status': 200,
                'message': 'FIPE Webhook service OK',
                'stats': stats,
            }
        except Exception as e:
            return {
                'status': 500,
                'message': str(e),
                'error': True,
            }
```

**File: `fipe_webhook/controllers/__init__.py`**

```python
from . import webhook
```

## 4. Permissões de Acesso

**File: `fipe_webhook/security/ir.model.access.csv`**

```csv
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
access_fipe_webhook_data_user,fipe.webhook.data user,model_fipe_webhook_data,base.group_user,1,0,0,0
access_fipe_webhook_data_manager,fipe.webhook.data manager,model_fipe_webhook_data,sales.group_sales_manager,1,1,1,0
```

**File: `fipe_webhook/__init__.py`**

```python
from . import models
from . import controllers
```

## 5. Instalação

```bash
# 1. Copiar módulo para addons
cp -r fipe_webhook /path/to/odoo/addons/

# 2. Reiniciar Odoo
./odoo-bin --addons-path=/path/to/addons -d seu_banco -u base

# 3. Ir para Aplicativos > Atualizar lista de aplicativos
# 4. Procurar por "FIPE Webhook Integration"
# 5. Instalar módulo
```

## 6. Teste Manual

### Token de Acesso

Os tokens estão definidos no controller:

```python
WEBHOOK_TOKENS = {
    'sa-east-1': 'fipe_webhook_token_sa_east_1_abc123xyz789',
    'stg': 'fipe_webhook_token_stg_def456uvw012',
    'prd': 'fipe_webhook_token_prd_ghi789rst345',
}
```

**⚠️ IMPORTANTE:** Em produção, use **variáveis de ambiente** ou **ir.config.parameter**!

### Teste via curl (Token Válido)

```bash
# Teste com token válido
curl -X POST https://seu-odoo.com/api/fipe/webhook \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Token: fipe_webhook_token_sa_east_1_abc123xyz789" \
  -d '{
    "type": "WEBHOOK_NOTIFY",
    "pipeline": "fipe_monthly_load",
    "reference_month": "2026-06",
    "records_total": 45230,
    "timestamp": "2026-06-15T14:30:00Z",
    "stage": "sa-east-1"
  }'
```

### Teste via curl (Token Inválido)

```bash
# Teste com token inválido (deve retornar 401)
curl -X POST https://seu-odoo.com/api/fipe/webhook \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Token: token_invalido_123" \
  -d '{
    "type": "WEBHOOK_NOTIFY",
    "pipeline": "fipe_monthly_load",
    "reference_month": "2026-06",
    "records_total": 45230,
    "timestamp": "2026-06-15T14:30:00Z",
    "stage": "sa-east-1"
  }'
```

### Teste via curl (Sem Token)

```bash
# Teste sem token (deve retornar 401)
curl -X POST https://seu-odoo.com/api/fipe/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "type": "WEBHOOK_NOTIFY",
    "pipeline": "fipe_monthly_load",
    "reference_month": "2026-06",
    "records_total": 45230,
    "timestamp": "2026-06-15T14:30:00Z",
    "stage": "sa-east-1"
  }'
```

### Resposta esperada (Sucesso - 200)

```json
{
  "status": 200,
  "message": "Webhook recebido e processado com sucesso",
  "webhook_id": 1,
  "reference_month": "2026-06",
  "records_total": 45230
}
```

### Resposta esperada (Token Inválido - 401)

```json
{
  "status": 401,
  "message": "Token de acesso inválido ou expirado",
  "error": true
}
```

### Resposta esperada (Token Ausente - 401)

```json
{
  "status": 401,
  "message": "Token de acesso não fornecido",
  "error": true
}
```

### Resposta esperada (Body Inválido - 400)

```json
{
  "status": 400,
  "message": "Campos obrigatórios ausentes: type",
  "error": true
}
```

## 7. Verificar Processamento

### No Odoo

1. Acesse: **Ferramentas > FIPE Webhook Integration > Webhook Data**
2. Localize o registro com reference_month = "2026-06"
3. Verifique status: "Processado"
4. Verifique logs em "Processing Log"

### Via Logs

```bash
# Ver logs do Odoo
tail -f /var/log/odoo/odoo.log | grep FIPE

# Buscar por status
grep "FIPE:" /var/log/odoo/odoo.log
```

## 8. Configurações Seguras de Token

### ✅ Recomendado: Variável de Ambiente

**Adicionar ao arquivo `.env` ou ao script de inicialização do Odoo:**

```bash
# .env
FIPE_WEBHOOK_TOKENS="fipe_webhook_token_sa_east_1_abc123xyz789,fipe_webhook_token_stg_def456uvw012,fipe_webhook_token_prd_ghi789rst345"
```

**Usar no controller:**

```python
import os

def _verify_webhook_token(self, token):
    """Verifica token contra variável de ambiente."""
    # Verificar contra variável de ambiente (PREFERIDO)
    allowed_tokens = os.environ.get('FIPE_WEBHOOK_TOKENS', '').split(',')
    return token in allowed_tokens
```

### ✅ Alternativa: ir.config.parameter (Odoo)

**Criar configuração via Código:**

```python
# __manifest__.py
'data': [
    'data/webhook_config.xml',
],
```

**File: `fipe_webhook/data/webhook_config.xml`**

```xml
<odoo>
    <data noupdate="1">
        <!-- Configuração de tokens do webhook FIPE -->
        <record id="fipe_webhook_token_sa_east_1" model="ir.config_parameter">
            <field name="key">fipe.webhook.token.sa_east_1</field>
            <field name="value">fipe_webhook_token_sa_east_1_abc123xyz789</field>
        </record>
        
        <record id="fipe_webhook_token_stg" model="ir.config_parameter">
            <field name="key">fipe.webhook.token.stg</field>
            <field name="value">fipe_webhook_token_stg_def456uvw012</field>
        </record>
        
        <record id="fipe_webhook_token_prd" model="ir.config_parameter">
            <field name="key">fipe.webhook.token.prd</field>
            <field name="value">fipe_webhook_token_prd_ghi789rst345</field>
        </record>
    </data>
</odoo>
```

**Usar no controller:**

```python
def _verify_webhook_token(self, token):
    """Verifica token contra ir.config.parameter."""
    try:
        config = request.env['ir.config_parameter'].sudo()
        
        # Buscar tokens para cada ambiente
        for env in ['sa_east_1', 'stg', 'prd']:
            stored_token = config.get_param(f'fipe.webhook.token.{env}')
            if token == stored_token:
                return True
    except:
        pass
    
    return False
```

### ✅ Produção: Token com Expiração

**Versão avançada com timestamp:**

```python
from datetime import datetime, timedelta
import json

def _verify_webhook_token(self, token):
    """Verifica token com expiração."""
    try:
        # Decodificar token (ex: base64 encoded JSON)
        import base64
        decoded = base64.b64decode(token).decode('utf-8')
        token_data = json.loads(decoded)
        
        # Verificar expiração
        expiration = datetime.fromisoformat(token_data['exp'])
        if datetime.now() > expiration:
            _logger.warning(f"FIPE: Token expirado: {token_data['env']}")
            return False
        
        # Verificar ambiente
        valid_tokens = {
            'sa-east-1': 'abc123xyz789',
            'stg': 'def456uvw012',
            'prd': 'ghi789rst345',
        }
        
        if token_data['env'] in valid_tokens:
            # Usar HMAC para validação adicional
            expected_signature = hmac.new(
                b'your-secret-key',
                msg=f"{token_data['env']}{token_data['exp']}".encode(),
                digestmod=hashlib.sha256
            ).hexdigest()
            
            return token_data.get('sig') == expected_signature
        
        return False
    except:
        return False
```

### 🔐 Segurança: Boas Práticas

1. **Nunca colocar tokens hardcoded no código**
   ```python
   # ❌ ERRADO
   WEBHOOK_TOKENS = {
       'sa-east-1': 'fipe_webhook_token_...',
   }
   
   # ✅ CORRETO
   import os
   WEBHOOK_TOKENS = os.environ.get('FIPE_WEBHOOK_TOKENS', '').split(',')
   ```

2. **Use tokens longos e aleatórios**
   ```bash
   # Gerar token seguro
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

3. **Rotacione tokens regularmente**
   ```bash
   # Mudar tokens a cada 90 dias
   export FIPE_WEBHOOK_TOKENS="novo_token_1,novo_token_2"
   # Redeploy Odoo
   ```

4. **Log de tentativas falhadas**
   ```python
   _logger.warning(
       f"FIPE: Webhook rejeitado - Token inválido | "
       f"Token: {self._mask_token(webhook_token)} | "
       f"IP: {request.httprequest.remote_addr}"
   )
   ```

5. **Monitorar acessos suspeitos**
   ```bash
   # Verificar logs
   grep "FIPE: Webhook rejeitado" /var/log/odoo/odoo.log | wc -l
   ```

## 9. Monitoramento

### Alertas por Email

Adicionar ao `_process_webhook_data`:

```python
def _notify_admin_on_error(self):
    """Notificar administrador em caso de erro."""
    if self.status == 'error':
        mail_template = self.env.ref('fipe_webhook.email_webhook_error')
        mail_template.send_mail(self.id)
```

### Dashboard

Criar dashboard em Odoo para visualizar:
- Total de webhooks recebidos
- Webhooks processados com sucesso
- Webhooks com erro
- Últimas atualizações FIPE

## Referências

- Webhook Payload: [WEBHOOK-CONFIG.md](./WEBHOOK-CONFIG.md)
- Documentação Odoo v19: https://www.odoo.com/documentation/19.0/
- Documentação ORM: https://www.odoo.com/documentation/19.0/developer/reference/backend/orm.html
- HTTP Routing: https://www.odoo.com/documentation/19.0/developer/reference/backend/http.html
