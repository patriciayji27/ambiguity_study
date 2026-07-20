#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
cd "$SCRIPT_DIR"

if ! command -v uv >/dev/null 2>&1; then
  print -u2 "uv is required. Install it from https://docs.astral.sh/uv/ and run this file again."
  exit 1
fi

print "Step 1/4: Refreshing original headline-study participant data..."
uv run --with "pandas>=2.0,<3.0" python download_firebase_data.py

print "\nStep 2/4: Refreshing headline-study recovery data..."
uv run --with "pandas>=2.0,<3.0" python download_firebase_data.py \
  --prefix prod-demo-headline-recovery/participants/ \
  --data-dir recovery-data

print "\nStep 3/4: Computing exact three-trial bonuses..."
if ! uv run --with "pandas>=2.0,<3.0" python compute_payments.py \
  --recovery-data-dir recovery-data; then
  print "\nThe workflow is blocked because exact participant trial logs are missing."
  print "Read: $SCRIPT_DIR/output/PAYMENT_BLOCKED.txt"
  print "Audit only: $SCRIPT_DIR/output/payment_readiness.csv"
  print "\nNo payment file was generated."
  exit 2
fi

print "\nStep 4/4: Verifying every payment and Prolific upload row..."
uv run python verify_payment_outputs.py

print "\nPAYMENT WORKFLOW READY AND VERIFIED. Review before issuing payment:"
print "  $SCRIPT_DIR/output/payments.csv"
print "  $SCRIPT_DIR/output/prolific_bonus_upload.csv"
