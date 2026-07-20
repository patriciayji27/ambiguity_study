# Headline Study Payment Policy

## Fixed decisions

- Draw pool: all 32 non-practice investment trials (30 main trials and two
  embedded attention checks).
- Draw size: exactly three trials per participant.
- Bonus formula: `0.10 * max(0, realized payoff - 50)` dollars per selected
  trial, summed and capped at $15.
- Base reward: $5 for an approved completed original submission. Prolific pays
  this base reward separately from the bonus upload.
- Bonus seed salt: `demo-headline-v4-bonus`. This value is permanent and the
  code does not accept an environment override.

The 32-trial pool is the literal reading of the participant instructions,
which say three of the 32 post-practice investment trials will be selected.

## Decision still requiring written approval

Before closing recovery with a fallback, the study owner and Alex must record:

1. The recovery window start and end dates.
2. The flat fallback bonus for completed participants whose exact browser log
   was not recovered, from $0 through the promised $15 maximum.
3. Who approved the decision and when.
4. Whether IRB review was not required or was completed.

Copy `payment_policy.example.json` to the ignored local file
`payment_policy.json` and fill it in. Set `status` to `APPROVED` only after
the decision exists in writing. `close_recovery_window.command` refuses to
create payment files while the policy is incomplete, unapproved, or before
the recorded recovery end date.
