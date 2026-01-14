# VigilWatch - Serverless Uptime Monitoring Dashboard

## Overview
VigilWatch is a fully serverless uptime and incident monitoring platform that performs synthetic HTTP checks against configured endpoints, detects failures, records incidents, and visualizes system health in near real-time.

## Features
- **Endpoint Monitoring**: HTTP/HTTPS endpoint health checks
- **Uptime Calculation**: Automatic uptime percentage tracking
- **Incident Management**: Failure detection and resolution tracking
- **Real-time Dashboard**: Live status visualization
- **Latency Metrics**: Response time tracking
- **Alert System**: Email notifications via SNS
- **Historical Data**: 30-day incident history

## Architecture

[ User / Client ]
|
| HTTPS
v
[ Amazon API Gateway ]
|
v
[ Lambda: api_handler ]
|
v
[ DynamoDB: monitored_endpoints ]

(Scheduled Monitoring)
[ Amazon EventBridge ]
|
v
[ Lambda: uptime_checker ]
|
v
[ External Websites / APIs ]
|
v
[ DynamoDB Updates ]
|
v
[ Amazon SNS Notifications ]

(All logs and metrics → Amazon CloudWatch)


## AWS Services Used
| Service | Purpose |
|---------|---------|
| **Lambda** | Serverless compute for monitoring logic |
| **DynamoDB** | NoSQL storage for check results and endpoints |
| **API Gateway** | REST API for frontend communication |
| **S3** | Static website hosting |
| **CloudFront** | CDN with HTTPS |
| **ACM** | SSL/TLS certificates |
| **CloudWatch** | Monitoring, logs, and alarms |
| **SNS** | Alert notifications |
| **EventBridge** | Scheduled monitoring triggers |

## Security Design

- **IAM Least Privilege**:  
  Lambda functions only have permissions required for DynamoDB, SNS, and CloudWatch.
- **HTTPS Everywhere**:  
  API Gateway enforces HTTPS by default.
- **No Public Databases**:  
  DynamoDB is accessed only via IAM-authenticated Lambdas.
- **No VPC Required**:  
  AWS-managed networking reduces attack surface and cost.


## Deployment

### Prerequisites
- AWS CLI configured with credentials
- Terraform v1.0+ installed
- Python 3.11+ for Lambda functions

### Step-by-Step Deployment

### Step-by-Step Deployment

```bash
# Clone the repository
git clone https://github.com/lesego-rabotapi/VigilWatch.git
cd VigilWatch

# Initialize Terraform
cd terraform
terraform init

# Review the execution plan
terraform plan

# Deploy infrastructure
terraform apply