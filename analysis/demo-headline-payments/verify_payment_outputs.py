#!/usr/bin/env python3
"""Validate final payment and Prolific bonus files before upload."""

from __future__ import annotations

import argparse
import csv
import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "output"
MONEY = Decimal("0.01")
BASE_USD = Decimal("5.00")
MAX_BONUS_USD = Decimal("15.00")


def fail(message: str) -> "NoReturn":
    raise SystemExit(f"PAYMENT VERIFICATION FAILED: {message}")


def money(value, field: str) -> Decimal:
    try:
        return Decimal(str(value)).quantize(MONEY, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        fail(f"{field} is not a valid dollar amount: {value!r}")


def is_true(value) -> bool:
    return str(value).strip().lower() == "true"


def split_values(value) -> list[str]:
    return [part for part in str(value or "").split(";") if part != ""]


def expected_contribution(payoff: Decimal) -> Decimal:
    return (Decimal("0.10") * max(Decimal("0"), payoff - Decimal("50"))).quantize(
        MONEY, rounding=ROUND_HALF_UP)


def validation_issue_rows(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def verify(out_dir: Path, expected_complete: int) -> Path:
    pay_path = out_dir / "payments.csv"
    upload_path = out_dir / "prolific_bonus_upload.csv"
    if not pay_path.is_file() or not upload_path.is_file():
        fail("payments.csv and prolific_bonus_upload.csv must both exist")
    issues = validation_issue_rows(out_dir / "validation_issues.csv")
    if issues:
        fail(f"{len(issues)} row(s) remain in validation_issues.csv")

    with pay_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != expected_complete:
        fail(f"expected {expected_complete} completed rows, found {len(rows)}")

    policy_snapshot_path = out_dir / "fallback_policy_applied.json"
    fallback_amount = None
    if policy_snapshot_path.is_file():
        try:
            policy = json.loads(
                policy_snapshot_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            fail(f"fallback policy snapshot is unreadable: {exc}")
        if policy.get("status") != "APPROVED":
            fail("fallback policy snapshot is not approved")
        if policy.get("drawPool") != "32-non-practice":
            fail("fallback policy snapshot has the wrong draw pool")
        if policy.get("bonusSeedSalt") != "demo-headline-v4-bonus":
            fail("fallback policy snapshot has the wrong bonus seed salt")
        fallback_amount = money(policy.get("fallbackBonusUsd"),
                                "policy fallbackBonusUsd")

    seen: set[str] = set()
    exact_count = 0
    fallback_count = 0
    bonus_total = Decimal("0")
    total_with_base = Decimal("0")
    expected_upload: dict[str, Decimal] = {}

    for row_number, row in enumerate(rows, start=2):
        if not is_true(row.get("completed")):
            fail(f"row {row_number} is not a completed original session")
        submission_id = str(row.get("submission_id") or "").strip()
        if not submission_id:
            fail(f"row {row_number} has no submission_id/SESSION_ID")
        if submission_id in seen:
            fail(f"row {row_number} duplicates a submission_id")
        seen.add(submission_id)

        base = money(row.get("base_usd"), "base_usd")
        bonus = money(row.get("bonus_usd"), "bonus_usd")
        total = money(row.get("total_usd"), "total_usd")
        amount = money(row.get("amount_to_pay_usd"), "amount_to_pay_usd")
        if base != BASE_USD:
            fail(f"row {row_number} base payment is not $5")
        if bonus < 0 or bonus > MAX_BONUS_USD:
            fail(f"row {row_number} bonus is outside $0-$15")
        if total != base + bonus or amount != total:
            fail(f"row {row_number} base, bonus, and total do not reconcile")

        method = row.get("payment_method")
        if method == "exact_recovered_trials":
            components = split_values(row.get("bonus_trial_components"))
            payoff_values = split_values(row.get("bonus_trial_payoffs"))
            contribution_values = split_values(
                row.get("bonus_trial_contribs_usd"))
            if not (len(components) == len(payoff_values) ==
                    len(contribution_values) == 3):
                fail(f"row {row_number} does not contain exactly three draws")
            expected_parts = [
                expected_contribution(money(value, "bonus_trial_payoffs"))
                for value in payoff_values
            ]
            recorded_parts = [
                money(value, "bonus_trial_contribs_usd")
                for value in contribution_values
            ]
            if expected_parts != recorded_parts:
                fail(f"row {row_number} selected-trial contributions are wrong")
            expected_bonus = min(MAX_BONUS_USD, sum(expected_parts, Decimal("0")))
            if bonus != expected_bonus:
                fail(f"row {row_number} bonus does not match its three payoffs")
            if row.get("payment_status") != "exact_bonus_computed":
                fail(f"row {row_number} exact payment status is inconsistent")
            if not is_true(row.get("bonus_computed")):
                fail(f"row {row_number} exact bonus is not marked computed")
            if int(row.get("n_trials_nonpractice_recovered") or 0) != 32:
                fail(f"row {row_number} exact bonus does not have 32 trials")
            if int(row.get("payoff_validation_issues") or 0) != 0:
                fail(f"row {row_number} exact bonus has validation issues")
            exact_count += 1
        elif method == "approved_flat_fallback_nonreturner":
            if fallback_amount is None:
                fail("fallback row exists without fallback_policy_applied.json")
            if bonus != fallback_amount:
                fail(f"row {row_number} does not match the approved fallback")
            if row.get("payment_status") != "exact_trial_data_missing":
                fail(f"row {row_number} fallback status is inconsistent")
            if is_true(row.get("bonus_computed")):
                fail(f"row {row_number} fallback is marked as an exact bonus")
            if int(row.get("payoff_validation_issues") or 0) != 0:
                fail(f"row {row_number} fallback has validation issues")
            fallback_count += 1
        else:
            fail(f"row {row_number} has unsupported payment_method {method!r}")

        bonus_total += bonus
        total_with_base += total
        if bonus > 0:
            expected_upload[submission_id] = bonus

    actual_upload: dict[str, Decimal] = {}
    with upload_path.open(newline="", encoding="utf-8") as handle:
        for row_number, values in enumerate(csv.reader(handle), start=1):
            if len(values) != 2:
                fail(f"Prolific upload row {row_number} must have two columns")
            submission_id, raw_bonus = values
            if submission_id in actual_upload:
                fail(f"Prolific upload row {row_number} duplicates SESSION_ID")
            actual_upload[submission_id] = money(raw_bonus, "upload bonus")
    if actual_upload != expected_upload:
        fail("Prolific bonus upload does not exactly match positive bonuses")

    report_path = out_dir / "PAYMENT_VERIFIED.txt"
    report_path.write_text(
        "PAYMENT OUTPUT VERIFIED\n"
        "=======================\n\n"
        f"Completed participants: {len(rows)}\n"
        f"Exact recovered bonuses: {exact_count}\n"
        f"Approved flat fallbacks: {fallback_count}\n"
        f"Prolific bonus upload rows: {len(actual_upload)}\n"
        f"Bonus total: ${bonus_total:.2f}\n"
        f"Base plus bonus total: ${total_with_base:.2f}\n\n"
        "All exact rows were recomputed from their three selected payoffs.\n"
        "All SESSION_ID values are present and unique.\n"
        "No unresolved payoff-validation rows are present.\n",
        encoding="utf-8",
    )
    print("PAYMENT OUTPUT VERIFIED")
    print(f"Completed participants: {len(rows)}")
    print(f"Exact recovered bonuses: {exact_count}")
    print(f"Approved flat fallbacks: {fallback_count}")
    print(f"Bonus total: ${bonus_total:.2f}")
    print(f"Base plus bonus total: ${total_with_base:.2f}")
    print(f"Wrote: {report_path}")
    return report_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate final headline-study payment files.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--expected-complete", type=int, default=50)
    args = parser.parse_args()
    verify(args.out_dir, args.expected_complete)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
