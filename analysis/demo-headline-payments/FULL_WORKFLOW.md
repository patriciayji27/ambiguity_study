# Complete Headline-Study Payment Workflow

## Current status

The 50 completed original sessions contain no recorded iframe choices or
realized trial payoffs. Final bonuses cannot be calculated from Firebase alone.
The exact records may still exist in each participant's browser under
`hl_study_trial_log`.

## One unavoidable recovery step

Deploy the repository version containing:

- `public/demo-headline-recovery/`
- the `demo-headline-recovery` entry in `public/global.json`
- the corrected original trial HTML under `public/demo-headline/`

Push these files to the repository's `main` branch. The existing GitHub Pages
action builds and deploys that branch. In the deployed ReVISit administration
controls for `demo-headline-recovery`, enable data collection and disable the
study navigator before inviting participants.

The recovery study uses the same protocol and hostname as the original study,
so it can read the same browser `localStorage`. Use this Prolific URL:

```text
https://patriciayji27.github.io/ambiguity_study/demo-headline-recovery/?PROLIFIC_PID={{%PROLIFIC_PID%}}&STUDY_ID={{%STUDY_ID%}}&SESSION_ID={{%SESSION_ID%}}
```

Ask the original participants to open that link with the same browser and
device they used for the headline study. They should not clear site data before
opening it. This participant action cannot be replaced by an API call because
the missing records are stored on their devices, not in Firebase.

## One command after recovery

From `analysis/demo-headline-payments`, run:

```bash
./run_payment_pipeline.command
```

The command performs the entire remaining workflow:

1. Refreshes original participant files from Firebase.
2. Refreshes `prod-demo-headline-recovery/participants/` from Firebase.
3. Matches recovery logs to original sessions by `PROLIFIC_PID`.
4. Requires all 32 non-practice choices and realized payoffs.
5. Cross-checks every payoff against the assigned study configuration.
6. Draws exactly three trials reproducibly and applies the promised formula.
7. Requires all 50 completed participants to be ready.

When all 50 are ready, the command prints `PAYMENT WORKFLOW READY` and writes:

- `output/payments.csv`: final base, bonus, total, and selected-trial audit.
- `output/prolific_bonus_upload.csv`: headerless `SESSION_ID,bonus` upload.

If even one completed participant is not ready, the command prints
`PAYMENT WORKFLOW BLOCKED`, exits with code 2, and writes only:

- `output/PAYMENT_BLOCKED.txt`
- `output/payment_readiness.csv`
- `output/participant_data_audit.csv`
- `output/trials_long.csv`

Never issue bonuses unless the command prints `PAYMENT WORKFLOW READY`.
