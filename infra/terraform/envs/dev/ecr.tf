# ---------------------------------------------------------------------------
# Container registries (Phase 6c). CI pushes the images it built and scanned here;
# ECS pulls them by digest. Cost: storage only, ~$0.10/GB-month (about 1 GB here).
# ---------------------------------------------------------------------------

locals {
  images = toset(["api", "web"])
}

resource "aws_ecr_repository" "app" {
  for_each = local.images
  #checkov:skip=CKV_AWS_136:AES-256 (S3-managed) encryption; a KMS key adds ~$1/month without extra control for public-source images.

  name = "${local.name}/${each.key}"

  # A tag can never be pointed at different bytes. CI tags with the commit SHA, so
  # "what's running" always maps to one commit (the lesson of the trivy-action incident).
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true # basic scanning: free; trivy in CI is the gate, this is a second opinion
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  # Learning environment: `terraform destroy` may delete repositories that still hold
  # images. In a shared account, set this to false.
  force_delete = true
}

# Keep the registry (and its bill) small: the last 10 images per repository, and
# untagged leftovers for one day.
resource "aws_ecr_lifecycle_policy" "app" {
  for_each   = aws_ecr_repository.app
  repository = each.value.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Remove untagged images after 1 day"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 1
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Keep the 10 most recent images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 10
        }
        action = { type = "expire" }
      },
    ]
  })
}
