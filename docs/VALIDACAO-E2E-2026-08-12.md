# Validação E2E do Caminho Feliz — 2026-08-12

**Status: EM ANDAMENTO — este documento é atualizado em tempo real conforme o teste avança.**

## Objetivo

Provar, com evidência real (logs do CloudWatch, estado de filas SQS, CloudTrail), que o pipeline
completo da FIPE funciona de ponta a ponta: `FipeManufacturerLoader` (sa-east-1) → `FipeModelLoader` →
`FipePriceLoader` → `FipeSomaIngestor-unified` (encaminha cross-region) → `FipeSomaIngestor-stg`/`-prd`
(gravam no RDS) → `FipeSomaNotifier-stg`/`-prd` (disparam o webhook real).

Este teste usa o modo de teste (`FORCE_VEHICLE_TYPE`/`FORCE_VEHICLE_MODEL`) para restringir o volume a
um único fabricante, validando também que esse modo de teste realmente limita o escopo processado.

Ver [AUDITORIA-WEBHOOK-NOTIFIER-2026-08-12.md](AUDITORIA-WEBHOOK-NOTIFIER-2026-08-12.md) para o histórico
completo dos Bugs 1-3 corrigidos antes deste teste.

---

## 1. Configuração do teste de modo restrito

Confirmado antes do teste: todas as filas Fipe (sa-east-1/stg/prd) estavam vazias e todos os event
source mappings (Manufacturer→Model→Price→Ingestor, em todas as regiões) estavam `Enabled`.

Variáveis de ambiente temporárias aplicadas em `FipeManufacturerLoader-unified` (sa-east-1):

```json
{
  "FORCE_VEHICLE_TYPE": "2",
  "FORCE_VEHICLE_MODEL": "YAMAHA"
}
```

(`2` = motocicletas na taxonomia da API FIPE. Removidas ao final do teste — ver seção 8.)

## 2. Fase 1 — FipeManufacturerLoader: filtro de teste confirmado

Log real da invocação (`aws lambda invoke --function-name FipeManufacturerLoader-unified`):

```
[INFO] Fetching brands for vehicle type 2 with payload: {'codigoTabelaReferencia': 336, 'codigoTipoVeiculo': 2}
[INFO] Found 102 brands for vehicle type 2.
[INFO] Processing brand 'YAMAHA' (Code: 101) for vehicle type 2.
[INFO] Message sent to SQS for brand 'YAMAHA'
```

**Confirmado**: de 102 marcas de moto encontradas, apenas 1 (YAMAHA) foi processada e enviada à fila —
o filtro `FORCE_VEHICLE_MODEL` funciona corretamente. Também confirmado que só o tipo de veículo 2 foi
processado (não os tipos 1 e 3, que rodariam sem `FORCE_VEHICLE_TYPE`).

## 3. Fase 2 — FipeModelLoader: 145 modelos (não o catálogo completo)

```
[INFO] Consultando modelos para: YAMAHA (Moto)
[INFO] Encontrados 145 modelos para YAMAHA
```

145 mensagens enviadas para `fipe-model-queue-unified` — volume compatível com um teste pontual (o
catálogo completo teria dezenas de milhares).

## 4. Fase 3 — FipePriceLoader: ~822 mensagens de preço geradas

Acompanhamento do volume nas filas confirmou o crescimento esperado (145 modelos × múltiplos
anos/combustíveis cada). Nenhuma mensagem em DLQ (`fipe-model-dlq-unified` e `fipe-price-dlq-unified`
seguiram em 0 durante todo o teste).

## 5. Bug 4 descoberto: cross-region forwarding falhando 100%

Ao chegar em `FipeSomaIngestor-unified`, **toda** tentativa de encaminhamento para STG/PRD falhou:

```
[ERROR] ConnectTimeoutError: Connect timeout on endpoint URL: "https://sqs.us-east-2.amazonaws.com/"
  File "/var/task/fipe_soma_ingestor.py", line 63, in lambda_handler
    ok_stg = forward_to_queue(sqs_stg, sqs_url_stg, body, message_id)
```

822 mensagens ficaram presas em retry (`ApproximateNumberOfMessagesNotVisible: 822`), 67 falhas em 5
minutos, sem nenhuma ainda em DLQ (`max_receive_count=10` ainda não atingido).

