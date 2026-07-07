# VigilWatch

## The "Why" Before the "How"

Modern teams often discover outages only after users complain. Enterprise monitoring platforms can be expensive or operationally heavy for small teams. VigilWatch explores how a serverless AWS architecture can provide automated uptime monitoring, incident recording and near real-time visibility while keeping infrastructure simple and inexpensive.

Rather than being a demo of AWS services, this project is an exercise in engineering trade-offs, Infrastructure as Code, and production-inspired cloud design.

## Engineering Objectives
- Fully serverless architecture
- Infrastructure defined with Terraform
- Event-driven scheduled monitoring
- Low operational overhead
- Security-first IAM design
- Reproducible deployments

## Architecture
Frontend (S3 + CloudFront)
→ API Gateway
→ Lambda APIs
→ DynamoDB

EventBridge (schedule)
→ Uptime Checker Lambda
→ External endpoints
→ DynamoDB
→ SNS alerts

CloudWatch collects logs and metrics.

## Why these technologies?

| Technology | Reasoning |
|---|---|
| AWS Lambda | Eliminates server management and scales automatically |
| DynamoDB | Key-value workload with predictable access patterns and low operational cost |
| API Gateway | Secure managed REST API |
| EventBridge | Reliable scheduled execution without cron servers |
| Terraform | Declarative, reproducible infrastructure |
| CloudFront + S3 | Low-cost globally distributed frontend hosting |

## Engineering Trade-offs
- Serverless reduces operational burden but introduces cold starts.
- DynamoDB simplifies scaling but requires careful data modelling.
- A managed architecture sacrifices some flexibility in exchange for reliability and reduced maintenance.

## Security
- Least-privilege IAM
- HTTPS endpoints
- No public database
- CloudWatch audit logging

## Repository Structure
```text
terraform/      Infrastructure as Code
lambda/         Backend functions
frontend/       Static dashboard
tests/          Unit and integration tests
docs/           Documentation
```

## Running
```bash
git clone https://github.com/lesego-rabotapi/VigilWatch.git
cd VigilWatch/terraform
terraform init
terraform plan
terraform apply
```

## Testing
Run:
```bash
pytest
```

## Lessons Learned
- Infrastructure should be version controlled alongside application code.
- Event-driven systems reduce operational complexity for scheduled workloads.
- Cloud-native services require understanding service limits and failure modes, not just APIs.

## Future Improvements
- Dead-letter queues
- Multi-region monitoring
- Authentication and RBAC
- OpenTelemetry tracing
- GitHub Actions quality gates
- Cost dashboards

## Production Readiness
Current implementation demonstrates sound cloud engineering practices including IaC, automated deployment, serverless architecture, monitoring, and testing. Additional resilience features such as retries, DLQs, authentication, and observability would further improve production readiness.

