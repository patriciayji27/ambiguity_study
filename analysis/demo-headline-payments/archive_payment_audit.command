#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
cd "$SCRIPT_DIR"

uv run python verify_payment_outputs.py

uv run python archive_payment_audit.py
