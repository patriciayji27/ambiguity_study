from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

import finalize_after_recovery
import compute_payments
import verify_payment_outputs


FIELDS = [
    "prolific_pid",
    "submission_id",
    "completed",
    "payment_status",
    "bonus_computed",
    "payment_method",
    "n_trials_nonpractice_recovered",
    "payoff_validation_issues",
    "bonus_trial_components",
    "bonus_trial_payoffs",
    "bonus_trial_contribs_usd",
    "base_usd",
    "bonus_usd",
    "total_usd",
    "amount_to_pay_usd",
]


def approved_policy(**updates):
    policy = {
        "status": "APPROVED",
        "drawPool": "32-non-practice",
        "bonusSeedSalt": "demo-headline-v4-bonus",
        "recoveryWindowStart": "2026-07-01",
        "recoveryWindowEnd": "2026-07-18",
        "fallbackBonusUsd": 8,
        "approvedBy": ["Study owner", "Alex"],
        "approvalDate": "2026-07-01",
        "irbReview": "NOT_REQUIRED",
        "rationale": "Written test policy.",
    }
    policy.update(updates)
    return policy


class PaymentCloseoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.out_dir = self.root / "output"
        self.out_dir.mkdir()
        self.readiness = self.out_dir / "payment_readiness.csv"
        self.policy = self.root / "payment_policy.json"

    def tearDown(self):
        self.temp.cleanup()

    def write_policy(self, **updates):
        self.policy.write_text(
            json.dumps(approved_policy(**updates)), encoding="utf-8")

    def write_readiness(self):
        rows = [
            {
                "prolific_pid": "participant-exact",
                "submission_id": "submission-exact",
                "completed": "True",
                "payment_status": "exact_bonus_computed",
                "bonus_computed": "True",
                "payment_method": "exact_recovered_trials",
                "n_trials_nonpractice_recovered": "32",
                "payoff_validation_issues": "0",
                "bonus_trial_components": "trial-a;trial-b;trial-c",
                "bonus_trial_payoffs": "100;0;60",
                "bonus_trial_contribs_usd": "5.00;0.00;1.00",
                "base_usd": "5.00",
                "bonus_usd": "6.00",
                "total_usd": "11.00",
                "amount_to_pay_usd": "11.00",
            },
            {
                "prolific_pid": "participant-fallback",
                "submission_id": "submission-fallback",
                "completed": "True",
                "payment_status": "exact_trial_data_missing",
                "bonus_computed": "False",
                "payment_method": "",
                "n_trials_nonpractice_recovered": "0",
                "payoff_validation_issues": "0",
                "bonus_trial_components": "",
                "bonus_trial_payoffs": "",
                "bonus_trial_contribs_usd": "",
                "base_usd": "5.00",
                "bonus_usd": "",
                "total_usd": "",
                "amount_to_pay_usd": "",
            },
        ]
        with self.readiness.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)

    def test_unapproved_policy_is_blocked(self):
        self.policy.write_text(
            json.dumps(approved_policy(status="UNAPPROVED")), encoding="utf-8")
        with self.assertRaises(SystemExit):
            finalize_after_recovery.load_policy(
                self.policy, date.fromisoformat("2026-07-19"))

    def test_future_recovery_deadline_is_blocked(self):
        self.write_policy(recoveryWindowEnd="2026-07-20")
        with self.assertRaises(SystemExit):
            finalize_after_recovery.load_policy(
                self.policy, date.fromisoformat("2026-07-19"))

    def test_exact_and_fallback_rows_finalize_and_verify(self):
        self.write_policy()
        self.write_readiness()
        finalize_after_recovery.finalize(
            self.readiness,
            self.policy,
            self.out_dir,
            today=date.fromisoformat("2026-07-19"),
        )
        verify_payment_outputs.verify(self.out_dir, expected_complete=2)

        with (self.out_dir / "payments.csv").open(
                newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(rows[0]["bonus_usd"], "6.00")
        self.assertEqual(rows[0]["payment_method"], "exact_recovered_trials")
        self.assertEqual(rows[1]["bonus_usd"], "8.00")
        self.assertEqual(
            rows[1]["payment_method"],
            "approved_flat_fallback_nonreturner",
        )

    def test_full_recovery_log_parses_against_committed_study_config(self):
        config_path = TOOLS_DIR.parents[1] / "public/demo-headline/config.json"
        component_meta = compute_payments.load_component_meta(config_path)
        assigned = sorted(
            name for name in component_meta
            if name.startswith("p55-hl-") and name.endswith("-S1")
        )
        self.assertEqual(len(assigned), 32)

        log = []
        for component in assigned:
            meta = component_meta[component]
            base_pct = float(meta["base_target_pct"])
            log.append({
                "chart": meta["chart_file"],
                "choice": "A",
                "payoff": compute_payments.js_round(1000 * base_pct / 100),
                "basePct": base_pct,
                "optionB_probability": meta["option_b_probability"],
                "optionB_won": None,
                "headline_id": meta["headline_id"],
                "headline_valence": meta["headline_valence"],
                "headline_domain": meta["headline_domain"],
                "fan": meta["fan_width"],
                "slope": meta["slope"],
            })

        trials, flags = compute_payments.extract_recovered_trials(
            log, {"sequence": assigned}, component_meta)
        self.assertEqual(flags, [])
        self.assertEqual(len(trials), 32)
        self.assertEqual(
            sum(trial["kind"] == "main" for trial in trials), 30)
        self.assertEqual(
            sum(trial["kind"] == "attention_check" for trial in trials), 2)
        self.assertTrue(all(
            compute_payments.validate_trial(trial) is None
            for trial in trials
        ))
        bonus_cents, selected, bonus_flags = compute_payments.compute_bonus(
            trials, "synthetic-participant", compute_payments.BONUS_SEED_SALT)
        self.assertIsNotNone(bonus_cents)
        self.assertEqual(len(selected), 3)
        self.assertFalse(any(
            flag.startswith("exact_bonus_not_computed")
            for flag in bonus_flags
        ))


if __name__ == "__main__":
    unittest.main()
