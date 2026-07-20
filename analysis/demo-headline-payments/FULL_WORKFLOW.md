# Complete Headline-Study Payment Workflow

## Verified starting point

- A frozen, checksum-verified copy of the July 18 download must exist outside
  the repository before refreshing `data/`.
- The July 18 dataset contains 57 participant files: 55 Prolific sessions
  (50 complete, five incomplete) and two non-Prolific tests.
- The completed allocation is 26 p55 and 24 p75. The configured assignment
  uses `numSequences: 50` and a two-arm Latin square; completion attrition is
  why the completed subset is not exactly 25/25.
- Both representative raw-file inspection and `--audit-only` confirm zero
  captured trial answers across 1,632 started trial records.

## Fixed payment decisions

The draw pool is all 32 non-practice trials: 30 main decisions and two
attention checks. Exactly three are selected per participant. Each selected
trial contributes `0.10 * max(0, payoff - 50)` dollars, and the final bonus is
capped at $15. The permanent seed salt is
`demo-headline-v4-bonus`.

The recovery deadline and non-returner fallback are not code defaults. They
must be approved in writing using `payment_policy.json`; see
`PAYMENT_POLICY.md`.

## Deploy and preflight

The repository must contain:

- `public/demo-headline-recovery/`
- the recovery entry in `public/global.json`
- corrected `public/demo-headline/` trial and precheck HTML
- `analysis/demo-headline-payments/`

Push to `main` and wait for the GitHub Pages action to succeed. Before
inviting participants, follow every test in `RECOVERY_OPERATIONS.md`,
including one seeded test recovery and one corrected headline trial. In the
deployed ReVISit controls, enable recovery data collection, disable the study
navigator, and disable public analytics.

## Recruit recovery

Approve the original 50 completed Prolific submissions so the original $5
base payment does not wait on bonus recovery. Create a separate approximately
two-minute recovery study, restricted to those 50 original PIDs, with its own
approved small base reward.

Use:

```text
https://patriciayji27.github.io/ambiguity_study/demo-headline-recovery/?PROLIFIC_PID={{%PROLIFIC_PID%}}&STUDY_ID={{%STUDY_ID%}}&SESSION_ID={{%SESSION_ID%}}
```

Participants must use the same browser and device as the original study and
must not clear site data first. The browser action is unavoidable because the
missing exact records are not in Firebase.

## Monitor with one command

From `analysis/demo-headline-payments`, run:

```bash
./run_payment_pipeline.command
```

The command:

1. Refreshes original data from Firebase.
2. Refreshes `prod-demo-headline-recovery/participants/`.
3. Matches recovery logs by `PROLIFIC_PID`.
4. Requires and validates all 32 exact outcomes per recovered participant.
5. Draws three trials using the fixed seed.
6. Produces final files only when all completed participants are exact.
7. Recomputes every selected-trial contribution and validates the entire
   SESSION_ID-keyed Prolific upload.

During recovery, exit code 2 and `PAYMENT WORKFLOW BLOCKED` are expected.
`output/payment_readiness.csv` shows progress but is not a payment file.

## Produce final files

If all 50 recover, the normal command prints
`PAYMENT WORKFLOW READY AND VERIFIED` and writes:

- `output/payments.csv`
- `output/prolific_bonus_upload.csv`
- `output/PAYMENT_VERIFIED.txt`

If the approved deadline passes first, complete `payment_policy.json` and
run:

```bash
./close_recovery_window.command
```

That one command refreshes the data, preserves exact returner bonuses, applies
the approved flat fallback only to completed non-returners, and runs the same
verification. It cannot run with an unapproved policy or before the deadline.

Upload only `prolific_bonus_upload.csv`; Prolific approval pays the original
$5 base separately.

## After payment

Run `./archive_payment_audit.command`, move its archive to
institution-approved encrypted storage, disable public Firebase Storage
reads, and configure the downloader with a service account kept outside the
repository.
