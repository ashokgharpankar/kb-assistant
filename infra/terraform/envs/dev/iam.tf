# ---------------------------------------------------------------------------
# The application's identity.
#
# You (the developer) log in as an admin. The APP must not. It gets a role that
# can call three named models and nothing else. Locally you "assume" this role
# to test with exactly the permissions production will have. In Phase 6 the
# same policy is attached to the ECS task role.
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "app_trust" {
  statement {
    sid     = "DeveloperCanAssume"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${local.account_id}:root"]
    }

    # "root" above means "this account", not the root user. The condition then
    # narrows it to one identity: by default, whoever ran `terraform apply` (you).
    condition {
      test     = "ArnEquals"
      variable = "aws:PrincipalArn"
      values   = [local.developer_arn]
    }
  }
}

resource "aws_iam_role" "app" {
  name                 = "${local.name}-app"
  description          = "Runtime identity of the knowledge assistant (least privilege)."
  assume_role_policy   = data.aws_iam_policy_document.app_trust.json
  max_session_duration = 3600
}

data "aws_iam_policy_document" "bedrock_invoke" {
  statement {
    sid    = "InvokeApprovedModelsOnly"
    effect = "Allow"

    # The Converse API is authorised by these same two actions.
    actions = [
      "bedrock:InvokeModel",
      "bedrock:InvokeModelWithResponseStream",
    ]

    resources = concat(
      # Foundation models. Region is "*" because a cross-region inference
      # profile may serve the request from another US region.
      [for id in var.bedrock_model_ids : "arn:aws:bedrock:*::foundation-model/${id}"],
      # The matching cross-region inference profiles (us.amazon.nova-...).
      [for id in var.bedrock_model_ids : "arn:aws:bedrock:${var.region}:${local.account_id}:inference-profile/us.${id}"],
    )
  }
}

resource "aws_iam_policy" "bedrock_invoke" {
  name        = "${local.name}-bedrock-invoke"
  description = "Invoke a fixed allow-list of Bedrock models."
  policy      = data.aws_iam_policy_document.bedrock_invoke.json
}

resource "aws_iam_role_policy_attachment" "app_bedrock" {
  role       = aws_iam_role.app.name
  policy_arn = aws_iam_policy.bedrock_invoke.arn
}
