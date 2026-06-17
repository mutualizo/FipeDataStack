# Exemplo de Integração Webhook - Odoo v19

Este documento fornece um exemplo completo de como integrar o FipeDataStack2 com Odoo v19 para receber notificações de webhooks quando dados FIPE são disponibilizados.

## Visão Geral da Integração

```
FipeDataStack2 (AWS)
    ↓
    Dispara webhook para:
    ↓
Odoo v19 (/api/fipe/webhook)
    ↓
    Cria registro em fipe.webhook.data
    ↓
    Executa ações automáticas:
    - Atualiza preços de produtos
    - Registra movimentos de estoque
    - Notifica gestor de vendas
    - Gera relatório de preços
```

## Pré-requisitos

- Odoo v19 instalado
- Python 3.8+
- Módulo `requests` para testes
- Acesso administrativo ao Odoo

## Etapa 1: Configurar Chave de API no Odoo

### Opção 1: Via Variável de Ambiente (Recomendado para STG)

```bash
# Em seu servidor Odoo, defina:
export FIPE_WEBHOOK_TOKEN="seu-token-secreto-muito-seguro-2026"

# Ou em .env:
FIPE_WEBHOOK_TOKEN=seu-token-secreto-muito-seguro-2026

# Ou em docker-compose.yml:
environment:
  - FIPE_WEBHOOK_TOKEN=seu-token-secreto-muito-seguro-2026
```

### Opção 2: Via Configuração Odoo (ir.config.parameter)

1. Acesse: **Configurações > Técnico > Parâmetros**
2. Clique em **Novo**
3. Preencha:
   - **Chave:** `fipe_webhook.api_token`
   - **Valor:** `seu-token-secreto-muito-seguro-2026`

### Opção 3: Token com Expiração (Mais Seguro para PRD)

```python
# No seu script de inicialização do Odoo
import os
import json
from datetime import datetime, timedelta

# Gerar token com data de expiração
token_data = {
    "token": "seu-token-secreto",
    "expires_at": (datetime.now() + timedelta(days=90)).isoformat()
}

# Salvar em ir.config.parameter ou variável de ambiente
os.environ['FIPE_WEBHOOK_TOKEN_DATA'] = json.dumps(token_data)
```

## Etapa 2: Criar Modelo de Dados (fipe.webhook.data)

Crie um novo modelo Odoo para armazenar webhooks recebidos:

**Arquivo:** `models/fipe_webhook.py`

