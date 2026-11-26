# ---------------------------------------------------------------------------
# GitHub Actions → AWS without stored keys (Phase 6c).
#
# GitHub issues each workflow run a short-lived OIDC token saying "I am repo X,
# branch Y". AWS trusts GitHub's identity provider, checks those claims, and hands
# back temporary credentials for one narrow role. No AWS access key exists anywhere
# to leak, rotate or forget.
# ---------------------------------------------------------------------------

# An account can have only one OIDC provider per URL, and it is shared by every
# project in the account that deploys from GitHub. So this stack looks it up instead
# of owning it: `terraform destroy` here must never delete another project's sign-in.
# The provider must list "sts.amazonaws.com" as an audience (client ID).
# Brand-new account? Create it once, outside this stack:
#   aws iam create-open-id-connect-provider \
#     --url https://token.actions.githubusercontent.com --client-id-list sts.amazonaws.com
data "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
}

data "aws_iam_policy_document" "github_trust" {
  statement {
    sid     = "GitHubActionsOnMainOnly"
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [data.aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Only this repository, and only workflow runs on main. A pull request (or a fork)
    # gets a different "sub" claim and is refused. With immutable subject claims the
    # sub carries numeric owner and repo IDs, so a deleted-and-recreated repository
    # with the same name cannot inherit this trust. A wildcard here ("repo:*") would let
    # any GitHub repository in the world assume the role.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:ref:refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "github_ecr_push" {
  name                 = "${local.name}-github-ecr-push"
  description          = "Assumed by GitHub Actions on main to push scanned images to ECR."
  assume_role_policy   = data.aws_iam_policy_document.github_trust.json
  max_session_duration = 3600
}

data "aws_iam_policy_document" "ecr_push" {
  statement {
    sid = "RegistryLogin"
    # GetAuthorizationToken has no resource-level permissions: it must be "*".
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"] #checkov:skip=CKV_AWS_356:ecr:GetAuthorizationToken only supports "*"
  }

  statement {
    sid = "PushToOurRepositoriesOnly"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
      "ecr:PutImage",
      "ecr:BatchGetImage",
      "ecr:DescribeImages",
    ]
    resources = [for r in aws_ecr_repository.app : r.arn]
  }
}

resource "aws_iam_role_policy" "github_ecr_push" {
  name   = "ecr-push"
  role   = aws_iam_role.github_ecr_push.id
  policy = data.aws_iam_policy_document.ecr_push.json
}
