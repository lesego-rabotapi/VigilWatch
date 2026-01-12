A web-based uptime and incident monitoring platform that performs synthetic checks against configured endpoints, detects failures, records incidents, and visualizes system health in near real-time.

# Features include:
- Endpoint monitoring (HTTP)
- Uptime Calculation
- Incident resolution
- Dashboard view

Add ons:
- Latency metrics
- Alerts (CloudWatch)
- Historical incident view

In future/post-build
- AI-based anomaly detection

# User roles
- System: perfoms checks and detects incidents
- User: views and adds monitored checkpoints



----------------------------------------------
# AWS Serverless Uptime Monitoring Dashboard

## Overview
This project implements a serverless uptime monitoring system using AWS-native services.

## Architecture
(Insert diagram)

## AWS Services Used
- Lambda
- EventBridge
- DynamoDB
- API Gateway
- S3
- CloudFront
- CloudWatch
- SNS

## Deployment
1. terraform init
2. terraform plan
3. terraform apply

## Monitoring
CloudWatch logs, alarms, and SNS alerts.

## Cost Optimization
All services operate within AWS Free Tier.