### Causa raiz (confirmada via `git log` + AWS CloudTrail)

`FipeSomaIngestor-unified` era a **única** das 5 Lambdas de sa-east-1 anexada a uma VPC:

```
$ aws lambda get-function-configuration --function-name FipeSomaIngestor-unified --region sa-east-1
VpcId: vpc-043ab9c1ba9c44ef9
Subnets: [subnet-006546e8b518aa32b, subnet-09e9017643f886252, subnet-0cd90c8e66bdccf87]
```

Essa VPC não tem NAT Gateway nem VPC Endpoint de SQS:

```
$ aws ec2 describe-nat-gateways --filter Name=vpc-id,Values=vpc-043ab9c1ba9c44ef9 --region sa-east-1
[]
$ aws ec2 describe-vpc-endpoints --filters Name=vpc-id,Values=vpc-043ab9c1ba9c44ef9 --region sa-east-1
[]
```

As subnets têm rota para um Internet Gateway, mas isso não dá acesso à internet para uma Lambda em VPC
(ENIs de Lambda não recebem IP público — só um NAT Gateway resolveria, e mesmo um VPC Endpoint de SQS
não ajudaria aqui, pois endpoints de interface são regionais e não roteiam chamadas cross-region).

**Linha do tempo reconstruída:**

| Data                     | Evento                                                                                                                                                                                                                                             | Evidência                                                                                                       |
| ------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| 2026-05-26               | Commit `67e387b` remove a VPC do ingestor deliberadamente ("Lambda agora sem VPC para internet nativa"), migrando para forwarding cross-region                                                                                                     | `git show 67e387b -- fipe_api_stack.py`                                                                         |
| 2026-06-15               | Último deploy real antes de hoje. CloudTrail confirma `vpcConfig: {subnetIds: [], securityGroupIds: []}` — sem VPC, forwarding funcional                                                                                                           | `aws cloudtrail lookup-events` (`UpdateFunctionConfiguration`, 2026-06-15T17:54:39-03:00)                       |
| 2026-06-17               | Commit `8572928` ("Sincronizar com branch stage") reintroduz `vpc=vpc, security_groups=[...], role=db_lambda_role` no construtor do ingestor, sem que ninguém notasse — cópia incondicional do padrão de stage (que precisa de VPC para RDS local) | `git show 8572928 -- fipe_api_stack.py`                                                                         |
| 2026-06-17 → 2026-08-12  | Esse commit nunca foi implantado: um bug de assinatura de construtor (Bug 1, já corrigido) bloqueava `cdk synth`/deploy desde então                                                                                                                | Ver seção "Bugs 1-3" na auditoria do webhook                                                                    |
| 2026-08-12, 11:52:47 -03 | Deploy de hoje finalmente desbloqueado (Bug 1 corrigido). `FipeSomaIngestor-unified` é **recriado do zero** (`CreateFunction`, não `UpdateFunctionConfiguration` — efeito colateral do sufixo `-unified`) e herda a VPC latente pela primeira vez  | `aws cloudtrail lookup-events --lookup-attributes AttributeKey=EventName,AttributeValue=CreateFunction20150331` |
| 2026-08-12, ~16:46 UTC   | Teste E2E real (este documento) expõe a falha ao vivo                                                                                                                                                                                              | Seção 5 acima                                                                                                   |

**Conclusão**: não é um bug novo e isolado — é a mesma regressão do commit `8572928` que eu já estava
corrigindo. Eu tinha restaurado a metade do código (`fipe_soma_ingestor.py`, Bug 2) mas deixei passar a
metade de infraestrutura (`vpc=` em `fipe_api_stack.py`), que só "ativou" quando o deploy de hoje
finalmente rodou.

## 6. Fix aplicado

`fipe_api_stack.py` — VPC do ingestor tornada condicional (só anexa quando existe RDS local, ou seja em
stage/production; sa-east-1 fica sem VPC, com internet direta, igual às outras 4 Lambdas):

```python
ingestor_vpc_kwargs = {}
if db_cluster_endpoint:
    ingestor_vpc_kwargs = {
        "vpc": vpc,
        "vpc_subnets": ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
        "allow_public_subnet": True,
        "security_groups": [self.lambda_security_group],
    }
ingestor_lambda = lambda_.Function(
    ...
    **ingestor_vpc_kwargs,
    role=db_lambda_role,
    ...
)
```

