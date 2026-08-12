# Auditoria: Disparo do Webhook Notifier (FipeSomaNotifier) no Pipeline Fipe

**Data da auditoria:** 2026-08-12
**Autor:** Investigação assistida (Claude Code), com evidências coletadas diretamente da AWS (conta `652510808251`, perfil `mutualizo`)
**Pergunta a responder:** A Lambda de webhook notifier (`FipeSomaNotifier`) é realmente acionada toda vez que o "caminho feliz" do pipeline Fipe termina (coleta → filas → RDS → notificação)?

> ## ✅ Status: correções aplicadas em 2026-08-12 (mesmo dia da auditoria)
> Ver seção **"Correção Aplicada"** ao final deste documento para o que foi corrigido, incluindo **dois bugs adicionais e mais graves** descobertos durante a tentativa de corrigir o problema original — um deles teria quebrado o pipeline de coleta inteiro (não só o webhook) se eu não tivesse validado antes de aplicar.

---

## Veredito

**Não.** Hoje, em produção, o webhook notifier **nunca é acionado pelo pipeline real** — nem em STG, nem em PRD. `FipeSomaNotifier-prd` tem **zero invocações desde que existe**. As poucas invocações de `FipeSomaNotifier-stg` que existem nos logs são **chamadas manuais de teste** feitas durante o desenvolvimento da Melhoria 4, não disparos orgânicos do pipeline.

**Causa raiz identificada e comprovada:** o código que envia a mensagem `END_OF_RECORDS` (sinal de "pipeline terminou") só existe no repositório desde o commit `8572928` (17/06/2026). A Lambda `FipeManufacturerLoader` em `sa-east-1` — a única que pode gerar esse sinal, já que é o único ponto de entrada do pipeline — está rodando um deploy de **15/06/2026, dois dias antes desse commit**. Ou seja: **o código que dispara a cascata do webhook nunca foi implantado em `sa-east-1`.** Toda execução real do pipeline desde então termina silenciosamente sem nunca enviar o sinal que as Lambdas seguintes (`FipeSomaIngestor-stg`/`-prd`) esperam para acionar `FipeSomaNotifier`.

O restante deste documento mostra a evidência, ponto a ponto.

---

## 1. Auditoria de código: o que está no repositório vs. o que está implantado

### 1.1 `FipeManufacturerLoader` (sa-east-1) — quem deveria criar o sinal `END_OF_RECORDS`

**Código atual no repositório** (`code_lambdas/src/fipe_api/fipe_manufacturer_loader.py`, branch `multi-region-sa-east-1`):

```python
    logger.info("Processing completed for all vehicle types.")

    # Enviar mensagem END_OF_RECORDS para sinalizar fim do pipeline mensal
    if not is_local and queue_url:
        end_of_records_message = {
            "type": "END_OF_RECORDS",
            "reference_month": fipe_api.reference_month_name,
            "reference_month_code": fipe_api.reference_table_code,
            "records_count": 0,  # Será contado em cada etapa
            "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        }
        fipe_api.send_message_sqs(queue_url, end_of_records_message)
        logger.info(f"END_OF_RECORDS enviado para sinalizar fim do processamento mensal: {fipe_api.reference_month_name}")
```

**Código realmente implantado** na função `FipeManufacturerLoader` em `sa-east-1` (baixado diretamente via `aws lambda get-function`, `LastModified: 2026-06-15T20:54:45Z`):

```python
    return {
        'statusCode': 200,
        'body': 'Processing completed successfully!',
        'message_count': len(local_messages) if is_local else None
    }

def lambda_handler(event, context):
    ...
```

O arquivo implantado **termina no `return`** — não existe nenhum bloco de envio de `END_OF_RECORDS`. `diff` completo entre os dois:

```diff
144a139,151
> 
>     # Enviar mensagem END_OF_RECORDS para sinalizar fim do pipeline mensal
>     if not is_local and queue_url:
>         end_of_records_message = {
>             "type": "END_OF_RECORDS",
>             "reference_month": fipe_api.reference_month_name,
>             "reference_month_code": fipe_api.reference_table_code,
>             "records_count": 0,  # Será contado em cada etapa
>             "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
>         }
>         fipe_api.send_message_sqs(queue_url, end_of_records_message)
>         logger.info(f"END_OF_RECORDS enviado para sinalizar fim do processamento mensal: {fipe_api.reference_month_name}")
```

(o `>` marca linhas que existem no repositório e **não** existem no que está implantado)

### 1.2 `FipeSomaIngestor` (sa-east-1) — quem deveria disparar o notifier

**Código atual no repositório** — função que dispara o notifier:

```python
def invoke_webhook_notifier(reference_month, records_count, stage_target):
    """
    Invoca a Lambda FipeSomaNotifier para disparar webhooks após sucesso do pipeline.
    """
    try:
        payload = {
            "reference_month": reference_month,
            "records_total": records_count,
            "stage": stage_target
        }
        lambda_client.invoke(
            FunctionName=f"FipeSomaNotifier-{stage_target}",
            InvocationType="Event",
            Payload=json.dumps(payload)
        )
        logger.info(f"INGESTOR - Webhook notifier invocado para stage={stage_target}, reference_month={reference_month}")
    except Exception as e:
        logger.error(f"INGESTOR - Erro ao invocar webhook notifier ({stage_target}): {str(e)}")
```

E a condição que a chama, dentro do `lambda_handler`:

```python
    # ⚠️ WEBHOOK DISPARA APENAS QUANDO END_OF_RECORDS É RECEBIDO
    if end_of_records_received and reference_month and records_processed > 0 and total_failures == 0:
        logger.info(f"INGESTOR - 🚀 FIM DO PIPELINE MENSAL - Disparando webhooks para STG e PRD")
        invoke_webhook_notifier(reference_month, records_processed, "stg")
        invoke_webhook_notifier(reference_month, records_processed, "prd")
    elif end_of_records_received and total_failures > 0:
        logger.warning(f"INGESTOR - END_OF_RECORDS recebido, mas houve {total_failures} falhas no processamento")
    elif not end_of_records_received:
        logger.info(f"INGESTOR - END_OF_RECORDS não recebido ainda (pipeline ainda em andamento)")
```

**Código realmente implantado** na função `FipeSomaIngestor` em `sa-east-1` (mesmo deploy de 15/06/2026) é uma versão **muito mais simples**, que só encaminha cada mensagem via SQS — sem nenhuma menção a `END_OF_RECORDS` ou `invoke_webhook_notifier`:

```python
def lambda_handler(event, context):
    ...
    for record in records:
        message_id = record["messageId"]
        body = record["body"]
        ok_stg = forward_to_queue(sqs_stg, sqs_url_stg, body, message_id)
        ok_prd = forward_to_queue(sqs_prd, sqs_url_prd, body, message_id)
        if not ok_stg or not ok_prd:
            batch_item_failures.append({"itemIdentifier": message_id})
    ...
    return {"batchItemFailures": batch_item_failures}
```

Confirmado por busca direta no artefato baixado:
```
$ grep -c "END_OF_RECORDS\|invoke_webhook_notifier" fipe_soma_ingestor.py   (implantado em sa-east-1)
0
```

### 1.3 Tabela de defasagem código-vs-deploy (todas as funções relevantes)

| Função | Região | Último deploy | Tem `END_OF_RECORDS`? | Tem `invoke_webhook_notifier`? |
|---|---|---|---|---|
| `FipeManufacturerLoader` | sa-east-1 | 2026-06-15 20:54 UTC | ❌ Não | — |
| `FipeSomaIngestor` | sa-east-1 | 2026-06-15 20:54 UTC | ❌ Não | ❌ Não |
| `FipeSomaIngestor-stg` | us-east-2 | (redeploy automático em 2026-08-12, ver nota¹) | ✅ Sim | ✅ Sim |
| `FipeSomaIngestor-prd` | us-east-1 | 2026-06-18 18:54 UTC | ✅ Sim | ✅ Sim |
| `FipeSomaNotifier-stg` | us-east-2 | (redeploy automático em 2026-08-12, ver nota¹) | — | — |
| `FipeSomaNotifier-prd` | us-east-1 | 2026-06-18 18:54 UTC | — | — |