```python
from odoo import models, fields, api
from datetime import datetime

class FipeWebhookData(models.Model):
    _name = 'fipe.webhook.data'
    _description = 'Notificações FIPE Webhook'
    _order = 'timestamp desc'

    # Campos obrigatórios do webhook
    webhook_type = fields.Char(string='Tipo', default='WEBHOOK_NOTIFY', readonly=True)
    pipeline = fields.Char(string='Pipeline', default='fipe_monthly_load', readonly=True)
    reference_month = fields.Char(
        string='Mês de Referência',
        required=True,
        help='Formato: YYYY-MM (ex: 2026-06)'
    )
    records_total = fields.Integer(string='Total de Registros', required=True)
    timestamp = fields.Datetime(string='Timestamp', readonly=True)
    stage = fields.Selection(
        [('stg', 'Staging'), ('prd', 'Produção')],
        string='Ambiente',
        required=True
    )
    
    # Metadados
    received_at = fields.Datetime(string='Recebido em', default=fields.Datetime.now)
    processed = fields.Boolean(string='Processado?', default=False)
    processed_at = fields.Datetime(string='Processado em')
    error_message = fields.Text(string='Mensagem de Erro')
    
    # Log
    webhook_payload = fields.Text(string='Payload JSON Completo')

    @api.model
    def create(self, vals):
        # Log do webhook recebido
        record = super().create(vals)
        self._process_webhook(record)
        return record

    def _process_webhook(self, record):
        """
        Processa o webhook após recebimento.
        Chamado automaticamente ao criar o registro.
        """
        try:
            # 1. Validar campos obrigatórios
            if not record.reference_month or not record.records_total:
                raise ValueError("reference_month e records_total são obrigatórios")

            # 2. Verificar se já foi processado (idempotência)
            existing = self.search([
                ('reference_month', '=', record.reference_month),
                ('stage', '=', record.stage),
                ('processed', '=', True)
            ])
            if existing:
                record.write({
                    'processed': True,
                    'processed_at': datetime.now(),
                    'error_message': 'Webhook duplicado - já foi processado em ' + existing[0].processed_at.isoformat()
                })
                return

            # 3. Executar ações automáticas
            self._update_product_prices(record)
            self._register_inventory_movement(record)
            self._notify_sales_manager(record)
            self._generate_pricing_report(record)

            # 4. Marcar como processado
            record.write({
                'processed': True,
                'processed_at': datetime.now()
            })

        except Exception as e:
            record.write({
                'error_message': str(e),
                'processed': False
            })
            raise

    def _update_product_prices(self, record):
        """
        Atualiza preços de produtos baseado em tabela FIPE do mês.
        """
        from odoo.addons.fipe_integration.models import fipe_price_fetcher

        product_obj = self.env['product.product']
        
        # Buscar todos os produtos com código FIPE
        products = product_obj.search([
            ('fipe_code', '!=', False),
            ('active', '=', True)
        ])

        for product in products:
            try:
                # Buscar preço FIPE do mês
                price = fipe_price_fetcher.fetch_price(
                    fipe_code=product.fipe_code,
                    reference_month=record.reference_month
                )

                if price:
                    # Atualizar preço com histórico
                    self.env['fipe.price.history'].create({
                        'product_id': product.id,
                        'fipe_price': price,
                        'reference_month': record.reference_month,
                        'changed_from': product.list_price,
                        'changed_to': price,
                        'timestamp': datetime.now()
                    })

                    # Atualizar preço no produto
                    product.write({'list_price': price})

            except Exception as e:
                self.env['ir.logging'].create({
                    'name': 'fipe.webhook.price_update_failed',
                    'type': 'client',
                    'dbname': self.env.cr.dbname,
                    'level': 'WARNING',
                    'message': f"Falha ao atualizar preço para produto {product.id}: {str(e)}"
                })

    def _register_inventory_movement(self, record):
        """
        Registra movimentos de estoque para produtos FIPE.
        """
        stock_move_obj = self.env['stock.move']
        
        products = self.env['product.product'].search([
            ('fipe_code', '!=', False),
            ('active', '=', True)
        ])

        for product in products:
            # Buscar localização de entrada/saída padrão
            location_id = self.env.ref('stock.stock_location_customers').id
            location_dest_id = self.env.ref('stock.stock_location_stock').id

            # Criar movimento de ajuste (simulando reabastecimento)
            stock_move_obj.create({
                'name': f'Ajuste FIPE - {record.reference_month}',
                'product_id': product.id,
                'quantity_done': 0,  # Sem movimento físico, só contábil
                'product_uom': product.uom_id.id,
                'location_id': location_id,
                'location_dest_id': location_dest_id,
                'reference_month': record.reference_month,
                'origin': f'FIPE-{record.reference_month}'
            })

    def _notify_sales_manager(self, record):
        """
        Notifica gestor de vendas sobre atualização de preços FIPE.
        """
        mail_obj = self.env['mail.mail']
        sales_manager = self.env['res.users'].search([('name', '=', 'Gestor de Vendas')], limit=1)

        if sales_manager:
            subject = f"📊 Preços FIPE Atualizados - {record.reference_month} ({record.stage})"
            body = f"""
            <p>Olá <strong>{sales_manager.name}</strong>,</p>
            
            <p>Os preços FIPE foram atualizados com sucesso!</p>
            
            <table border="1" cellpadding="10">
                <tr>
                    <td><strong>Mês de Referência:</strong></td>
                    <td>{record.reference_month}</td>
                </tr>
                <tr>
                    <td><strong>Ambiente:</strong></td>
                    <td>{record.get_stage_display()}</td>
                </tr>
                <tr>
                    <td><strong>Total de Registros:</strong></td>
                    <td>{record.records_total:,}</td>
                </tr>
                <tr>
                    <td><strong>Recebido em:</strong></td>
                    <td>{record.received_at.strftime('%d/%m/%Y %H:%M:%S')}</td>
                </tr>
            </table>
            
            <p>Clique <a href="{self._get_odoo_url()}/web#id={record.id}&model=fipe.webhook.data">aqui</a> 
            para ver detalhes no Odoo.</p>
            
            <p>Atenciosamente,<br/>
            FipeDataStack</p>
            """

            mail_obj.create({
                'subject': subject,
                'body_html': body,
                'email_from': 'noreply@fipe.example.com',
                'email_to': sales_manager.email,
                'auto_delete': False
            }).send()

    def _generate_pricing_report(self, record):
        """
        Gera relatório de preços atualizados.
        """
        report_obj = self.env['ir.attachment']
        
        # Buscar produtos atualizados neste mês
        products = self.env['product.product'].search([
            ('fipe_code', '!=', False),
            ('active', '=', True)
        ])

        # Criar CSV com relatório
        import csv
        from io import StringIO
        
        csv_buffer = StringIO()
        writer = csv.writer(csv_buffer)
        writer.writerow(['Código Interno', 'Código FIPE', 'Nome', 'Preço Anterior', 'Preço Novo', 'Variação %'])
        
        for product in products:
            history = self.env['fipe.price.history'].search([
                ('product_id', '=', product.id),
                ('reference_month', '=', record.reference_month)
            ], limit=1)

            if history:
                variation = ((history.changed_to - history.changed_from) / history.changed_from * 100) if history.changed_from > 0 else 0
                writer.writerow([
                    product.id,
                    product.fipe_code,
                    product.name,
                    f"{history.changed_from:.2f}",
                    f"{history.changed_to:.2f}",
                    f"{variation:.2f}%"
                ])

        # Salvar como anexo
        csv_content = csv_buffer.getvalue().encode('utf-8')
        report_obj.create({
            'name': f'Relatório-FIPE-{record.reference_month}.csv',
            'datas': csv_content,
            'res_model': 'fipe.webhook.data',
            'res_id': record.id,
            'type': 'binary'
        })

    def _get_odoo_url(self):
        """Retorna URL base do Odoo"""
        return self.env['ir.config_parameter'].sudo().get_param('web.base.url')

    def get_stage_display(self):
        """Retorna label do stage"""
        return dict(self.fields_get()['stage']['selection']).get(self.stage, self.stage)
```