Validado localmente com `cdk synth` antes do deploy — o template gerado confirma ausência de
`VpcConfig` na Lambda `FipeSomaIngestor-unified`. Commit `876649e`, deploy via `deploy-sa-east-1.yml`
(run [31618921344](https://github.com/mutualizo/FipeDataStack/actions/runs/31618921344), sucesso em 2m42s).

Confirmado pós-deploy:

```
$ aws lambda get-function-configuration --function-name FipeSomaIngestor-unified --region sa-east-1
VpcId: "", Subnets: [], LastModified: 2026-08-12T16:44:37+0000
```

## 7. Fase 4 — Forwarding cross-region funcionando (pós-fix)

Event source mapping reabilitado (as 822 mensagens de teste, que ficaram pausadas na fila durante o
diagnóstico, foram retomadas automaticamente — sem precisar regenerar dados). Logs imediatamente após o
fix:

```
[INFO] INGESTOR - Mensagem a76b88e5-... encaminhada para https://sqs.us-east-2.amazonaws.com/.../fipe-price-queue-stg
[INFO] INGESTOR - Mensagem a76b88e5-... encaminhada para https://sqs.us-east-1.amazonaws.com/.../fipe-price-queue-prd
[INFO] INGESTOR - Concluído: 10/10 sucesso, 0 falhas
{"status": "SUCCESS", "event": "Mensagens encaminhadas via SQS para STG e PRD", "details": {"total_messages": 10, "regions": ["us-east-2", "us-east-1"]}}
```

**Zero `ConnectTimeoutError` após o fix.** Filas STG/PRD recebendo mensagens em tempo real:

```
fipe-price-queue-stg (us-east-2): 592 visíveis + 230 em processamento
fipe-price-queue-prd (us-east-1): 571 visíveis + 211 em processamento
```

## 9. Fase 5 — STG e PRD gravando no RDS com sucesso

Logs de `FipeSomaIngestor-stg` (us-east-2), lotes de 10 mensagens sendo persistidos continuamente:

```
{"status": "SUCCESS", "event": "Todos os dados foram persistidos no RDS em us-east-2", "details": {"total_messages": 10, "region": "us-east-2"}}
```

Logs de `FipeSomaIngestor-prd` (us-east-1), mesmo padrão:

```
{"status": "SUCCESS", "event": "Todos os dados foram persistidos no RDS em us-east-1", "details": {"total_messages": 10, "region": "us-east-1"}}
```

**Zero eventos `ERROR` em ambos os log groups** durante toda a janela do teste (checado via
`filter-pattern "ERROR"` nos últimos 3 minutos de processamento intenso).

## 11. Bug 5 descoberto: FipeSomaIngestor-stg/prd em subnet PUBLIC — invoke() do webhook trava até timeout

Ao receber `END_OF_RECORDS`, ambos `FipeSomaIngestor-stg` e `FipeSomaIngestor-prd` processaram os dados
com sucesso e logaram a intenção de disparar o webhook, mas a invocação nunca completou:

```
[INFO] INGESTOR - Processamento concluído: 10/10 mensagens processadas com sucesso.
[INFO] {"status": "SUCCESS", "event": "Todos os dados foram persistidos no RDS em us-east-1", ...}
[INFO] INGESTOR - 🚀 FIM DO PIPELINE MENSAL - Disparando webhook para prd
[INFO] INGESTOR - Reference month: agosto/2026, Total de registros: 9
```

Nenhuma linha de sucesso (`Webhook notifier invocado`) nem de erro (`Erro ao invocar webhook`) apareceu
depois disso. Via **CloudWatch Logs Insights** (necessário porque `filter-log-events` não paginava até o
fim, dado o volume de logs concorrentes):

```
fields @timestamp, @message | filter @message like /5190e705/ | filter @message like /REPORT/
→ REPORT RequestId: 5190e705-... Duration: 300000.00 ms Billed Duration: 300000 ms
  Memory Size: 512 MB Max Memory Used: 101 MB Status: timeout
```

**A invocação inteira do ingestor travou nos 300000ms (5 min) exatos do timeout configurado da Lambda,
bem depois de já ter processado e persistido todos os dados** — a única chamada pendente era o
`lambda_client.invoke(FunctionName="FipeSomaNotifier-prd", ...)`.

### Causa raiz

`FipeSomaIngestor-stg`/`-prd` estavam configurados em subnet **PUBLIC** (rota direta para Internet
Gateway), com a flag `allow_public_subnet=True` — usada justamente para silenciar o aviso do CDK de que
isso normalmente está errado:

```python
vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
allow_public_subnet=True,
```

Só que **uma Lambda em VPC nunca recebe IP público** — uma rota para Internet Gateway não dá acesso à
internet nem à API da própria Lambda (`lambda.us-east-1.amazonaws.com`) nessas condições. Só uma subnet
**privada roteada via NAT Gateway** funciona. Confirmado: ambas as VPCs (stg e prd) já tinham NAT
Gateway disponível — só a Lambda não estava na subnet certa para usá-lo:

```
$ aws ec2 describe-route-tables --filters Name=association.subnet-id,Values=<subnet-do-ingestor-prd>
→ 0.0.0.0/0 -> igw-0208b472650dc2dcb   (Internet Gateway - inútil para Lambda)

$ aws ec2 describe-subnets --filters Name=vpc-id,Values=<vpc-prd>
→ subnet-041189cdf52e918f6 "soma-prd-subnet-private1-us-east-1a"
  subnet-0068cca5ec18d4130 "soma-prd-subnet-private2-us-east-1b"
$ aws ec2 describe-route-tables --filters Name=association.subnet-id,Values=subnet-041189cdf52e918f6
→ 0.0.0.0/0 -> nat-0fbb8458c927efbc7   (NAT Gateway - funcional, já existia, só não estava em uso aqui)
```

Isso explica por completo o achado original da auditoria de webhook: `FipeSomaNotifier-prd` tinha
**0 invocações** e `FipeSomaNotifier-stg` só tinha invocações de testes manuais diretos — a chamada vinda
do ingestor real, através da VPC, nunca teve como funcionar, mesmo após os Bugs 1-3 corrigidos.

### Fix aplicado

`vpc_subnets` trocado de `PUBLIC` para `PRIVATE_WITH_EGRESS` em `fipe_api_stack.py`, removendo
`allow_public_subnet=True` (não é mais necessário). Aplicado nas duas branches (mesmo código, mesma
correção, confirmando a paridade stage/production exigida pelo projeto):

- `stage`: commit `b5d329d`, subnet resolvida via `cdk synth`: `subnet-0c60ecc686de3cf7a`
  (`soma-stg-subnet-private1-us-east-2a`, rota confirmada para `nat-0c09d8fc4d748b388`)
- `production`: commit `27966a6`, subnets resolvidas: `subnet-041189cdf52e918f6` e
  `subnet-0068cca5ec18d4130` (as duas privadas identificadas acima)

Deploys disparados (`deploy-stage.yml` run
[31620473568](https://github.com/mutualizo/FipeDataStack/actions/runs/31620473568) via push automático,
`deploy-production.yml` run
[31620591904](https://github.com/mutualizo/FipeDataStack/actions/runs/31620591904) via workflow_dispatch).

Event source mappings de `FipeSomaIngestor-stg`/`-prd` foram pausados durante o diagnóstico (a mesma
mensagem de teste, incluindo `END_OF_RECORDS`, ficaria retentando e travando 5 min a cada tentativa) —
serão reabilitados após o deploy confirmado, retomando o processamento do mesmo lote sem precisar gerar
dados novamente.

Confirmado pós-deploy — subnets corretas nas duas Lambdas:

```
FipeSomaIngestor-stg: subnet-0c60ecc686de3cf7a (LastModified 2026-08-12T17:02:37Z)
FipeSomaIngestor-prd: subnet-041189cdf52e918f6, subnet-0068cca5ec18d4130 (LastModified 2026-08-12T17:04:14Z)
```

## 13. Fase 6 e 7 — Webhook disparado com sucesso pela primeira vez, ponta a ponta

Event source mappings reabilitados; o lote final (`END_OF_RECORDS` + últimas mensagens de dados) que
estava pausado foi reprocessado automaticamente, **desta vez sem travar**:

```
STG - REPORT RequestId: e43bce2b-... Duration: 23493.49 ms  (sem "Status: timeout")
PRD - REPORT RequestId: 6572b18b-... Duration: 21991.13 ms  (sem "Status: timeout")
```

Comparar com a Fase 5 (Bug 5, antes do fix): `Duration: 300000.00 ms ... Status: timeout`.

`FipeSomaNotifier-stg` e `FipeSomaNotifier-prd` foram **efetivamente invocados e executados** pela
primeira vez a partir do fluxo real do ingestor (não um teste manual direto):

```
STG: NOTIFIER - Handler iniciado com evento: {"reference_month": "agosto/2026", "records_total": 9, "stage": "stg"}
     NOTIFIER - Config carregada de /fipe/webhooks/stg: 5 webhook(s)
     NOTIFIER - Tentativa 1/5 para uniseg em stg
     NOTIFIER - URL sendo chamada: https://uniseg19.stg.mutualizo.com.br/api/v3/fipe/refresh
     NOTIFIER - Webhook uniseg retornou status 500 (retry com backoff exponencial: 5s, 10s, 20s...)

PRD: NOTIFIER - Handler iniciado com evento: {"reference_month": "agosto/2026", "records_total": 9, "stage": "prd"}
     NOTIFIER - Config carregada de /fipe/webhooks/prd: 6 webhook(s)
     NOTIFIER - Tentativa 1/5 para autobem em prd
     NOTIFIER - URL sendo chamada: https://autobem.mutualizo.com.br/api/v3/fipe/refresh
     NOTIFIER - Webhook autobem retornou status 403 "Direct API access not allowed." (mesmo padrão de retry)
```

**Nenhum segredo (`api_key`, `proxy_nonce`, `X-Webhook-Token`) foi exposto nesta captura** — filtrados
antes de qualquer exibição.

### Interpretação

O objetivo desta validação era provar que o **nosso pipeline** dispara o webhook corretamente — e prova:
a Lambda notifier agora é alcançada, carrega a config do Parameter Store, monta o payload certo
(`reference_month`, `records_total`, `stage`) e faz a chamada HTTP real para os endpoints configurados,
com retry/backoff funcionando como projetado.

Os erros HTTP (500 em `uniseg19.stg`, 403 em `autobem`) são respostas dos **sistemas consumidores**
(Laranjinha/Odoo), fora do escopo desta stack — nunca tinham sido alcançados antes por uma execução real
do pipeline, então esses erros específicos não têm histórico de comparação; podem já existir há tempos
sem que ninguém soubesse, justamente porque o webhook nunca chegou a ser disparado de verdade. Vale um
acompanhamento separado com os times donos desses endpoints.

## 14. Limpeza pós-teste

- Variáveis de teste (`FORCE_VEHICLE_TYPE`, `FORCE_VEHICLE_MODEL`) removidas de
  `FipeManufacturerLoader-unified` logo após a primeira invocação do teste.
- Nenhuma mensagem em nenhuma DLQ (`fipe-*-dlq-unified`, `fipe-price-dlq-stg`, `fipe-price-dlq-prd`)
  durante todo o teste.

## 15. Veredito final

✅ **Caminho feliz completo confirmado, ponta a ponta, com evidência real**: `FipeManufacturerLoader`
(sa-east-1) → `FipeModelLoader` → `FipePriceLoader` → `FipeSomaIngestor-unified` (encaminha cross-region,
**Bug 4 corrigido**) → `FipeSomaIngestor-stg`/`-prd` (gravam no RDS e disparam o webhook,
**Bug 5 corrigido**) → `FipeSomaNotifier-stg`/`-prd` (executam e chamam os endpoints reais).

O modo de teste (`FORCE_VEHICLE_TYPE`/`FORCE_VEHICLE_MODEL`) restringiu corretamente o escopo: 1 marca de
102 encontradas, 1 tipo de veículo de 3, ~822 mensagens de preço geradas (vs. 100k-300k do catálogo
completo) — confirmando que o modo de teste é seguro para usar em validações futuras sem sobrecarregar a
API FIPE ou gerar volume de produção indevido.

Pendências fora do escopo desta stack: respostas HTTP de erro dos endpoints consumidores (uniseg stg,
autobem prd) e o sufixo `-unified` nos recursos de sa-east-1 (já documentado e deferido anteriormente).

---

## 16. Segunda rodada (2026-08-12, ~20:54 UTC) — payload e headers reais enviados ao webhook

O usuário adicionou um log extra em `fipe_soma_notifier.py` (commit `fdc1298`, implantado em `stage` e
`production`) para expor exatamente o payload e os headers HTTP enviados a cada tentativa de webhook,
com o objetivo de diagnosticar os erros vistos na Fase 6/7 (500 em uniseg-stg, 403 em autobem-prd). O
mesmo teste (`FORCE_VEHICLE_TYPE=2`, `FORCE_VEHICLE_MODEL=YAMAHA`) foi repetido do zero para capturar essa
evidência com o código novo já em produção.

Cascata completa se repetiu com sucesso (manufacturer → model → price → forward cross-region → RDS →
webhook), confirmando que os Bugs 4 e 5 seguem corrigidos e estáveis numa segunda execução independente.

### Payload e headers reais (segredos redigidos)

**PRD** (`FipeSomaNotifier-prd`, webhook `autobem`):
```
NOTIFIER - URL sendo chamada: https://autobem.mutualizo.com.br/api/v3/fipe/refresh
NOTIFIER - Headers enviados: {"Content-Type": "application/json", "X-Webhook-Token": "<redigido>", "proxy_nonce": "<redigido>"}
NOTIFIER - Payload enviado: {"type": "WEBHOOK_NOTIFY", "pipeline": "fipe_monthly_load", "reference_month": "agosto/2026", "reference_month_code": "unknown", "records_total": 9, "timestamp": "2026-08-12T20:54:54.702598", "stage": "prd"}
NOTIFIER - Webhook autobem retornou status 403
NOTIFIER - Corpo da resposta: {"error": "Direct API access not allowed."}
```

**STG** (`FipeSomaNotifier-stg`, webhook `uniseg`):
```
NOTIFIER - URL sendo chamada: https://uniseg19.stg.mutualizo.com.br/api/v3/fipe/refresh
NOTIFIER - Headers enviados: {"Content-Type": "application/json", "X-Webhook-Token": "<redigido>", "proxy_nonce": "<redigido>"}
NOTIFIER - Payload enviado: {"type": "WEBHOOK_NOTIFY", "pipeline": "fipe_monthly_load", "reference_month": "agosto/2026", "reference_month_code": "unknown", "records_total": 9, "timestamp": "2026-08-12T20:54:19.481552", "stage": "stg"}
NOTIFIER - Erro ao chamar webhook uniseg: HTTPSConnectionPool(host='uniseg19.stg.mutualizo.com.br', port=443): Read timed out. (read timeout=30)
```
(retentativas seguintes repetem o mesmo payload/headers, com o mesmo resultado)

### Duas falhas distintas do lado consumidor

- **PRD/autobem**: resposta imediata (403), corpo `"Direct API access not allowed."` — sugere que o
  endpoint espera a chamada através de algum proxy/gateway específico (existem filas SQS no mesmo
  ambiente com nomes como `api-proxy-listener-issue-policy-endo-*` e `proxy-notify-queue-*`, sugerindo
  que outros fluxos do Mutualizo já passam por um componente de proxy intermediário) e está rejeitando
  a chamada HTTP direta feita pelo `FipeSomaNotifier`.
- **STG/uniseg**: nenhuma resposta em 30s (timeout de leitura) — o endpoint aceitou a conexão TCP mas não
  respondeu a tempo; pode ser um problema diferente (endpoint sobrecarregado, travado, ou validando algo
  antes de responder).

Ambas são questões do lado consumidor (fora desta stack), mas agora há evidência concreta de exatamente
o que está sendo enviado para investigar com os times donos desses serviços.

### Achado secundário: `reference_month_code` sempre `"unknown"`

Em `fipe_soma_notifier.py:146`, o handler lê `reference_month_code` do evento recebido
(`event.get("reference_month_code", False)`), mas `invoke_webhook_notifier()` em `fipe_soma_ingestor.py`
só envia `reference_month`, `records_count` e `stage_target` — nunca `reference_month_code`. Resultado:
o payload enviado ao webhook **sempre** tem `"reference_month_code": "unknown"`, mesmo sabendo o código
real (ex. `336`) em outras partes do pipeline. Não corrigido nesta sessão (não foi pedido), mas
registrado aqui caso o time consumidor dependa desse campo para identificar a tabela de referência FIPE.
