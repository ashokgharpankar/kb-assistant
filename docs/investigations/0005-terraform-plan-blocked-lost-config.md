# Incident 0005: Terraform plan blocked: lost git-ignored config and a self-inflicted backend reset

**Date:** 2026-11-22 · **Phase:** 2c · **Severity:** medium (blocked infrastructure changes)
**Status:** Resolved; bootstrap re-import written in Phase 6c (closed once `make tf-bootstrap-apply` runs)

## Summary

Adding Cognito with Terraform, `make tf-plan` failed in a chain of four separate problems.
Live infrastructure (budgets, anomaly detection, an IAM role) had to stay untouched.

## Timeline

| Step | Symptom | Cause | Fix |
|---|---|---|---|
| 1 | `tflint: command not found` | TFLint is no longer in Homebrew (license change); `brew install` silently found nothing | `make tf-check` now runs the official Docker image when tflint isn't installed |
| 2 | `Backend initialization required` | **My own tooling:** `tf-check` validated with `init -backend=false` in the same folder, resetting the real backend setup | Validate in a separate data dir (`TF_DATA_DIR=.terraform-validate`); `tf-init` uses `-reconfigure` |
| 3 | `backend.hcl` missing; bootstrap `output` empty | Lost in incident 0003 (git-ignored, so git couldn't restore it); the bootstrap stack's local state too | Found the state bucket with `aws s3 ls`, confirmed `envs/dev/terraform.tfstate` existed, rewrote `backend.hcl`, `init -reconfigure` (not `-migrate-state`) |
| 4 | `var.alert_email` prompt | `terraform.tfvars` lost the same way | Recreated from the example with the previous values |

## The safety check

The plan itself was the guard: only **"4 to add, 0 to change, 0 to destroy"** (the Cognito
resources) was acceptable. Anything else would have meant the recreated settings differed from
what was deployed, or that Terraform wasn't reading the real state. Iterate on the files until
the plan shows exactly the intended change, then apply. It did; nothing existing changed.

## Still open

The bootstrap stack (the state bucket) has no state any more: it no longer "knows" it created
the bucket. The bucket keeps working; `make tf-bootstrap` must not be run until the bucket is
re-imported with `terraform import` (Phase 6).

## What we learned

1. **State is the source of truth; the plan is the safety net.** Read every plan as a diff
   against reality before applying.
2. **Git-ignored config needs a backup** (here: a password-manager note). In CI/CD it should be
   generated, not hand-kept.
3. **Validation must not touch real setup.** A check that resets the backend is a bug in the check.
4. **Package managers change.** "Command not found" after an install that printed nothing means
   the install didn't happen: check `brew list`, don't assume PATH.

## Interview version

"A Terraform plan wouldn't run: git-ignored backend and variable files had been lost, and my own
validation target had reset the backend. I rebuilt the backend config from the real S3 bucket,
confirmed the state object existed, reconnected with init -reconfigure, and used the plan as the
gate: only '4 to add, 0 to change, 0 to destroy' was acceptable. Then I fixed the tooling and
documented the recovery."

## Follow-up, Phase 6c (2026-11-26)

The bootstrap stack had no state at all, and its state would have lived in a local,
git-ignored file again: the same class of risk. Phase 6c gives it a home in the state bucket (key `bootstrap/terraform.tfstate`) with
Terraform `import` blocks that adopt the existing bucket, gated on a plan of "6 to import, 1 to change, 0 to destroy".
`make tf-backend-hcl` regenerates `envs/dev/backend.hcl` from the bootstrap outputs, so a lost
`backend.hcl` is now a one-command fix. `terraform.tfvars` still needs the manual backup.

## Links

Phase 2c guide (Step 2 note) · Makefile (`tf-check`, `tf-init`, `TFLINT`) · Incident 0003 ·
Notion: Phase 2 review, Q&A, Interview Stories STAR #3
