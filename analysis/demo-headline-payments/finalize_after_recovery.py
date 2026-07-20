#!/usr/bin/env python3
"""Close a blocked recovery window using an explicitly approved fallback."""

from __future__ import annotations

import argparse
import csv
import json
import os
import tempfile
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "output"
DEFAULT_POLICY = SCRIPT_DIR / "payment_policy.json"
FIXED_DRAW_POOL = "32-non-practice"
FIXED_SALT = "demo-headline-v4-bonus"
BASE_USD = Decimal("5.00")
MAX_BONUS_USD = Decimal("15.00")
MONEY = Decimal("0.01")


def fail(message: str) -> "NoReturn":
    raise SystemExit(f"POLICY CLOSEOUT BLOCKED: {message}")


def money(value, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value)).quantize(MONEY, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        fail(f"{field} is not a valid dollar amount: {value!r}")
    return parsed


def parse_date(value, field: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        fail(f"{field} must use YYYY-MM-DD")


def load_policy(path: Path, today: date) -> tuple[dict, Decimal]:
    if not path.is_file():
        fail(f"policy file not found: {path}")
    try:
        policy = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        fail(f"policy file is unreadable: {exc}")

    if policy.get("status") != "APPROVED":
        fail("policy status must be APPROVED")
    if policy.get("drawPool") != FIXED_DRAW_POOL:
        fail(f"drawPool must remain {FIXED_DRAW_POOL}")
    if policy.get("bonusSeedSalt") != FIXED_SALT:
        fail(f"bonusSeedSalt must remain {FIXED_SALT}")

    start = parse_date(policy.get("recoveryWindowStart"), "recoveryWindowStart")
    end = parse_date(policy.get("recoveryWindowEnd"), "recoveryWindowEnd")
    if end < start:
        fail("recoveryWindowEnd cannot precede recoveryWindowStart")
    if today < end:
        fail(f"recovery window remains open through {end.isoformat()}")

    fallback = money(policy.get("fallbackBonusUsd"), "fallbackBonusUsd")
    if fallback < 0 or fallback > MAX_BONUS_USD:
        fail("fallbackBonusUsd must be between $0 and $15")

    approved_by = policy.get("approvedBy")
    if not isinstance(approved_by, list) or not any(
            str(value).strip() for value in approved_by):
        fail("approvedBy must name at least one approver")
    parse_date(policy.get("approvalDate"), "approvalDate")
    if policy.get("irbReview") in (None, "", "PENDING"):
        fail("irbReview must record the completed/not-required determination")
    if not str(policy.get("rationale") or "").strip():
        fail("rationale is required")
    return policy, fallback


def is_true(value) -> bool:
    return str(value).strip().lower() == "true"


def write_csv_atomic(path: Path, fieldnames: list[str], rows: list[dict],
                     header: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames,
                                    extrasaction="ignore")
            if header:
                writer.writeheader()
            writer.writerows(rows)
        os.replace(temp_name, path)
    except Exception:
        Path(temp_name).unlink(missing_ok=True)
        raise


def finalize(readiness_path: Path, policy_path: Path, out_dir: Path,
             today: date | None = None) -> tuple[Path, Path]:
    policy, fallback = load_policy(policy_path, today or date.today())
    if not readiness_path.is_file():
        fail(f"payment readiness file not found: {readiness_path}")

    issues_path = out_dir / "validation_issues.csv"
    if issues_path.is_file() and issues_path.stat().st_size:
        fail(f"validation issues require review: {issues_path}")

    with readiness_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = [dict(row) for row in reader]
        source_fields = list(reader.fieldnames or [])
    complete = [row for row in rows if is_true(row.get("completed"))]
    if not complete:
        fail("no completed participants were found")

    seen_submission_ids: set[str] = set()
    final_rows = []
    exact_count = 0
    fallback_count = 0
    for row in complete:
        submission_id = str(row.get("submission_id") or "").strip()
        if not submission_id:
            fail("every completed row must have a SESSION_ID/submission_id")
        if submission_id in seen_submission_ids:
            fail(f"duplicate submission_id: {submission_id}")
        seen_submission_ids.add(submission_id)

        if is_true(row.get("bonus_computed")):
            if row.get("payment_status") != "exact_bonus_computed":
                fail("bonus_computed row has an inconsistent payment_status")
            if int(row.get("n_trials_nonpractice_recovered") or 0) != 32:
                fail("exact bonus row does not contain all 32 recovered trials")
            if int(row.get("payoff_validation_issues") or 0) != 0:
                fail("exact bonus row contains payoff validation issues")
            bonus = money(row.get("bonus_usd"), "bonus_usd")
            method = "exact_recovered_trials"
            exact_count += 1
        else:
            if row.get("payment_status") != "exact_trial_data_missing":
                fail("fallback is allowed only for missing exact trial data")
            bonus = fallback
            method = "approved_flat_fallback_nonreturner"
            fallback_count += 1

        if bonus < 0 or bonus > MAX_BONUS_USD:
            fail("participant bonus is outside the promised $0-$15 range")
        final = dict(row)
        final.update({
            "payment_method": method,
            "base_usd": f"{BASE_USD:.2f}",
            "bonus_usd": f"{bonus:.2f}",
            "total_usd": f"{BASE_USD + bonus:.2f}",
            "amount_to_pay_usd": f"{BASE_USD + bonus:.2f}",
            "fallback_policy_approval_date": policy["approvalDate"],
            "fallback_policy_recovery_end": policy["recoveryWindowEnd"],
        })
        final_rows.append(final)

    extra_fields = [
        "payment_method", "fallback_policy_approval_date",
        "fallback_policy_recovery_end",
    ]
    fields = source_fields + [
        field for field in extra_fields if field not in source_fields
    ]
    pay_path = out_dir / "payments.csv"
    upload_path = out_dir / "prolific_bonus_upload.csv"
    write_csv_atomic(pay_path, fields, final_rows)
    upload_rows = [
        {"submission_id": row["submission_id"], "bonus": row["bonus_usd"]}
        for row in final_rows if money(row["bonus_usd"], "bonus_usd") > 0
    ]
    write_csv_atomic(upload_path, ["submission_id", "bonus"], upload_rows,
                     header=False)

    snapshot = dict(policy)
    snapshot["appliedAt"] = datetime.now().astimezone().isoformat()
    snapshot["completedParticipants"] = len(final_rows)
    snapshot["exactBonusParticipants"] = exact_count
    snapshot["fallbackParticipants"] = fallback_count
    (out_dir / "fallback_policy_applied.json").write_text(
        json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out_dir / "PAYMENT_BLOCKED.txt").unlink(missing_ok=True)

    print("POLICY CLOSEOUT READY")
    print(f"Completed participants: {len(final_rows)}")
    print(f"Exact recovered bonuses: {exact_count}")
    print(f"Approved flat fallbacks: {fallback_count} at ${fallback:.2f}")
    print(f"Wrote:\n  {pay_path}\n  {upload_path}")
    return pay_path, upload_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Finalize blocked headline-study payments after recovery closes.")
    parser.add_argument("--readiness", type=Path,
                        default=DEFAULT_OUTPUT_DIR / "payment_readiness.csv")
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    finalize(args.readiness, args.policy, args.out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