## Etapa 3: Criar Controller do Webhook

**Arquivo:** `controllers/webhook_controller.py`

```python
import json
import os
import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

class FipeWebhookController(http.Controller):
    
    def _validate_token(self, received_token):
        """
        Valida o token X-Webhook-Token recebido.
        Suporta 3 opções de configuração.
        """
        # Opção 1: Variável de ambiente
        env_token = os.getenv('FIPE_WEBHOOK_TOKEN')
        if env_token and received_token == env_token:
            return True

        # Opção 2: ir.config.parameter
        config_token = request.env['ir.config_parameter'].sudo().get_param('fipe_webhook.api_token')
        if config_token and received_token == config_token:
            return True

        # Opção 3: Token com expiração
        import json
        from datetime import datetime
        try:
            token_data = json.loads(os.getenv('FIPE_WEBHOOK_TOKEN_DATA', '{}'))
            stored_token = token_data.get('token')
            expires_at = token_data.get('expires_at')
            
            if stored_token and received_token == stored_token:
                if expires_at and datetime.fromisoformat(expires_at) > datetime.now():
                    return True
        except Exception as e:
            _logger.warning(f"Erro ao validar token com expiração: {str(e)}")

        return False

    @http.route('/api/fipe/webhook', type='json', auth='none', methods=['POST'], csrf=False)
    def fipe_webhook_receiver(self):
        """
        Endpoint para receber webhooks do FipeDataStack2.
        
        Headers esperados:
        - Content-Type: application/json
        - X-Webhook-Token: seu-token-secreto
        
        Body esperado:
        {
            "type": "WEBHOOK_NOTIFY",
            "pipeline": "fipe_monthly_load",
            "reference_month": "2026-06",
            "records_total": 45230,
            "timestamp": "2026-06-04T01:15:30Z",
            "stage": "stg"
        }
        """
        try:
            # 1. Validar token no header
            token = request.httprequest.headers.get('X-Webhook-Token')
            if not token:
                _logger.warning("Webhook recebido sem X-Webhook-Token")
                return {'error': 'Missing X-Webhook-Token header'}, 401

            if not self._validate_token(token):
                _logger.warning(f"Webhook recebido com token inválido")
                return {'error': 'Invalid token'}, 401

            # 2. Validar campos obrigatórios
            payload = request.get_json_data()
            
            required_fields = ['reference_month', 'records_total', 'stage']
            for field in required_fields:
                if field not in payload:
                    _logger.warning(f"Webhook sem campo obrigatório: {field}")
                    return {'error': f'Missing field: {field}'}, 400

            # 3. Validar formato de reference_month (YYYY-MM)
            import re
            if not re.match(r'^\d{4}-\d{2}$', payload['reference_month']):
                return {'error': 'Invalid reference_month format. Expected YYYY-MM'}, 400

            # 4. Validar stage
            if payload['stage'] not in ['stg', 'prd']:
                return {'error': 'Invalid stage. Expected stg or prd'}, 400

            # 5. Criar registro com dados do webhook
            webhook_record = request.env['fipe.webhook.data'].create({
                'webhook_type': payload.get('type', 'WEBHOOK_NOTIFY'),
                'pipeline': payload.get('pipeline', 'fipe_monthly_load'),
                'reference_month': payload['reference_month'],
                'records_total': payload['records_total'],
                'timestamp': payload.get('timestamp'),
                'stage': payload['stage'],
                'webhook_payload': json.dumps(payload, indent=2)
            })

            _logger.info(f"Webhook processado com sucesso: {webhook_record.id}")

            return {
                'status': 'received',
                'webhook_id': webhook_record.id,
                'reference_month': payload['reference_month']
            }, 200

        except Exception as e:
            _logger.exception(f"Erro ao processar webhook: {str(e)}")
            return {'error': str(e)}, 500
```

