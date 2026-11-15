# ---------------------------------------------------------------------------
# Budgets: the smoke alarm. They do not stop spend, they tell you about it early.
#
# Key detail for a credit-funded account: by default a budget tracks what you
# are BILLED. With $100-200 of credits that number is $0 until the credits are
# gone, so the alarm would stay silent while you burn through them. We exclude
# credits and refunds so the budget tracks real usage.
# ---------------------------------------------------------------------------

locals {
  # Alert at 50% and 100% of actual spend, and when the month is FORECAST to
  # exceed the limit (the earliest warning of the three).
  budget_alerts = {
    actual_50    = { type = "ACTUAL", threshold = 50 }
    actual_100   = { type = "ACTUAL", threshold = 100 }
    forecast_100 = { type = "FORECASTED", threshold = 100 }
  }
}

resource "aws_budgets_budget" "account" {
  name         = "${local.name}-account-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_types {
    include_credit = false
    include_refund = false
  }

  dynamic "notification" {
    for_each = local.budget_alerts

    content {
      comparison_operator        = "GREATER_THAN"
      notification_type          = notification.value.type
      threshold                  = notification.value.threshold
      threshold_type             = "PERCENTAGE"
      subscriber_email_addresses = [var.alert_email]
    }
  }
}

# Bedrock gets its own, tighter budget: it is the one service where a bug
# (a retry loop, a runaway agent) can spend money quickly.
resource "aws_budgets_budget" "bedrock" {
  name         = "${local.name}-bedrock-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.bedrock_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_types {
    include_credit = false
    include_refund = false
  }

  cost_filter {
    name   = "Service"
    values = ["Amazon Bedrock"]
  }

  dynamic "notification" {
    for_each = local.budget_alerts

    content {
      comparison_operator        = "GREATER_THAN"
      notification_type          = notification.value.type
      threshold                  = notification.value.threshold
      threshold_type             = "PERCENTAGE"
      subscriber_email_addresses = [var.alert_email]
    }
  }
}

# --- Day 2: per-project view --------------------------------------------------
# Tags only show up in billing once you "activate" them as cost allocation tags.

resource "aws_ce_cost_allocation_tag" "project" {
  count = var.enable_project_tag_budget ? 1 : 0

  tag_key = "Project"
  status  = "Active"
}

resource "aws_budgets_budget" "project" {
  count = var.enable_project_tag_budget ? 1 : 0

  name         = "${local.name}-project-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_types {
    include_credit = false
    include_refund = false
  }

  cost_filter {
    name = "TagKeyValue"
    # Format is "user:<TagKey>$<TagValue>". format() avoids HCL treating "$" + "{" as an escape.
    values = [format("user:Project$%s", var.project)]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    notification_type          = "ACTUAL"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    subscriber_email_addresses = [var.alert_email]
  }

  depends_on = [aws_ce_cost_allocation_tag.project]
}
