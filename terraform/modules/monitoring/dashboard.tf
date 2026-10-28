# One golden-signals dashboard per environment (three dashboards of up to 50 metrics are free per
# account; this one shows 27, 26 without the control metric) and saved Logs Insights queries for
# triage, which are free. The objectives these signals measure are in docs/slo.md.

locals {
  functions = var.function_names
  checker   = var.function_names["uptime_check"]
  api       = ["ApiId", var.api_id, "Stage", "$default"]

  per_function = { for metric in ["Duration", "Invocations", "Errors", "Throttles"] : metric => [
    for key, name in local.functions : ["AWS/Lambda", metric, "FunctionName", name, { label = key }]
  ] }

  per_table = { for metric in ["ConsumedReadCapacityUnits", "ConsumedWriteCapacityUnits", "ReadThrottleEvents", "WriteThrottleEvents"] : metric => [
    for table in var.tables : ["AWS/DynamoDB", metric, "TableName", table, { label = "${metric} ${table}" }]
  ] }

  graphs = [
    {
      title = "Latency: API p50 and p99, function p99 duration (ms)"
      stat  = "p99"
      metrics = concat(
        [concat(["AWS/ApiGateway", "Latency"], local.api, [{ stat = "p50", label = "API p50" }])],
        [concat(["AWS/ApiGateway", "Latency"], local.api, [{ stat = "p99", label = "API p99" }])],
        local.per_function["Duration"],
      )
    },
    {
      title   = "Traffic: API requests and function invocations"
      stat    = "Sum"
      metrics = concat([concat(["AWS/ApiGateway", "Count"], local.api, [{ label = "API requests" }])], local.per_function["Invocations"])
    },
    {
      title = "Errors: API 4xx and 5xx, function errors, dead-lettered runs${var.metrics_enabled ? ", blind checker" : ""}"
      stat  = "Sum"
      metrics = concat(
        [concat(["AWS/ApiGateway", "4xx"], local.api, [{ label = "API 4xx" }])],
        [concat(["AWS/ApiGateway", "5xx"], local.api, [{ label = "API 5xx" }])],
        local.per_function["Errors"],
        [["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", var.dead_letter_queue, { stat = "Maximum", label = "dead-lettered runs" }]],
        var.metrics_enabled ? [["VigilWatch", "ControlProbeFailed", "FunctionName", local.checker, { stat = "Maximum", label = "checker blind" }]] : [],
      )
    },
    {
      title   = "Saturation: function throttles, table capacity used and throttled"
      stat    = "Sum"
      metrics = concat(local.per_function["Throttles"], concat(values(local.per_table)...)) # not flatten: it would split each metric line
    },
  ]
}

resource "aws_cloudwatch_dashboard" "golden_signals" {
  dashboard_name = "${var.name_prefix}-golden-signals"
  dashboard_body = jsonencode({
    widgets = concat(
      [{
        type   = "text"
        x      = 0
        y      = 0
        width  = 24
        height = 2
        properties = {
          markdown = "## ${var.name_prefix}: golden signals\nObjectives and error budgets: docs/slo.md. Triage: the saved queries under ${var.name_prefix}/ in Logs Insights, and docs/RUNBOOK.md."
        }
      }],
      [for i, graph in local.graphs : {
        type   = "metric"
        x      = (i % 2) * 12
        y      = 2 + floor(i / 2) * 6
        width  = 12
        height = 6
        properties = {
          title   = graph.title
          region  = var.aws_region
          view    = "timeSeries"
          stacked = false
          period  = 300
          stat    = graph.stat
          metrics = graph.metrics
        }
      }],
    )
  })
}

locals {
  queries = {
    "function-errors" = {
      log_groups = [for name in values(local.functions) : "/aws/lambda/${name}"]
      query      = <<-EOT
        fields @timestamp, level, logger, message, request_id, exception
        | filter level = "ERROR" or @message like /Task timed out/
        | sort @timestamp desc
        | limit 50
      EOT
    }
    "checker-runs" = {
      log_groups = ["/aws/lambda/${local.checker}"]
      query      = <<-EOT
        fields @timestamp, request_id, @message
        | filter message = "run complete"
        | sort @timestamp desc
        | limit 50
      EOT
    }
    "api-5xx" = {
      log_groups = [var.api_access_log_group]
      query      = <<-EOT
        fields @timestamp, requestId, route, status, error, latencyMs
        | filter status like /^5/
        | sort @timestamp desc
        | limit 50
      EOT
    }
    "api-slow" = {
      log_groups = [var.api_access_log_group]
      query      = <<-EOT
        fields @timestamp, requestId, route, status, latencyMs
        | filter latencyMs > 500
        | sort latencyMs desc
        | limit 50
      EOT
    }
  }
}

resource "aws_cloudwatch_query_definition" "query" {
  for_each = local.queries

  name            = "${var.name_prefix}/${each.key}"
  log_group_names = each.value.log_groups
  query_string    = each.value.query
}