¹ *`deploy-stage.yml` dispara automaticamente a cada push na branch `stage`. Durante esta mesma sessão de auditoria, dois commits de limpeza de repositório (não relacionados a lógica de negócio) foram enviados para `stage`, o que re-implantou essas duas funções com o mesmo conteúdo de código já vigente — só atualizou o timestamp, não a lógica.*

**Conclusão da Parte 1:** mesmo que `FipeSomaIngestor-stg`/`-prd` estejam com o código certo para reagir a um `END_OF_RECORDS` e chamar `FipeSomaNotifier`, isso é irrelevante enquanto `sa-east-1` — o único lugar que pode gerar esse sinal — continuar rodando uma versão de código anterior a essa funcionalidade.

---

## 2. Rastro de execução real: o pipeline "morre" exatamente onde o código previa

Foram identificadas duas execuções reais e completas (sem filtro `FORCE_VEHICLE_MODEL`, processando todas as marcas de carro/moto/caminhão) nos últimos dias:

- **01/08/2026, 06:00:37 UTC** — disparo **automático** (bate exatamente com a regra EventBridge, ver seção 5)
- **03/08/2026, 13:39:22 UTC** — disparo **manual** (`aws lambda invoke`)

### 2.1 Execução de 03/08/2026 (RequestId `85be10fd-7b5b-4602-adff-f00e062aed8d`)

```
13:39:22.439Z  {"status": "START", "event": "Pipeline iniciado em sa-east-1"}
13:39:23.518Z  REFTABLE - Reference table code set to: 336 - Month: agosto/2026
13:39:24.714Z  Starting process for vehicle type 3...  (29 marcas de caminhão)
13:39:40.265Z  Completed processing for vehicle type 3.
13:39:40.765Z  Starting process for vehicle type 1...  (107 marcas de carro)
13:40:35.974Z  Completed processing for vehicle type 1.
13:40:36.475Z  Starting process for vehicle type 2...  (102 marcas de moto)
13:41:29.403Z  Completed processing for vehicle type 2.
13:41:29.903Z  Processing completed for all vehicle types.
               END RequestId: 85be10fd-...
               REPORT ... Duration: 127467.46 ms
```

A execução processou as 3 frotas completas (238 marcas no total) e terminou normalmente (sem erro, `REPORT` presente). **A linha `END_OF_RECORDS enviado para sinalizar fim do processamento mensal` nunca aparece** — porque, como mostrado na seção 1.1, o código implantado simplesmente não a possui.

### 2.2 Execução de 01/08/2026 (RequestId `cb3544e1-447a-4d7e-a833-c48d2ab810fd`) — disparo automático

```
06:00:37.584Z  {"status": "START", "event": "Pipeline iniciado em sa-east-1"}
...
06:02:45.282Z  REPORT RequestId: cb3544e1-...  Duration: 127697.75 ms
```

Mesmo padrão: execução completa, sem erro, sem `END_OF_RECORDS`.

### Comando usado (reprodutível):
```bash
aws logs filter-log-events --region sa-east-1 \
  --log-group-name /aws/lambda/FipeManufacturerLoader \
  --start-time <epoch_ms> --end-time <epoch_ms> \
  --filter-pattern "END_OF_RECORDS"
# resultado: vazio, nas duas execuções
```

---

## 3. Confirmação do lado de dentro: STG e PRD nunca "ouviram" o sinal

`FipeSomaIngestor-stg` e `FipeSomaIngestor-prd` **têm** o código certo (seção 1.3) e, de fato, processam volume real de mensagens de preço regularmente (ver métricas na seção 4). A cada lote de mensagens que processam sem ver uma mensagem `END_OF_RECORDS`, eles logam explicitamente:

```
INGESTOR - END_OF_RECORDS não recebido ainda (pipeline ainda em andamento)
```

