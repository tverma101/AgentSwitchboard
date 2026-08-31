# Usage attribution and labels

## Symptom

Usage totals were technically correct inside FCC, but a downstream usage view
could not tell FCC-routed traffic from native Codex traffic. Rows for the same
provider and model were also combined even when they came through different
wire APIs or authenticated accounts.

## Root cause

The `usage_events` ledger previously grouped only by `provider_id` and `model`.
It had no persisted source or per-event account identity. FCC's connected
OpenAI account is owned by the process-lifetime `OpenAIAuthManager`, while
native Codex account snapshots are a separate subsystem; the usage ledger did
not make that boundary visible to consumers.

## Current behavior

- New events use the stable source id `fcc_proxy` and display as `FCC proxy`.
- Model breakdowns are grouped by provider, exact model, wire API, source, and
  account fingerprint.
- Connected OpenAI usage receives a stable `acct_<12 hex characters>`
  fingerprint derived from the account id. Tokens, account ids, and email
  addresses are never written to the usage ledger.
- Events without an available account identity remain recorded and are labeled
  `Account not identified`; attribution metadata cannot make a request fail.
- Legacy `usage_events` databases receive the new columns in place. Existing
  rows are preserved and receive the FCC source default, but they remain
  account-unidentified because historical account identity is not reconstructed.
- Native Codex usage is intentionally not folded into this ledger.

## Validation

The usage tests cover account/API separation, record-time account resolution,
resolver failure tolerance, and migration of the old schema. Admin and terminal
surfaces render the source, wire API, and account label explicitly.

## Residual boundary

Historical events cannot be assigned an account fingerprint after the fact.
They are clearly marked as unidentified rather than guessed from current
credentials.
