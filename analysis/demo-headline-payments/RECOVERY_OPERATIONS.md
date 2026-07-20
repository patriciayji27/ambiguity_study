# Recovery Operations Runbook

## Production preflight

Do not invite participants until all of these checks pass:

1. The GitHub Pages deployment for the current `main` commit is successful.
2. This URL returns the recovery study:

   `https://patriciayji27.github.io/ambiguity_study/demo-headline-recovery/`

3. In ReVISit, data collection is enabled for `demo-headline-recovery`, the
   study navigator is disabled, and public analytics is disabled.
4. A dry-run recovery file has appeared in Firebase under
   `prod-demo-headline-recovery/participants/`.
5. One corrected `demo-headline` trial has been tested: Next remains locked
   until a choice is made, and the submitted answer contains
   `investment-choice` and `trial-payoff`.
6. The production browser console has no Firebase App Check 403 warning. If it
   does, register the web app's reCAPTCHA v3 secret in Firebase App Check and
   repeat the dry run before recruiting.

## Paste-ready recovery dry run

Open the deployed site on `patriciayji27.github.io`. In that tab's browser
console, paste:

```js
localStorage.setItem('hl_study_trial_log', JSON.stringify([
  {
    time: '2026-07-19T12:00:00.000Z',
    chart: 'C01-S1.png',
    choice: 'B',
    payoff: 100,
    basePct: 3.5,
    optionB_probability: 0.55,
    optionB_expected_return_pct: 5.5,
    optionB_won: true,
    cumulative: 100,
    headline_id: 'NEG01',
    headline_valence: 'slight_negative',
    headline_domain: 'policy',
    fan: 'tight',
    offset: '-2',
    slope: 'positive'
  },
  {
    time: '2026-07-19T12:01:00.000Z',
    chart: 'C02-S1.png',
    choice: 'B',
    payoff: 0,
    basePct: 4,
    optionB_probability: 0.55,
    optionB_expected_return_pct: 5.5,
    optionB_won: false,
    cumulative: 100,
    headline_id: 'NEG02',
    headline_valence: 'slight_negative',
    headline_domain: 'policy',
    fan: 'tight',
    offset: '-1.5',
    slope: 'positive'
  }
]));
localStorage.setItem('hl_study_cumulative_pnl', '100');
```

Then open this test URL:

```text
https://patriciayji27.github.io/ambiguity_study/demo-headline-recovery/?PROLIFIC_PID=TEST_RECOVERY_PREFLIGHT&STUDY_ID=TEST_RECOVERY_PREFLIGHT&SESSION_ID=TEST_RECOVERY_PREFLIGHT
```

Select **Recover stored trial data**, then **Submit recovery**, then finish the
study. Confirm Firebase contains a new recovery participant file whose answer
includes:

- `recovery-status = found`
- `recovered-trial-count = 2`
- a nonempty `recovered-trial-log`

Delete only this clearly named test session before recruiting. Never seed or
edit a real participant's log.

## Prolific recovery study

Before creating the paid recovery study, confirm the original 50 submissions
have been approved so their original $5 base rewards are not delayed.

Configure the recovery study with:

- An allowlist containing exactly the 50 original `PROLIFIC_PID` values.
- A completion time of approximately two minutes and a separate small base
  reward approved by the study owner.
- The recovery URL:

```text
https://patriciayji27.github.io/ambiguity_study/demo-headline-recovery/?PROLIFIC_PID={{%PROLIFIC_PID%}}&STUDY_ID={{%STUDY_ID%}}&SESSION_ID={{%SESSION_ID%}}
```

- Participant instructions: use the same browser and device as the original
  study and do not clear site data first.

Message the same participants through the original study. Send at most one
mid-window reminder unless the approved protocol says otherwise.

Creating the paid study, approving submissions, and sending messages are
external financial/recruitment actions and must be reviewed immediately before
submission.

## Monitor recovery

From `analysis/demo-headline-payments`, run:

```bash
./run_payment_pipeline.command
```

While any completed participant is missing an exact log, the command exits 2,
prints `PAYMENT WORKFLOW BLOCKED`, and updates
`output/payment_readiness.csv`. This is expected during recovery. Track:

- `payment_status = exact_bonus_computed`: exact recovery is ready.
- `payment_status = exact_trial_data_missing`: no complete exact log yet.
- `attention_check_data_status = complete`: both attention records recovered.

`payment_readiness.csv` is a monitoring file, not a bulk-payment file.

## Close the recovery window

If all 50 exact logs are available, `run_payment_pipeline.command` writes and
verifies the final files without a fallback.

If the approved deadline passes first:

1. Copy `payment_policy.example.json` to the ignored
   `payment_policy.json`.
2. Record the written fallback decision and set `status` to `APPROVED`.
3. Run:

```bash
./close_recovery_window.command
```

The command refreshes both Firebase folders, preserves exact bonuses for
returners, applies the approved flat fallback only to completed non-returners,
and validates all 50 rows. It refuses to run before the deadline or with a
pending policy.

## Before and after payment

Upload only `output/prolific_bonus_upload.csv`; it contains bonus amounts
keyed by `SESSION_ID`. Do not upload `amount_to_pay_usd`, because the
original $5 base reward is handled by approval of the original submission.

After the upload is confirmed:

1. Run `./archive_payment_audit.command`.
2. Move the resulting ignored audit archive to institution-approved encrypted
   storage.
3. Disable public Firebase Storage reads.
4. Configure `FIREBASE_SERVICE_ACCOUNT` outside the repository and verify the
   downloader in service-account mode.
