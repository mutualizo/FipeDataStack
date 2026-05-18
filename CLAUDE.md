# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

FipeDataStack is an AWS CDK project (Python) that provisions infrastructure to **automatically update a monthly snapshot of FIPE vehicle pricing data** into PostgreSQL. The system executes once per month on a scheduled basis (via EventBridge) to fetch fresh pricing tables from the FIPE API and store them in the database.

Main components:

1. **FipeDataStack**: PostgreSQL Aurora database cluster for storing monthly FIPE vehicle price snapshots
2. **FipeApiStack**: Nested stack with Lambda functions, SQS queues, and EventBridge scheduling for the monthly data pipeline

The system follows a data pipeline architecture where:
- **FipeManufacturerLoader** is triggered automatically once per month by EventBridge
- Lambda functions are chained via SQS messages: Manufacturers → Models → Prices → Database ingestion
- Each stage processes and forwards data to the next queue for parallel efficiency

## Quick Commands

```bash
# Install dependencies
make install

# Prepare Lambda layers and dependencies
make prepare-layers

# Deploy to development environment
make deploy-dev AWS_PROFILE=your-profile VPC_ID=vpc-xxxxx ALLOWED_IP=123.456.789.0

# Deploy to staging/production
make deploy-stg AWS_PROFILE=your-profile VPC_ID=vpc-xxxxx ALLOWED_IP=123.456.789.0
make deploy-prd AWS_PROFILE=your-profile VPC_ID=vpc-xxxxx ALLOWED_IP=123.456.789.0

# Bootstrap CDK for AWS environment
make bootstrap AWS_PROFILE=your-profile

# Run tests
python -m pytest tests/

# Clean temporary artifacts
make clean

# Destroy resources from environment
make destroy-dev AWS_PROFILE=your-profile
```

## Project Structure

```
FipeDataStack2/
├── app.py                         # CDK app entry point (handles auth, stage management)
├── fipe_data_stack.py             # Main stack: Aurora PostgreSQL, Security Groups, Secrets
├── fipe_api_stack.py              # Nested stack: Lambda functions, SQS queues, DLQs
├── fipe_api_layer/                # Lambda layer for FIPE API dependencies
├── lambda/                        # Lambda function for database initialization (SQL runner)
├── code_lambdas/                  # Source code for FIPE processing Lambda functions
│   └── src/fipe_api/              # Core Lambda implementations (loader + ingestor)
├── create_fipe_db.sql             # Initial database schema
├── create-fipe-api-layer.sh       # Script to package Lambda layer dependencies
├── makefile.txt                   # Build and deployment automation
├── requirements.txt               # Python dependencies (aws-cdk, boto3, psycopg2)
├── cdk.json                       # CDK configuration and context values
├── cdk.context.json               # CDK cached context (auto-generated)
├── .github/workflows/             # GitHub Actions CI/CD pipelines
└── tests/                         # Unit tests (minimal, mainly assertions templates)
```

## Architecture Highlights

### Data Pipeline
1. **FipeManufacturerLoader** → Fetches manufacturers from FIPE API → sends to SQS
2. **FipeModelLoader** → Consumes manufacturer messages → fetches models → sends to SQS
3. **FipePriceLoader** → Consumes model messages → fetches prices → sends to SQS
4. **FipeSomaIngestor** → Consumes price messages → inserts/updates database

### Key Infrastructure Features
- **Dead Letter Queues (DLQ)**: All SQS queues have associated DLQs for failed messages
- **Environment Variables**: Lambdas use `SQS_OUTPUT_URL`, `SQS_INPUT_URL`, `RDS_HOST`, `RDS_PORT`, `RDS_DATABASE`, `RDS_USER`
- **Secrets Manager**: Database credentials stored and retrieved via AWS Secrets Manager
- **Security Groups**: VPC-level access control; database access restricted to specified IP
- **Exponential Backoff**: Throttling handling for FIPE API rate limits
- **Batch Processing**: Messages grouped with configurable wait periods for efficiency

## Working with Environments

### Stages (dev, stg, prd)
- Stages are controlled via `STACK_STAGE` environment variable or command-line argument
- Each stage gets its own database, Lambda functions, SQS queues, and security groups
- All resources are tagged with the stage for cost allocation and organization
- Example: `FipeDataStack-dev`, `FipeDataStack-stg`, `FipeDataStack-prd`

### AWS Credentials
- **Via AWS Profile**: `AWS_PROFILE=profile-name` (credentials from `~/.aws/credentials`)
- **Via Environment Variables**: `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` (with `AWS_REGION`)
- **Context Variables**: `vpc_id` and `allowed_ip` are required for deployment (no defaults)

### Context Values in cdk.json
- Pre-configured CDK feature flags for best practices and security
- Watch excludes: tests, __pycache__, requirements, README
- Context values like `@aws-cdk/core:enableAdditionalMetadataCollection` are set for compatibility

## Database & Secrets

### Database Access
- **Engine**: PostgreSQL Aurora (T3.MEDIUM instance for free tier eligibility)
- **User**: Default user is `postgres`
- **Credentials**: Auto-generated and stored in AWS Secrets Manager
- **Retrieval**: `aws secretsmanager get-secret-value --secret-id <DBSecretArn> --query 'SecretString'`