## Etapa 4: Atualizar __manifest__.py

**Arquivo:** `__manifest__.py`

```python
{
    'name': 'Integração FIPE Webhook',
    'version': '19.0.1.0.0',
    'category': 'Tools',
    'depends': [
        'base',
        'sale',
        'stock',
        'web',
        'mail'
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/fipe_webhook_views.xml',
    ],
    'installable': True,
    'auto_install': False,
    'external_dependencies': {
        'python': ['requests'],
    },
}
```

## Etapa 5: Criar Arquivo de Segurança

**Arquivo:** `security/ir.model.access.csv`

```csv
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
access_fipe_webhook_data_user,fipe.webhook.data user,model_fipe_webhook_data,base.group_user,1,0,0,0
access_fipe_webhook_data_admin,fipe.webhook.data admin,model_fipe_webhook_data,base.group_system,1,1,1,1
```

## Etapa 6: Criar Views

**Arquivo:** `views/fipe_webhook_views.xml`

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <data>
        <!-- Tree View -->
        <record id="fipe_webhook_data_tree" model="ir.ui.view">
            <field name="name">fipe.webhook.data.tree</field>
            <field name="model">fipe.webhook.data</field>
            <field name="arch" type="xml">
                <tree>
                    <field name="reference_month"/>
                    <field name="records_total"/>
                    <field name="stage"/>
                    <field name="received_at"/>
                    <field name="processed"/>
                    <field name="error_message"/>
                </tree>
            </field>
        </record>

        <!-- Form View -->
        <record id="fipe_webhook_data_form" model="ir.ui.view">
            <field name="name">fipe.webhook.data.form</field>
            <field name="model">fipe.webhook.data</field>
            <field name="arch" type="xml">
                <form>
                    <header>
                        <field name="processed" widget="boolean_toggle"/>
                    </header>
                    <sheet>
                        <group>
                            <field name="reference_month"/>
                            <field name="stage"/>
                            <field name="records_total"/>
                            <field name="received_at"/>
                            <field name="processed_at"/>
                        </group>
                        <group string="Detalhes">
                            <field name="webhook_type"/>
                            <field name="pipeline"/>
                            <field name="timestamp"/>
                        </group>
                        <field name="webhook_payload" widget="ace" options="{'mode': 'json'}"/>
                        <field name="error_message" widget="html" attrs="{'invisible': [('error_message', '=', False)]}"/>
                    </sheet>
                </form>
            </field>
        </record>

        <!-- Action -->
        <record id="fipe_webhook_data_action" model="ir.actions.act_window">
            <field name="name">Webhooks FIPE</field>
            <field name="res_model">fipe.webhook.data</field>
            <field name="view_mode">tree,form</field>
            <field name="view_ids" eval="[(5, 0, 0), (0, 0, {'view_mode': 'tree', 'view_id': ref('fipe_webhook_data_tree')}), (0, 0, {'view_mode': 'form', 'view_id': ref('fipe_webhook_data_form')})]"/>
        </record>

        <!-- Menu -->
        <menuitem id="fipe_webhook_menu" name="Webhooks FIPE" parent="base.menu_tools" action="fipe_webhook_data_action"/>
    </data>