Essa linha aparece **milhares de vezes** nos logs de `FipeSomaIngestor-stg` (ex: em 02/07/2026, das 13:06 em diante, uma vez por lote de mensagens processado). Buscando pelo caminho positivo — a linha que só aparece quando o sinal realmente chega:

```bash
aws logs filter-log-events --region us-east-2 --log-group-name /aws/lambda/FipeSomaIngestor-stg \
  --start-time <17/06/2026> --end-time <agora> --filter-pattern "\"recebido para mês\""
# resultado: vazio

aws logs filter-log-events --region us-east-2 --log-group-name /aws/lambda/FipeSomaIngestor-stg \
  --start-time <17/06/2026> --end-time <agora> --filter-pattern "\"FIM DO PIPELINE\""
# resultado: vazio

aws logs filter-log-events --region us-east-1 --log-group-name /aws/lambda/FipeSomaIngestor-prd \
  --start-time <17/06/2026> --end-time <agora> --filter-pattern "\"recebido para mês\""
# resultado: vazio
```

**Desde que esse código existe (17-18/06/2026) até hoje (12/08/2026), nenhuma das duas Lambdas jamais viu um `END_OF_RECORDS`.** Isso é consistente e esperado, dado o achado da seção 1: a origem do sinal (`sa-east-1`) nunca foi atualizada para enviá-lo.

---

## 4. `FipeSomaNotifier`: quando (e por quê) ele realmente foi chamado

### 4.1 `FipeSomaNotifier-prd` (us-east-1)

```bash
aws lambda get-function --function-name FipeSomaNotifier-prd --region us-east-1
# State: Active, LastModified: 2026-06-18T18:54:43Z  → a função existe e está no ar

aws cloudwatch get-metric-statistics --namespace AWS/Lambda --metric-name Invocations \
  --dimensions Name=FunctionName,Value=FipeSomaNotifier-prd --region us-east-1 \
  --start-time <70 dias atrás> --end-time <agora> --period 86400 --statistics Sum
# resultado: NENHUM datapoint
```

Não existe nem *log group* `/aws/lambda/FipeSomaNotifier-prd` — em CloudWatch, o log group de uma Lambda só é criado na primeira execução. **A função nunca foi invocada, nem uma vez, desde que foi implantada (18/06/2026).**

### 4.2 `FipeSomaNotifier-stg` (us-east-2) — as poucas invocações existentes são testes manuais

Métricas de invocação (`Invocations`, soma diária):

| Data | Invocações |
|---|---|
| 2026-06-18 | 13 |
| 2026-07-02 | 27 |
| (nenhum outro dia nos últimos 70 dias) | 0 |

Nenhuma dessas datas coincide com uma execução completa do pipeline detectada nas seções 2-3. O conteúdo dos logs confirma que são chamadas manuais:

```
2026-07-02T17:08:13.746Z  [ERROR]  NOTIFIER - reference_month não fornecido no evento
2026-07-02T17:58:29.079Z  [INFO]   NOTIFIER - Handler iniciado com evento:
                          {"reference_month": "2026-07", "reference_month_code": "335",
                           "records_total": 45230, "stage": "stg"}
2026-07-02T17:58:29.079Z  [INFO]   NOTIFIER - Disparando webhooks para stage=stg,
                          reference_month=2026-07, records=45230
2026-07-02T17:59:30.167Z  [INFO]   NOTIFIER - Handler iniciado com evento: {... "records_total": 45230 ...}
```

O valor `"records_total": 45230` é o **payload de teste fixo** documentado no material de planejamento da Melhoria 4 (usado em `aws lambda invoke --function-name FipeSomaNotifier-stg --payload '{"reference_month": "2026-05", "records_total": 45230}'`), repetido várias vezes com pequenas variações — inclusive uma chamada sem `reference_month`, que gerou erro. Isso é inequivocamente **teste manual durante o desenvolvimento**, não o pipeline real invocando a função (o pipeline, quando funcionasse, chamaria com `records_processed` real, contado durante a execução — não o número fixo `45230`).

