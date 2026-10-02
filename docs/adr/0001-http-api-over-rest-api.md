# ADR 0001: API Gateway HTTP API instead of REST API

- Status: accepted (2026-10-02)

## Context

The first version used a REST API (v1). Its Terraform needed a resource, method, integration,
method response and integration response per route, plus OPTIONS mock integrations for CORS.
A half-finished migration to HTTP API left the configuration referencing resources that did
not exist. The API has two routes and no need for REST-only features (usage plans, request
validation, private endpoints, edge-optimized endpoints).

## Decision

Use an HTTP API (v2) with a `$default` stage, Lambda proxy integrations (payload format 2.0),
API-level CORS and stage throttling.

## Consequences

- Roughly 70% cheaper per request than REST after the free period; free tier is the same 1M calls/month for 12 months.
- CORS has one source of truth: `cors_configuration`. The functions set no CORS headers, which tests enforce.
- API keys and usage plans are not available. Abuse control is throttling plus the endpoint cap (ADR 0004).
- The invoke URL has no stage prefix, so it changed. The dashboard reads it from the generated `config.js`.
