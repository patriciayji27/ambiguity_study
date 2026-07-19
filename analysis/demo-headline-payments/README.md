# Demo-Headline Firebase Data and Payment Tools

These scripts download the `prod-demo-headline/participants/` objects from
Firebase Storage, audit whether the required study fields were captured, and
compute deterministic Prolific bonuses when valid trial data is available.

## Quick run

See `FULL_WORKFLOW.md` for the deployment and participant-recovery step.

From this folder, run the complete download-and-compute pipeline with:

```bash
./run_payment_pipeline.command
```

This command refreshes the original and recovery Firebase folders, calculates
only fully validated bonuses, and writes the results under `output/`. Final
`payments.csv` and `prolific_bonus_upload.csv` files appear only when every
completed original participant has an exact validated bonus. Otherwise the
command writes `PAYMENT_BLOCKED.txt` and `payment_readiness.csv` and exits.
It does not issue payments or upload anything to Prolific.

## Current data warning

The Firebase data downloaded on July 18, 2026 contains 55 Prolific sessions:
50 complete and 5 incomplete. The completed allocation is 26 p55 and 24 p75.
There are also two non-Prolific test sessions.

None of the 1,632 started trial records contains `investment-choice` or
`trial-payoff`. The risk-precheck answers are also absent. The iframe choices
are also absent from ReVISit provenance and window-event records, so exact
performance bonuses cannot be reconstructed from the downloaded Firebase
files. `compute_payments.py` detects this condition, writes the audit, and
refuses to fabricate a payment result.

The original trial page did successfully preserve each non-practice choice
and generated payoff under `hl_study_trial_log` in the participant's browser
`localStorage`. The companion `public/demo-headline-recovery/` study can send
that exact log to ReVISit when the participant opens it on the same browser,
device, and study origin.

The participant data above was collected with study HTML that loaded the
ReVISit communication library from a path that did not exist. The corrected
library import is:

```html
<script src="../../revisitUtilities/revisit-communicate.js"></script>
```

That deployed version tried `../../revisit-communicate.js` and
`/revisit-communicate.js`. Its fallback `revisit-data` message was not handled
by ReVISit's iframe controller, so choices remained in each participant's
browser `localStorage` and were never written to Firebase. The local study was
corrected in version `4.1.4-revisit-capture-fix`; the correction only applies
to sessions collected after that version is deployed.

## Setup

Python 3.9 or newer is supported. From the repository root:

```bash
python3 -m venv analysis/demo-headline-payments/.venv
source analysis/demo-headline-payments/.venv/bin/activate
python3 -m pip install -r analysis/demo-headline-payments/requirements.txt
```

The downloader itself uses only Python's standard library. `pandas` is needed
for the audit and payment CSVs.

## Download Firebase data

```bash
python3 analysis/demo-headline-payments/download_firebase_data.py
```

Defaults:

- Bucket: `financial-uncertainty.firebasestorage.app`
- Prefix: `prod-demo-headline/participants/`
- Local data: `analysis/demo-headline-payments/data/`

The script maintains `data/.firebase-sync-manifest.json`. Re-running it only
downloads new or changed object generations; downloads are written atomically
and checked against Firebase size and MD5 metadata.

The current Storage rules permit public reads, so the REST download does not
need an API key or service account. A Firebase web API key identifies a project
but does not authorize access to private participant data.

After public reads are disabled, create a Firebase service-account key, keep it
outside this repository, and run:

```bash
python3 -m pip install firebase-admin
export FIREBASE_SERVICE_ACCOUNT="/absolute/path/financial-uncertainty-sa.json"
python3 analysis/demo-headline-payments/download_firebase_data.py
```

Useful checks:

```bash
python3 analysis/demo-headline-payments/download_firebase_data.py --dry-run
python3 analysis/demo-headline-payments/download_firebase_data.py --force
```

## Audit participant data

```bash
python3 analysis/demo-headline-payments/compute_payments.py --audit-only
```

This writes `output/participant_data_audit.csv`, including completion status,
arm, whether a session came from Prolific, trial counts, captured-answer counts,
and data-quality issues. Data and output folders are ignored by Git.

## Compute payments

For newly collected sessions with verified ReVISit trial answers, run:

```bash
python3 analysis/demo-headline-payments/compute_payments.py
```

The script automatically uses `public/demo-headline/config.json`. Outputs are:

- `payment_readiness.csv`: always written; one audit row per participant.
- `payments.csv`: final complete-session payment list, written only when all
  completed participants have exact validated bonuses.
- `prolific_bonus_upload.csv`: final headerless `SESSION_ID,bonus` rows,
  written only with `payments.csv`.
- `PAYMENT_BLOCKED.txt`: explains why final payment files were withheld.
- `trials_long.csv`: one row per participant and captured trial.
- `validation_issues.csv`: only created when a recorded payoff disagrees with
  the payoff implied by the study config.
- `participant_data_audit.csv`: always created before payment computation.

Non-Prolific test sessions are excluded by default. Incomplete sessions remain
in `payments.csv` with blank, uncomputed bonus fields and a manual-review flag
unless `--include-incomplete` is supplied.

The `bonus_computed` column is the payment gate. It is true only when all 32
non-practice choices and realized payoffs are available and every payoff
passes the config cross-check. A participant with an incomplete, missing, or
invalid exact log is excluded from `prolific_bonus_upload.csv`; the script does
not substitute a mean, maximum, or flat bonus.

Attention-check columns distinguish assignment from recovery. Every normal
session has two assigned attention checks, but `attention_checks_correct` is
left blank until both exact responses have been recovered. `0/0` is never used
as a score. Likewise, `amount_to_pay_usd` remains blank unless
`payment_status=exact_bonus_computed`.

`prolific_bonus_upload.csv` uses the Prolific submission ID stored as
`SESSION_ID`, not `PROLIFIC_PID`, because Prolific's bulk bonus tool requires
submission IDs. Bonus payments cannot be refunded, so verify the amount, row
count, and total before submitting the file.

## Recover the July 2026 trial logs

1. Deploy `demo-headline-recovery` on the same ReVISit site/origin that hosted
   `demo-headline`.
2. Invite each original participant through Prolific with `PROLIFIC_PID`,
   `STUDY_ID`, and `SESSION_ID` in the URL. Tell participants to use the same
   browser and device as before.
3. After the recovery submissions arrive, download them from Firebase:

```bash
cd analysis/demo-headline-payments
uv run python download_firebase_data.py \
  --prefix prod-demo-headline-recovery/participants/ \
  --data-dir recovery-data
```

4. Merge original and recovered records and compute exact bonuses:

```bash
uv run python compute_payments.py --recovery-data-dir recovery-data
```

When recovery is complete, review `output/payments.csv` and
`output/prolific_bonus_upload.csv`. Before then, use
`output/payment_readiness.csv` only to track recovery; it is not a payment list.

## Payment rule

- Base: $5.00 for full participation.
- Bonus: three of the 32 non-practice investment trials are selected
  deterministically from a hash of `BONUS_SEED_SALT` and `PROLIFIC_PID`.
- Each selected trial contributes `0.10 * max(0, payoff - 50)` dollars.
- The two practice rounds are excluded. The 30 ordinary trials and two
  embedded attention checks are included because the instructions say three
  of the 32 investment trials are selected.
- The final bonus is capped at the separately promised $15 maximum. This cap
  matters if the positive attention-check trial is selected.

Keep `BONUS_SEED_SALT` unchanged after any payment is issued. The default is
`demo-headline-v4-bonus`.