**Conclusão da Parte 4:** o webhook para o app consumidor (Laranjinha/Odoo) nunca recebeu uma notificação disparada organicamente pelo pipeline — nem em STG, nem em PRD. Toda evidência de "webhook funcionando" nos registros da equipe vem de testes manuais isolados de `FipeSomaNotifier`, não de uma execução ponta-a-ponta real.

---

## 5. Achados secundários (fora do escopo principal, mas relevantes)

### 5.1 O agendamento automático não é o documentado
A regra do EventBridge existe e está `ENABLED`, mas roda `cron(0 6 1 * ? *)` — **dia 1 do mês, 06:00 UTC** — não "dia 4, 01:00 UTC" como descrito no `CLAUDE.md` e na própria descrição da regra (`"Executa FipeManufacturerLoader no 4º dia do mês"`, que está desatualizada em relação ao `ScheduleExpression` real). A execução automática de 01/08/2026 06:00:37 UTC bate com esse cron real.

### 5.2 Segredo hardcoded no código implantado
O header `proxy_nonce` enviado para o webhook da Laranjinha está **hardcoded diretamente no código-fonte** de `fipe_soma_notifier.py` (não vem do Parameter Store, ao contrário do `api_key`, que é buscado dinamicamente). Valor omitido deste documento por segurança — recomenda-se mover para o Parameter Store junto com `api_key`.

### 5.3 `fipe_soma_notifier.py` não existe no repositório da branch `multi-region-sa-east-1`
O código-fonte dessa Lambda (que existe e está implantada em `stg`/`prd`) não está presente em `code_lambdas/src/fipe_api/` na branch atual — só foi possível auditá-lo baixando o artefato já implantado diretamente da AWS. Isso sugere que o arquivo foi criado/versionado só nas branches `stage`/`production`, nunca trazido para `multi-region-sa-east-1` (mesmo não sendo necessário lá, valeria conferir se as três branches deveriam estar sincronizadas nesse arquivo).

---

## 6. Recomendação

Para que a afirmação "o webhook é disparado toda vez que o pipeline termina com sucesso" passe de **teórica** para **real**, é necessário:

1. **Reimplantar `sa-east-1`** (branch `multi-region-sa-east-1`) via `deploy-sa-east-1.yml` (ou `cdk deploy` manual), trazendo `FipeManufacturerLoader` e `FipeSomaIngestor` para a versão atual do código (que já contém a lógica de `END_OF_RECORDS`).
2. Após o deploy, **validar com uma execução real controlada** (ideal: `FORCE_VEHICLE_MODEL` restrito a uma marca, para ciclo rápido) que:
   - `FipeManufacturerLoader` loga `END_OF_RECORDS enviado ...`
   - `FipeSomaIngestor-stg`/`-prd` logam `END_OF_RECORDS recebido para mês: ...` e `🚀 FIM DO PIPELINE MENSAL`
   - `FipeSomaNotifier-stg`/`-prd` são efetivamente invocados (`Invocations` > 0 no dia do teste) com um `records_total` real, não `45230`
3. Corrigir a descrição/documentação do agendamento (seção 5.1).
4. Mover o `proxy_nonce` para o Parameter Store (seção 5.2).

---

## Apêndice: comandos usados (reprodutibilidade)

```bash
export AWS_PROFILE=mutualizo

# Identidade / conta
aws sts get-caller-identity --region sa-east-1

# Log groups existentes
aws logs describe-log-groups --region sa-east-1 --log-group-name-prefix "/aws/lambda/Fipe"
aws logs describe-log-groups --region us-east-2 --log-group-name-prefix "/aws/lambda/Fipe"
aws logs describe-log-groups --region us-east-1 --log-group-name-prefix "/aws/lambda/Fipe"

# Métricas de invocação (Invocations, diário, ~70 dias)
aws cloudwatch get-metric-statistics --region <region> --namespace AWS/Lambda --metric-name Invocations \
  --dimensions Name=FunctionName,Value=<function> \
  --start-time <70d atrás> --end-time <hoje> --period 86400 --statistics Sum

# Regra EventBridge
aws events list-rules --region sa-east-1

# Código realmente implantado (baixa o .zip do artefato em produção)
aws lambda get-function --function-name <function> --region <region> --query 'Code.Location' --output text
# (curl na URL retornada, unzip, comparar com o repositório via diff)

# Busca de log por padrão (usado para achar/confirmar END_OF_RECORDS)
aws logs filter-log-events --region <region> --log-group-name /aws/lambda/<function> \
  --start-time <epoch_ms> --end-time <epoch_ms> --filter-pattern "<pattern>"
```