### Initial Schema
- `create_fipe_db.sql` contains table definitions for FIPE data
- Executed by a Lambda function during stack creation (using CustomResource)
- Database name: `fipedata`

## Lambda Functions

### Layer Dependencies
- `fipe_api_layer/` packages all Python dependencies (boto3, requests, psycopg2-binary, etc.)
- Layer path: `python/lib/python3.10/site-packages/`
- Built via `create-fipe-api-layer.sh` which copies dependencies from `requirements.txt`
- psycopg2 has its own layer for database connectivity

### Lambda Configuration
- **Runtime**: Python 3.10
- **Timeout**: 5 minutes (manufacturer loader: 10 minutes due to API calls)
- **Memory**: Configured in `fipe_api_stack.py` (256MB by default)
- **VPC**: All Lambdas have VPC access for database connectivity
- **Environment**: Injected at stack creation (SQS URLs, database parameters)

## Monthly Execution Schedule

The pipeline is **automatically triggered once per month via EventBridge** (CloudWatch Events):

### Scheduling Details
- **Trigger**: EventBridge rule `FipeManufacturerMonthlyRule-<stage>`
- **Schedule**: Cron expression: `0 1 4 * *` (4th day of each month at 01:00 UTC)
- **Function Triggered**: `FipeManufacturerLoader` (entry point for the entire pipeline)

### How It Works
1. EventBridge rule fires at scheduled time
2. Automatically invokes `FipeManufacturerLoader` Lambda without manual intervention
3. Manufacturer loader fetches data and sends messages to the manufacturer queue
4. Subsequent Lambdas consume and process messages (Model → Price → Ingestor)
5. Final ingestor inserts/updates the monthly snapshot in PostgreSQL

### No Manual Invocation Needed
- Unlike typical Lambda deployments, **you don't need to manually invoke the function**
- The entire monthly data refresh happens automatically on schedule
- You only need to monitor logs and DLQ for any failures

### Modifying the Schedule
To change the execution time or day, modify the cron expression in `fipe_api_stack.py` (line ~183):
```python
schedule=events.Schedule.cron(minute="0", hour="1", day="4", month="*", year="*")
# minute hour day month year
# Example: daily at 2:30 AM = minute="30", hour="2", day="*", month="*", year="*"
# Example: last day of month at midnight = minute="0", hour="0", day="L", month="*", year="*" (if supported)
```

After modifying, redeploy the stack:
```bash
make deploy-dev AWS_PROFILE=your-profile VPC_ID=vpc-xxxxx ALLOWED_IP=123.456.789.0
```

## GitHub Actions Workflows

Three workflows handle CI/CD:
- `deploy-development.yml`: Manual trigger, deploys to dev environment
- `deploy-stage.yml`: Manual trigger, deploys to staging
- `deploy-production.yml`: Manual trigger, deploys to production

Workflows:
1. Checkout code
2. Configure AWS credentials from secrets/variables
3. Setup Python 3.10 and Node.js 22
4. Install CDK and Python dependencies
5. Build Lambda layers via shell script
6. Bootstrap CDK (if needed)
7. Deploy with context parameters

**Note**: Workflow uses `context vars` like `STACK_STAGE`, `AWS_REGION`, `VCP_ID` (note the typo in the var name).

## Deployment Checklist

Before deploying:
1. Ensure AWS credentials are configured (profile or env vars)
2. Verify `VPC_ID` and `ALLOWED_IP` context values are correct
3. Run `make prepare-layers` to build Lambda dependencies
4. Run tests if modifying stack logic: `python -m pytest tests/`
5. Review `cdk diff` to see what will be created/modified: `cdk diff --context vpc_id=vpc-xxx --context allowed_ip=1.2.3.4`

After deployment, CDK outputs include:
- **FipeDataStack**: DBEndpoint, DBPort, DBSecretArn
- **FipeApiStack**: Queue URLs (ManufacturerQueueUrl, ModelQueueUrl, PriceQueueUrl) and DLQ URLs

## Post-Deployment Operations

### Connecting to Database
```bash
# Get password from Secrets Manager
aws secretsmanager get-secret-value --secret-id <DBSecretArn> --query 'SecretString' --output text | jq -r '.password'

# Connect via psql
psql -h <DBEndpoint> -p 5432 -U postgres -d fipedata
```

### Monitoring the Monthly Execution
Since the pipeline executes automatically, monitor these key areas:

#### Lambda Execution Logs
```bash
# View logs for each stage of the pipeline
aws logs tail /aws/lambda/FipeManufacturerLoader-dev --follow
aws logs tail /aws/lambda/FipeModelLoader-dev --follow
aws logs tail /aws/lambda/FipePriceLoader-dev --follow
aws logs tail /aws/lambda/FipeSomaIngestor-dev --follow
```

#### SQS Queue Depth
Monitor queue length to detect bottlenecks:
```bash
aws sqs get-queue-attributes --queue-url <QUEUE_URL> \
  --attribute-names ApproximateNumberOfMessages,ApproximateNumberOfMessagesDelayed
```