</odoo>
```

## Testar a Integração

### 1. Instalar Módulo no Odoo

```bash
# Via CLI
odoo-bin -c /path/to/odoo.conf -d seu_database -i fipe_integration

# Ou via interface: Apps > Instalar
```

### 2. Configurar Token

```bash
# Defina a variável de ambiente ou configure via ir.config_parameter
export FIPE_WEBHOOK_TOKEN="seu-token-secreto-odoo"
```

### 3. Adicionar URL ao Parameter Store AWS

```bash
# Obter config STG
aws ssm get-parameter \
  --name /fipe/webhooks/stg \
  --query 'Parameter.Value' \
  --output text \
  --region us-east-2 > webhooks.json

# Editar e adicionar:
cat webhooks.json | jq '.webhooks += [
  {
    "name": "odoo-stg",
    "url": "https://seu-odoo-stg.example.com/api/fipe/webhook",
    "api_key": "seu-token-secreto-odoo"
  }
]' > webhooks_updated.json

# Atualizar Parameter Store
aws ssm put-parameter \
  --name /fipe/webhooks/stg \
  --value file://webhooks_updated.json \
  --overwrite \
  --type String \
  --region us-east-2
```

### 4. Testar Manualmente

```bash
curl -X POST https://seu-odoo-stg.example.com/api/fipe/webhook \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Token: seu-token-secreto-odoo" \
  -d '{
    "type": "WEBHOOK_NOTIFY",
    "pipeline": "fipe_monthly_load",
    "reference_month": "2026-06",
    "records_total": 45230,
    "timestamp": "2026-06-04T01:15:30Z",
    "stage": "stg"
  }'
```

**Resposta esperada:**
```json
{
  "status": "received",
  "webhook_id": 123,
  "reference_month": "2026-06"
}
```

## Monitoramento

### Via Odoo

1. Acesse: **Tools > Webhooks FIPE**
2. Veja lista de webhooks recebidos
3. Clique para ver detalhes e logs de processamento

### Via CloudWatch

```bash
aws logs tail /aws/lambda/FipeSomaNotifier-stg --follow --region us-east-2
```

## FAQ

**P: E se o webhook falhar no Odoo?**
R: O FipeDataStack tentará novamente até 5 vezes com backoff exponencial. Verifique logs e corrija a configuração.

**P: O token pode expirar?**
R: Sim, se usar a Opção 3. Atualize a configuração antes da expiração para evitar falhas.

**P: Posso ter múltiplas instâncias do Odoo recebendo webhooks?**
R: Sim! Registre múltiplas URLs no Parameter Store, uma para cada instância.

**P: Os dados históricos de preços são mantidos?**
R: Sim. O modelo `fipe.price.history` mantém um registro de todas as mudanças.