---

## Correção Aplicada (2026-08-12, mesmo dia)

A recomendação original (seção 6) era "reimplantar sa-east-1 com o código atual". Ao tentar fazer exatamente isso, **o deploy falhou no `cdk synth`** — o que, felizmente, impediu que dois bugs adicionais e mais graves chegassem a ser aplicados na stack real.

### Bugs adicionais encontrados durante a correção

**Bug 1 — `TypeError` que causou a falha do deploy.** `fipe_data_stack.py` chamava `FipeApiStack(..., sqs_forwarding_stg=..., sqs_forwarding_prd=..., slack_webhook_url=...)`, mas `FipeApiStack.__init__` nunca declarou esses parâmetros nomeados (caíam no `**kwargs` e eram repassados para `NestedStack.__init__()`, que não os aceita). Mesmo corrigindo a assinatura, a classe não usava esses valores em nenhum lugar — `SQS_URL_STG`/`SQS_URL_PRD` nunca chegavam a ser variáveis de ambiente da Lambda. Refactor que ficou pela metade.

**Bug 2 — MUITO MAIS GRAVE: sa-east-1 tinha perdido o encaminhamento SQS por completo.** O mesmo commit `8572928` que adicionou a lógica de `END_OF_RECORDS` também **sobrescreveu** `fipe_soma_ingestor.py` em `multi-region-sa-east-1` com a versão de `stage` (que grava direto num RDS via `get_db_connection()`, lendo `RDS_HOST`). Em sa-east-1 não existe RDS local (`create_rds=False`), então `RDS_HOST` é `None` — **se esse deploy tivesse ido adiante, sa-east-1 teria parado de encaminhar qualquer coisa para as filas de STG/PRD**, quebrando o pipeline de dados inteiro (que hoje, com o código antigo ainda no ar, continua funcionando — só falta o webhook). A função de encaminhamento (`forward_to_queue`) simplesmente não existia mais no arquivo.

**Bug 3 — Invocação cross-region do Lambda client quebrada por design, já implantada há 2 meses.** Em `fipe_soma_ingestor.py` (versão de STG/PRD), `lambda_client = boto3.client('lambda', region_name='sa-east-1')` estava fixo. Invocação de Lambda não atravessa região — um client fixo em `sa-east-1` nunca acharia `FipeSomaNotifier-stg` (us-east-2) nem `FipeSomaNotifier-prd` (us-east-1). **Isso já estava implantado desde 18/06/2026 e nunca teria funcionado**, independentemente de qualquer coisa relacionada ao deploy de sa-east-1. Também havia um erro de design: cada ingestor disparava os **dois** notifiers (stg e prd) incondicionalmente, quando deveria disparar só o seu próprio.

### O que foi corrigido, por arquivo/branch