#### Dead Letter Queues (DLQ)
If messages fail, they appear in DLQs after max retries:
```bash
# Check DLQ message count
aws sqs get-queue-attributes --queue-url <DLQ_URL> \
  --attribute-names ApproximateNumberOfMessages

# View messages in DLQ (for debugging)
aws sqs receive-message --queue-url <DLQ_URL> --max-number-of-messages 10
```

#### EventBridge Rule Status
```bash
# Check if the monthly rule is enabled
aws events list-rules --name-prefix FipeManufacturer-<stage>

# View recent invocations (via CloudWatch Insights or direct log inspection)
# Each scheduled invocation will have logs timestamped at 01:00 UTC on the 4th
```

#### DLQ Reprocessing
If messages need to be reprocessed:
```bash
# Move messages back from DLQ to main queue for retry
aws sqs receive-message --queue-url <DLQ_URL> --max-number-of-messages 10 | \
jq -r '.Messages[] | @base64' | while read msg; do
    body=$(echo $msg | base64 --decode | jq -r '.Body')
    aws sqs send-message --queue-url <MAIN_QUEUE_URL> --message-body "$body"
    receipt=$(echo $msg | base64 --decode | jq -r '.ReceiptHandle')
    aws sqs delete-message --queue-url <DLQ_URL> --receipt-handle "$receipt"
done
```

### Monitoring Monthly Execution
```bash
# Check if execution rule is enabled
aws events list-rules --name-prefix FipeManufacturer

# View recent rule invocations (check CloudWatch Logs instead - see below)
aws logs tail /aws/lambda/FipeManufacturerLoader-dev --follow

# Check for failed messages in DLQ
aws sqs get-queue-attributes \
  --queue-url https://sqs.us-east-1.amazonaws.com/123456789/fipe-manufacturer-dlq-dev \
  --attribute-names ApproximateNumberOfMessages
```

### Manual Testing (One-Time Invocation)
To test the pipeline manually **without waiting for the monthly schedule**:
```bash
# Trigger the pipeline immediately (for testing purposes only)
aws lambda invoke --function-name FipeManufacturerLoader-dev response.json

# Check response
cat response.json
```

**Note**: Manual invocation is typically only needed for testing or if you need to force an immediate data refresh outside the monthly schedule.

## Common Development Patterns

### Modifying a Lambda Function
- Source code in `code_lambdas/src/fipe_api/`
- Update `requirements.txt` if adding dependencies
- Rebuild layer: `make prepare-layers`
- Redeploy: `make deploy-dev` (or relevant stage)

### Adding a New Stack Resource
- Edit `fipe_data_stack.py` or `fipe_api_stack.py`
- Update `requirements.txt` if importing new CDK constructs
- Test with `python -m pytest` or `cdk diff`
- Deploy to dev first for validation

### Debugging Stack Issues
- Check CloudFormation events: `aws cloudformation describe-stack-events --stack-name FipeDataStack-dev`
- Review Lambda logs in CloudWatch
- Verify security group rules allow necessary traffic
- Confirm database credentials are accessible via Secrets Manager

## Key Dependencies

- **aws-cdk-lib 2.252.0**: Core CDK library
- **constructs 10.x**: CDK construct base classes
- **boto3 1.28.0+**: AWS SDK for Python
- **psycopg2-binary 2.9.6+**: PostgreSQL adapter for Lambda layer

## Testing

- Basic test file at `tests/unit/test_fipe_data_cdk_stack.py` (mostly boilerplate)
- Tests use CDK assertions to validate template generation
- Run tests locally before committing changes to stacks

## Notes

### Infrastructure
- Free tier eligible: T3.MEDIUM instance class, short backup retention
- Backup retention: 7 days default (modifiable in `fipe_data_stack.py`)
- SQS retention: 4 days for main queues, 14 days for DLQs
- DLQ threshold: Messages move to DLQ after 5 failed processing attempts
- API rate limiting: Exponential backoff implemented in Lambda code to handle FIPE API throttling

### Monthly Execution
- **Automatic Scheduling**: Pipeline is fully automated via EventBridge (no manual trigger needed)
- **Execution Day**: 4th of each month at 01:00 UTC (configurable in `fipe_api_stack.py`)
- **Duration**: Entire pipeline typically completes within 10-15 minutes depending on API response times
- **Data Overwrite**: Each monthly execution creates a new snapshot; old data is kept (not overwritten unless explicitly configured)
- **Failure Handling**: If any stage fails, messages go to DLQ and are not retried automatically (manual intervention needed)
- **Timezone**: All times in EventBridge are UTC; adjust `hour` parameter if you need a different timezone

### Operational Best Practices
- Monitor logs ~5 minutes after scheduled execution time (around 01:05 UTC on the 4th)
- Set up CloudWatch Alarms for Lambda failures or DLQ message counts exceeding threshold
- Review monthly database size growth to ensure storage is adequate
- Keep audit trail by checking database last_modified timestamps to verify successful ingestion
