# Investigations and incidents

One file per problem worth learning from: what happened, how it was diagnosed, the root cause,
what changed so it can't happen again, and a short "interview version". Bigger diagnoses with
several competing hypotheses are written as investigations (0001); the rest as short incident
reports. Decisions that follow live in `docs/adr/`.

| # | Date | Phase | What happened | Root cause | Status |
|---|---|---|---|---|---|
| [0001](0001-retrieval-quality.md) | 2026-11-21 | 1 / 2a | An answer cited a source that didn't support it | Dirty PDF data: ligatures, headers, ToC text, link lists, overlapping sources | Fixed, re-measured |
| [0002](0002-bedrock-quota-zero.md) | 2026-11-18 | 0 | Every Bedrock call refused | New-account hold: quotas applied at 0, not adjustable | Open (AWS case) |
| [0003](0003-finder-overwrite-deleted-files.md) | 2026-11-19 | 1 | Files deleted from the repo | Finder "Replace" swaps whole folders | Resolved |
| [0004](0004-prune-could-delete-other-documents.md) | 2026-11-21 | 1 | `--prune` on one file would delete all other documents | Prune's idea of "everything" was wrong for single files | Fixed before release |
| [0005](0005-terraform-plan-blocked-lost-config.md) | 2026-11-22 | 2c | Terraform plan blocked | Lost git-ignored config (from 0003) + validation reset the backend + tflint left Homebrew | Resolved; bootstrap state in S3 since 6c |
| [0006](0006-similarity-floor-cannot-separate.md) | 2026-11-23 | 3 | Off-topic questions score above real ones | Cosine similarity measures topic, not answerability | Mitigated (gate on outcomes) |
| [0007](0007-eval-top-score-bug.md) | 2026-11-24 | 4 | Evaluation misreported top scores; latency false alarms | "First result = best match" assumption; laptop timing noise | Fixed (write-up corrected) |
| [0008](0008-stale-eval-label.md) | 2026-11-24 | 4 | One question failed retrieval under every setting | Label written from an older edition of the document | Fixed; audit of 5 cases pending |
| [0009](0009-agent-retries-the-wrong-questions.md) | 2026-11-25 | 5b | Agent scored 100% but improved no answer; +60% tokens | Retry signal can't separate "model failed" from "off-topic"; exact-sentence refusal check | Decided (pipeline stays default); follow-ups open |
| [0010](0010-stronger-model-followed-an-injection.md) | 2026-11-25 | 5b | A 7B model answered better but followed a "developer mode" injection | Prompt covered injected sources, not an injected question; stronger models comply more | Fixed (prompt rule, measured on both models) |
| [0011](0011-helm-chart-missing-from-merge.md) | 2026-11-26 | 6b / 6c | 6c CI failed on a Helm chart it didn't touch | 6c branched from main while the 6b PR was still open (blocked by 0012) | Fixed (6b merged, 6c rebased) |
| [0012](0012-no-patched-base-image.md) | 2026-11-26 | 6c | trivy blocked the web image: 5 CRITICAL, 15 HIGH | New CVEs in nginx and Alpine; no patched nginx-unprivileged image published | Mitigated; nginx exceptions recheck 2026-12-03 |
| [0013](0013-oidc-provider-already-existed.md) | 2026-11-26 | 6c | `tf-apply` failed: OIDC provider already exists | One provider per URL per account; a per-project stack tried to own it | Fixed (data source); budget drift to verify |
| [0014](0014-github-oidc-immutable-subject.md) | 2026-11-26 | 6c | First ECR push: `Not authorized to perform sts:AssumeRoleWithWebIdentity` | GitHub's immutable OIDC `sub` (owner@id/repo@id) vs a name-only trust policy | Fixed |
| [0015](0015-nginx-exits-when-api-name-unresolved.md) | 2026-11-27 | 7a | UI down: nginx `host not found in upstream "api"` | nginx resolves proxy_pass names once at start-up and exits if one is missing | Fixed (resolve per request) |

**Adding one:** next number, the same headings (Summary, Impact or Evidence, Root cause,
Resolution, What we learned, Interview version, Links), a row in this table, and a link from the
phase guide where it happened.
