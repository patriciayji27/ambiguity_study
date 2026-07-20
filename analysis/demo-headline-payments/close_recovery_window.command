#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
cd "$SCRIPT_DIR"

if [[ ! -f payment_policy.json ]]; then
  print -u2 "Missing payment_policy.json."
  print -u2 "Copy payment_policy.example.json and record the written approval first."
  exit 1
fi

set +e
./run_payment_pipeline.command
pipeline_status=$?
set -e

if [[ $pipeline_status -eq 0 ]]; then
  print "\nAll completed participants had exact recovered bonuses; no fallback was used."
  exit 0
fi
if [[ $pipeline_status -ne 2 ]]; then
  print -u2 "The data refresh or exact-payment pipeline failed unexpectedly."
  exit $pipeline_status
fi

print "\nApplying the approved post-window fallback policy..."
uv run python finalize_after_recovery.py --policy payment_policy.json

print "\nVerifying every exact and fallback payment row..."
uv run python verify_payment_outputs.py

print "\nPAYMENT WORKFLOW READY AND VERIFIED UNDER THE APPROVED POLICY."
print "  $SCRIPT_DIR/output/payments.csv"
print "  $SCRIPT_DIR/output/prolific_bonus_upload.csv"
