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
| [0005](0005-terraform-plan-blocked-lost-config.md) | 2026-11-22 | 2c | Terraform plan blocked | Lost git-ignored config (from 0003) + validation reset the backend + tflint left Homebrew | Resolved; bootstrap re-import pending |
| [0006](0006-similarity-floor-cannot-separate.md) | 2026-11-23 | 3 | Off-topic questions score above real ones | Cosine similarity measures topic, not answerability | Mitigated (gate on outcomes) |
| [0007](0007-eval-top-score-bug.md) | 2026-11-24 | 4 | Evaluation misreported top scores; latency false alarms | "First result = best match" assumption; laptop timing noise | Fixed (write-up corrected) |
| [0008](0008-stale-eval-label.md) | 2026-11-24 | 4 | One question failed retrieval under every setting | Label written from an older edition of the document | Fixed; audit of 5 cases pending |

**Adding one:** next number, the same headings (Summary, Impact or Evidence, Root cause,
Resolution, What we learned, Interview version, Links), a row in this table, and a link from the
phase guide where it happened.
