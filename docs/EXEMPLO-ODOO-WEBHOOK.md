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
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class FipeWebhookController(http.Controller):
    """
    Controller para receber webhooks da Melhoria 4 (FipeDataStack)
    """
    
    # API Key esperada (deve estar em variável de ambiente ou configuração)
    # TODO: Mover para ir.config.parameter ou variável de ambiente
    EXPECTED_API_KEYS = [
        'test-key-123',
        'sk_live_production_key',
    ]
    
    @http.route('/api/fipe/webhook', type='json', auth='public', methods=['POST'])
    def receive_fipe_webhook(self, **kwargs):
        """
        Endpoint para receber webhooks da Melhoria 4
        
        POST /api/fipe/webhook
        
        Headers:
            X-API-Key: <api_key>
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
        
        Response:
        {
            "status": "received",
            "message": "Webhook processado com sucesso",
            "webhook_id": 123
        }
        """
        try:
            # 1. VALIDAÇÃO DE SEGURANÇA
            api_key = request.httprequest.headers.get('X-API-Key')
            
            if not api_key:
                _logger.warning("FIPE: Webhook recebido sem X-API-Key header")
                return self._error_response('API Key ausente', 401)
            
            if api_key not in self.EXPECTED_API_KEYS:
                _logger.warning(f"FIPE: Webhook recebido com API Key inválida: {api_key}")
                return self._error_response('API Key inválida', 401)
            
            # 2. VALIDAÇÃO DE DADOS
            webhook_data = request.get_json_data()
            
            # Validar campos obrigatórios
            required_fields = ['reference_month', 'records_total', 'stage']
            for field in required_fields:
                if field not in webhook_data:
                    _logger.warning(f"FIPE: Campo obrigatório ausente: {field}")
                    return self._error_response(f"Campo obrigatório ausente: {field}", 400)
            
            # Validar tipo de dados
            if not isinstance(webhook_data['records_total'], int) or webhook_data['records_total'] <= 0:
                _logger.warning("FIPE: records_total deve ser um inteiro positivo")
                return self._error_response("records_total inválido", 400)
            
            # 3. PROCESSAR WEBHOOK
            _logger.info(
                f"FIPE: Webhook válido recebido - "
                f"Mês: {webhook_data['reference_month']}, "
                f"Registros: {webhook_data['records_total']}, "
                f"Stage: {webhook_data['stage']}"
            )
            
            # Criar registro no banco de dados
            fipe_webhook_model = request.env['fipe.webhook.data']
            fipe_record = fipe_webhook_model.create_from_webhook(webhook_data)
            
            # 4. RESPOSTA DE SUCESSO
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
    
    def _error_response(self, message, status_code):
        """Retorna resposta de erro padronizada."""
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

### Teste via curl

```bash
# Teste com webhook.site
curl -X POST https://seu-odoo.com/api/fipe/webhook \
  -H "Content-Type: application/json" \
  -H "X-API-Key: test-key-123" \
  -d '{
    "type": "WEBHOOK_NOTIFY",
    "pipeline": "fipe_monthly_load",
    "reference_month": "2026-06",
    "records_total": 45230,
    "timestamp": "2026-06-15T14:30:00Z",
    "stage": "sa-east-1"
  }'
```

### Resposta esperada

```json
{
  "status": 200,
  "message": "Webhook recebido e processado com sucesso",
  "webhook_id": 1,
  "reference_month": "2026-06",
  "records_total": 45230
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

## 8. Configurações Avançadas

### Armazenar API Key em variável de ambiente

**Modificar: `controllers/webhook.py`**

```python
import os

# Buscar API keys de variável de ambiente
EXPECTED_API_KEYS = os.environ.get('FIPE_API_KEYS', 'test-key-123').split(',')
```

### Usar ir.config.parameter

**Modificar: `controllers/webhook.py`**

```python
@http.route('/api/fipe/webhook', type='json', auth='public', methods=['POST'])
def receive_fipe_webhook(self, **kwargs):
    # Buscar API keys da configuração Odoo
    config = request.env['ir.config_parameter'].sudo()
    allowed_api_keys = config.get_param('fipe.webhook.api_keys', 'test-key-123').split(',')
    
    api_key = request.httprequest.headers.get('X-API-Key')
    
    if api_key not in allowed_api_keys:
        return self._error_response('API Key inválida', 401)
    
    # ... resto do código
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
