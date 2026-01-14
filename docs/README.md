# VigilWatch - Serverless Uptime Monitoring Dashboard

## 🚀 Overview
VigilWatch is a fully serverless uptime and incident monitoring platform that performs synthetic HTTP checks against configured endpoints, detects failures, records incidents, and visualizes system health in near real-time.

## ✨ Features
- **Endpoint Monitoring**: HTTP/HTTPS endpoint health checks
- **Uptime Calculation**: Automatic uptime percentage tracking
- **Incident Management**: Failure detection and resolution tracking
- **Real-time Dashboard**: Live status visualization
- **Latency Metrics**: Response time tracking
- **Alert System**: Email notifications via SNS
- **Historical Data**: 30-day incident history

## 🏗️ Architecture

[ User Browser ]
|
HTTPS (443)
|
[ CloudFront + ACM SSL ]
|
[ S3 Static Website ]
|
[ API Gateway ]
|
[ Lambda Functions ]
|
[ DynamoDB Tables ]
|
[ CloudWatch + SNS ]


## 🔧 AWS Services Used
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



## 🚀 Deployment

### Prerequisites
- AWS CLI configured with credentials
- Terraform v1.0+ installed
- Python 3.11+ for Lambda functions

### Step-by-Step Deployment

1. **Clone and Setup**
```bash
git clone <your-repo>
cd VigilWatch

cd terraform
terraform init

terraform plan

terraform apply -auto-approve

# Update frontend with API URL
API_URL=$(terraform output -raw api_gateway_url)
sed -i "s|YOUR_API_URL|$API_URL|" .../frontend/index.html

# Upload to the S3
aws s3 sync .../frontend/ s3://vigilwatch-frontend-$(terraform output -raw aws_account_id)/

echo "Dashboard URL: https://$(terraform output -raw cloudfront_distribution_id).cloudfront.net"