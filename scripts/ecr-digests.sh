#!/usr/bin/env bash
# Print the newest api and web images in ECR, pinned by digest, as terraform.tfvars lines:
#   app_api_image = "<repo>@sha256:..."
# Used by `make ecr-digests` and `make tf-plan-app` (Phase 6c-2).
set -euo pipefail
tf_dir=${1:-infra/terraform/envs/dev}
repos=$(terraform -chdir="$tf_dir" output -json ecr_repositories)
for img in api web; do
  repo=$(python3 -c "import sys,json; print(json.loads(sys.argv[1])[sys.argv[2]])" "$repos" "$img")
  name=${repo#*/}   # kb-assistant-dev/<img>
  digest=$(aws ecr describe-images --repository-name "$name" \
    --query 'sort_by(imageDetails,&imagePushedAt)[-1].imageDigest' --output text)
  if [[ -z "$digest" || "$digest" == "None" ]]; then
    echo "No image in $name yet: merge to main so CI pushes one." >&2
    exit 1
  fi
  echo "app_${img}_image = \"${repo}@${digest}\""
done