| O quê | Onde | Como |
|---|---|---|
| Agendamento mensal (dia 1, 11:00 UTC / 08:00 Brasília, não dia 4/01:00 UTC) | `CLAUDE.md` (local, não versionado) | Documentação corrigida para bater com o código-fonte real |
| `proxy_nonce` hardcoded | `fipe_soma_notifier.py` (stage, production, multi-region-sa-east-1) | Lido de `webhook.get("proxy_nonce")`, valor movido para o Parameter Store `/fipe/webhooks/{stg,prd}` |
| `fipe_soma_notifier.py` nunca commitado em `production`/`multi-region-sa-east-1` | idem | Arquivo trazido de `stage`, já com o fix acima |
| Bug 1 (TypeError do construtor) | `fipe_api_stack.py`, `fipe_data_stack.py` (multi-region-sa-east-1) | `sqs_forwarding_stg`/`sqs_forwarding_prd` declarados e injetados como `SQS_URL_STG`/`SQS_URL_PRD`; variáveis de RDS e permissão de secret só quando `db_secret_arn` existe; `slack_webhook_url` redundante removido |
| Bug 2 (encaminhamento SQS perdido) | `fipe_soma_ingestor.py` (multi-region-sa-east-1) | Restaurada a versão de `forward_to_queue`, extraída do artefato já implantado (comprovadamente funcional) |
| Bug 3 (client cross-region + dispara os dois notifiers) | `fipe_soma_ingestor.py` (stage, production) | `boto3.client('lambda')` sem região fixa (usa a região da própria execução); cada ingestor só dispara o notifier do seu próprio `STAGE` |

### Validação
- `cdk synth` local (`./venv/bin/python`, perfil `mutualizo`) passou com exit code 0 após as correções; confirmado no template gerado que a Lambda `FipeSomaIngestor` recebe `SQS_URL_STG`/`SQS_URL_PRD` com as URLs reais e nenhuma variável de RDS.
- Deploy real disparado nas 3 branches (`deploy-sa-east-1.yml`, `deploy-stage.yml` via auto-deploy de push, `deploy-production.yml`) — ver status exato no momento em que este documento foi lido (pode já ter avançado).
- **Ainda pendente após os deploys**: validar com uma execução real controlada (idealmente `FORCE_VEHICLE_MODEL` restrito) que a cascata completa funciona ponta a ponta: `END_OF_RECORDS` enviado → recebido por STG e PRD → cada um dispara seu próprio `FipeSomaNotifier` → webhook chega no consumidor com um `records_total` real (não o `45230` de teste).

### Lição aprendida
Antes de redeployar qualquer coisa "para trazer o código atualizado", **diffar o código atual contra o que está deployado função por função**, não só a função relacionada ao bug que está sendo investigado. Um "sync entre branches" anterior (commit `8572928`) introduziu uma regressão grave (Bug 2) que não tinha nada a ver com o problema original do webhook — só foi descoberta porque o deploy falhou por OUTRO motivo (Bug 1) antes de chegar a aplicar essa parte.

### Deploy de sa-east-1: confirmado e funcional (2026-08-12, ~15:15 UTC)

Validado diretamente na AWS após o deploy:
- `FipeSomaIngestor-unified`: tem `forward_to_queue`/`get_sqs_client`, **não** tem `get_db_connection`. Env vars: `SQS_URL_STG`/`SQS_URL_PRD` com URLs reais, sem nenhuma env var de RDS.
- `FipeManufacturerLoader-unified`: tem a lógica de `END_OF_RECORDS`.
- Regra EventBridge recriada com o cron correto (`cron(0 11 1 * ? *)`, dia 1 às 08:00 Brasília) e target aponta corretamente para a Lambda renomeada.

**⚠️ Achado (deferido a pedido do time): o deploy renomeou as 5 Lambdas e as 3 filas SQS de sa-east-1, adicionando o sufixo `-unified`** (ex: `FipeSomaIngestor` → `FipeSomaIngestor-unified`). Não quebra nada funcionalmente — confirmado que o CDK religou tudo automaticamente (event source mappings e EventBridge target apontam corretamente para os nomes novos) — mas contradiz a decisão de design da Melhoria 2 de não usar sufixo em sa-east-1. Causa: `fipe_api_stack.py` usa `f"...{stage}"` nos nomes dos recursos, e `stage="unified"` produz esse sufixo — mais um resíduo do commit `8572928`. **Correção adiada para depois**, junto com a validação end-to-end real (rodar um teste com `FORCE_VEHICLE_MODEL` e confirmar a cascata completa até cada `FipeSomaNotifier` disparar com um `records_total` real).

