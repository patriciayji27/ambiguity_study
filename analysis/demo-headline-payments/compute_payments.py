#!/usr/bin/env python3
from __future__ import annotations
"""
compute_payments.py
===================
Compute Prolific payments for the demo-headline study
("Investment Decision-Making Under Uncertainty: Headline Study").

Reads the ReVISit participantData JSON files downloaded from Firebase Storage
(by download_firebase_data.py), builds a tidy trial-level dataframe, and
computes each participant's payment exactly as promised in the study
introduction / consent form:

Before computing payment, the script always writes participant_data_audit.csv
and verifies that the required `investment-choice` and `trial-payoff` fields
exist. For the affected July 2026 collection, it can merge exact browser logs
exported through the companion demo-headline-recovery study. It refuses to
compute a bonus for participants whose exact trial outcomes are absent.

    Base pay:  $5.00 flat for full participation.

    Bonus:     Three of the participant's 32 non-practice decision trials are
               chosen at random.
               On each chosen trial, every hypothetical dollar gained in
               excess of $50 adds 10 cents to the bonus. There are no
               negative bonuses.

                   per-trial contribution = $0.10 * max(0, payoff - $50)
                   bonus = sum over the 3 chosen trials, in [$0, $15]

Draw pool and ceiling
---------------------
The consent describes 32 investment decision trials after the two practice
rounds, and the instructions say three "of these trials" are selected. The
draw therefore includes the 30 ordinary trials and two embedded attention
checks, while excluding practice. Because a positive attention check can pay
$240, the final sum is capped at the separately promised $15 maximum.

Determinism / auditability
--------------------------
The 3 bonus trials are drawn with a PRNG seeded by
SHA-256(BONUS_SEED_SALT + ":" + prolific_pid). Re-running the script therefore
always reproduces the identical draw and identical bonuses for every
participant, no matter the machine or the order files are read in. Change the
salt (env var BONUS_SEED_SALT) only if you deliberately want a fresh draw --
and never after bonuses have been paid.

The payoff used for payment is the outcome that was actually generated and
shown to the participant during the study (`trial-payoff` in the recorded
answers) -- that is what the instructions promise ("your choices and these
generated outcomes will determine your bonus"). As a safety net, every
recorded payoff is cross-checked against the payoff implied by the study
config (deterministic for Option A; {0,100} consistent with `optionB-won`
for Option B), and any mismatch is written to validation_issues.csv.

Inputs
------
    --data-dir   folder of participantData JSON files   (default ./data)
    --recovery-data-dir  recovery participantData files (default ./recovery-data)
    --config     path to the study config.json          (default: auto-detect)
    --out-dir    output folder                          (default ./output)
    --include-incomplete   also compute pay for participants not marked
                           complete (default: bonus fields remain blank and
                           the participant is flagged for manual review)

Outputs (in --out-dir)
----------------------
    trials_long.csv            one row per (participant x trial): the tidy
                               dataframe for later analysis steps
    payment_readiness.csv      one row per participant; always written
    payments.csv               final complete-session payment list; written
                               only when every completed participant is ready
    prolific_bonus_upload.csv  final "SESSION_ID,bonus" upload; written only
                               with payments.csv, with positive bonuses only
    PAYMENT_BLOCKED.txt        written instead of final payment files when any
                               completed participant lacks an exact valid log
    validation_issues.csv      written only if any payoff cross-check fails
    participant_data_audit.csv capture/completion audit, always written

Requires:  pip install pandas
Environment:  BONUS_SEED_SALT (optional; default "demo-headline-v4-bonus")
"""

import argparse
import hashlib
import json
import math
import os
import random
import re
import sys
from pathlib import Path

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
DEFAULT_DATA_DIR = SCRIPT_DIR / "data"
DEFAULT_RECOVERY_DATA_DIR = SCRIPT_DIR / "recovery-data"
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "output"
DEFAULT_CONFIG = REPO_ROOT / "public" / "demo-headline" / "config.json"

# --------------------------------------------------------------------------
# Payment mechanism constants (from assets/introduction.md and consent.md)
# --------------------------------------------------------------------------
BASE_PAY_CENTS = 500          # $5 flat for full participation
N_BONUS_TRIALS = 3            # trials drawn at random per participant
BONUS_THRESHOLD_DOLLARS = 50  # dollars gained in excess of this count...
CENTS_PER_EXCESS_DOLLAR = 10  # ...10 cents each
BONUS_CAP_CENTS = 1500        # stated ceiling ($15); needed if AC1 is drawn
DEFAULT_SALT = "demo-headline-v4-bonus"
EXPECTED_MAIN_TRIALS = 30
EXPECTED_NONPRACTICE_TRIALS = 32  # 30 main + 2 attention checks

TRIAL_ANSWER_KEYS = ("investment-choice", "trial-payoff")  # marks a trial record


# --------------------------------------------------------------------------
# Small coercion helpers -- ReVISit answers sometimes arrive as strings
# --------------------------------------------------------------------------
def to_float(x):
    if x is None:
        return None
    if isinstance(x, bool):
        return float(x)
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def to_bool(x):
    if isinstance(x, bool):
        return x
    if x is None:
        return None
    s = str(x).strip().lower()
    if s in ("true", "1", "yes"):
        return True
    if s in ("false", "0", "no"):
        return False
    return None


def js_round(x):
    """JavaScript Math.round: round half toward +infinity (not banker's)."""
    return int(math.floor(x + 0.5))


# --------------------------------------------------------------------------
# Study config: component name -> design metadata
# --------------------------------------------------------------------------
def find_config(explicit: str | None) -> Path | None:
    if explicit:
        p = Path(explicit)
        if p.is_file():
            return p
        sys.exit(f"--config given but file not found: {explicit}")
    for cand in (Path("config.json"),
                 Path("demo-headline/config.json"),
                 Path("../demo-headline/config.json"),
                 DEFAULT_CONFIG):
        p = cand.expanduser().resolve()
        if p.is_file():
            return p
    return None


def load_component_meta(config_path: Path | None) -> dict:
    """component name -> meta dict (empty if config unavailable)."""
    if config_path is None:
        print("NOTE: study config.json not found; payoff cross-checks and "
              "design metadata (cell, correct answer, ...) will be limited.\n")
        return {}
    with open(config_path, encoding="utf-8") as f:
        cfg = json.load(f)
    return {name: comp.get("meta", {})
            for name, comp in cfg.get("components", {}).items()}


# --------------------------------------------------------------------------
# Participant file parsing (robust to ReVISit schema variants)
# --------------------------------------------------------------------------
def iter_participant_files(data_dir: Path):
    files = set(data_dir.glob("**/*_participantData*"))
    files.update(
        p for p in data_dir.glob("**/*.json")
        if not p.name.startswith(".") and "manifest" not in p.name.lower()
    )
    return sorted(p for p in files if p.is_file())


def read_json(path: Path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        print(f"  SKIPPING unreadable file {path.name}: {exc}")
        return None


_KEY_SUFFIX = re.compile(r"_(\d+)$")


def component_name_from_key(key: str) -> tuple[str, int | None]:
    """ReVISit answer keys look like '<componentName>_<sequenceIndex>'."""
    m = _KEY_SUFFIX.search(key)
    if m:
        return key[: m.start()], int(m.group(1))
    return key, None


def extract_url_param(pdata: dict, names: tuple[str, ...]) \
        -> tuple[str | None, str | None]:
    for container_key in ("searchParams", "urlParams", "queryParams"):
        params = pdata.get(container_key) or {}
        if not isinstance(params, dict):
            continue
        for name in names:
            value = params.get(name)
            if value:
                return str(value), container_key
    return None, None


def extract_prolific_pid(pdata: dict, filename: str) -> tuple[str, str]:
    """Return (prolific_pid, source)."""
    pid, source = extract_url_param(
        pdata, ("PROLIFIC_PID", "prolific_pid", "ProlificPid"))
    if pid and source:
        return pid, source
    pid = pdata.get("participantId")
    if pid:
        # urlParticipantIdParam = PROLIFIC_PID in uiConfig, so the ReVISit
        # participantId IS the Prolific PID for participants who arrived
        # through the Prolific link.
        return str(pid), "participantId"
    stem = filename.split("_participantData")[0]
    return stem, "filename"


def extract_submission_id(pdata: dict) -> tuple[str | None, str | None]:
    """Return the Prolific submission ID used for bulk bonus payments."""
    return extract_url_param(
        pdata, ("SESSION_ID", "SUBMISSION_ID", "session_id", "submission_id"))


def assigned_trial_components(pdata: dict) -> list[str]:
    """Return trial components in the participant's realized sequence order."""
    assigned: list[str] = []
    seen: set[str] = set()

    def visit(value) -> None:
        if isinstance(value, str):
            if re.match(r"^p(?:55|75)-hl-", value) and value not in seen:
                seen.add(value)
                assigned.append(value)
            return
        if isinstance(value, list):
            for item in value:
                visit(item)
            return
        if isinstance(value, dict):
            for item in value.values():
                visit(item)

    visit(pdata.get("sequence"))
    return assigned


def recovery_payload(pdata: dict) -> list[dict] | None:
    """Extract the largest valid browser-log payload from a recovery session."""
    candidates = []
    answers = pdata.get("answers") or {}
    if not isinstance(answers, dict):
        return None
    for record in answers.values():
        if not isinstance(record, dict):
            continue
        answer = record.get("answer") or {}
        if not isinstance(answer, dict):
            continue
        raw = answer.get("recovered-trial-log")
        if raw is None:
            continue
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, list) and all(isinstance(item, dict)
                                           for item in parsed):
            candidates.append(parsed)
    return max(candidates, key=len) if candidates else None


def load_recovery_logs(data_dir: Path) -> dict[str, dict]:
    """Load exact localStorage exports, keyed by PROLIFIC_PID."""
    recovered: dict[str, dict] = {}
    if not data_dir.is_dir():
        return recovered
    for path in iter_participant_files(data_dir):
        pdata = read_json(path)
        if not isinstance(pdata, dict):
            continue
        pid, pid_source = extract_prolific_pid(pdata, path.name)
        if pid_source not in ("searchParams", "urlParams", "queryParams"):
            continue
        payload = recovery_payload(pdata)
        if payload is None:
            continue
        previous = recovered.get(pid)
        if previous is None or len(payload) > len(previous["log"]):
            recovered[pid] = {"log": payload, "file": path.name}
    return recovered


def infer_arm(pdata: dict) -> str | None:
    for tag in pdata.get("participantTags") or []:
        if tag in ("probability-arm-p55", "probability-arm-p75"):
            return tag[-3:]
    answers = pdata.get("answers") or {}
    if isinstance(answers, dict):
        for key, record in answers.items():
            component = record.get("componentName") if isinstance(record, dict) else None
            component = component or component_name_from_key(str(key))[0]
            if component.startswith(("p55-", "p75-")):
                return component[:3]
    return None


def audit_participant(path: Path, pdata: dict) -> dict:
    """Summarize whether the fields required for payment were captured."""
    pid, pid_source = extract_prolific_pid(pdata, path.name)
    submission_id, submission_id_source = extract_submission_id(pdata)
    answers = pdata.get("answers") or {}
    if not isinstance(answers, dict):
        answers = {}

    trial_records = 0
    started_trial_records = 0
    captured_trial_records = 0
    risk_records = 0
    captured_risk_records = 0
    for key, record in answers.items():
        if not isinstance(record, dict):
            continue
        component = record.get("componentName") or component_name_from_key(str(key))[0]
        answer = record.get("answer")
        answer = answer if isinstance(answer, dict) else {}
        if component.startswith(("p55-hl-", "p75-hl-")):
            trial_records += 1
            if to_float(record.get("startTime")) not in (None, 0.0):
                started_trial_records += 1
            if any(field in answer for field in TRIAL_ANSWER_KEYS):
                captured_trial_records += 1
        if component in ("p55-risk-precheck", "p75-risk-precheck"):
            risk_records += 1
            if answer:
                captured_risk_records += 1

    issues = []
    if started_trial_records and captured_trial_records == 0:
        issues.append("trial_answers_not_captured")
    elif captured_trial_records < started_trial_records:
        issues.append("some_trial_answers_not_captured")
    if risk_records and captured_risk_records == 0:
        issues.append("risk_precheck_answers_not_captured")
    if pid_source not in ("searchParams", "urlParams", "queryParams"):
        issues.append("non_prolific_or_missing_url_params")
    elif not submission_id:
        issues.append("missing_submission_id_for_bulk_bonus")

    return {
        "prolific_pid": pid,
        "submission_id": submission_id,
        "submission_id_source": submission_id_source,
        "file": path.name,
        "pid_source": pid_source,
        "is_prolific": pid_source in ("searchParams", "urlParams", "queryParams"),
        "participant_index": pdata.get("participantIndex"),
        "participant_config_hash": pdata.get("participantConfigHash"),
        "arm": infer_arm(pdata),
        "completed": pdata.get("completed") is True,
        "rejected_in_revisit": pdata.get("rejected") is True,
        "answer_records": len(answers),
        "trial_records": trial_records,
        "started_trial_records": started_trial_records,
        "captured_trial_records": captured_trial_records,
        "risk_precheck_records": risk_records,
        "captured_risk_precheck_records": captured_risk_records,
        "issues": ";".join(issues),
    }


def classify_trial(component: str, answer: dict, meta: dict) -> str:
    """'practice' | 'attention_check' | 'main'."""
    if to_bool(answer.get("is-practice-trial")) or meta.get("isPractice") \
            or "practice" in component.lower():
        return "practice"
    valence = str(answer.get("headline-valence")
                  or meta.get("headline_valence") or "")
    if meta.get("is_attention_check") or valence.startswith("attention") \
            or re.search(r"-AC\d", component):
        return "attention_check"
    return "main"


def extract_recovered_trials(
        log: list[dict], pdata: dict, comp_meta: dict) \
        -> tuple[list[dict], list[str]]:
    """Convert the original browser trial log into payment trial records."""
    assigned_order = assigned_trial_components(pdata)
    assigned = set(assigned_order)
    sequence_index = {
        component: index for index, component in enumerate(assigned_order)
    }
    chart_to_component = {}
    for component in assigned_order:
        meta = comp_meta.get(component, {})
        chart = meta.get("chart_file")
        if chart:
            chart_to_component[chart] = (component, meta)
    trials = []
    seen_components = set()
    flags = []
    ignored = 0

    # If a participant restarted the study, localStorage can contain repeated
    # components. The latest occurrence corresponds to the completed run.
    for index in range(len(log) - 1, -1, -1):
        item = log[index]
        chart = str(item.get("chart") or "")
        mapped = chart_to_component.get(chart)
        if not mapped:
            ignored += 1
            continue
        component, meta = mapped
        if component not in assigned:
            ignored += 1
            continue
        if component in seen_components:
            flags.append(f"duplicate_recovered_trial_ignored:{component}")
            continue

        choice_raw = str(item.get("choice") or "")
        choice = {"A": "A", "B": "B", "optionA": "A", "optionB": "B"}.get(
            choice_raw)
        payoff = to_float(item.get("payoff"))
        if choice is None or payoff is None:
            flags.append(f"invalid_recovered_trial_ignored:{component}")
            continue

        answer = {
            "headline-valence": item.get("headline_valence"),
            "is-practice-trial": "false",
        }
        kind = classify_trial(component, answer, meta)
        trial = {
            "answer_key": f"recovered:{index}",
            "component": component,
            "seq_index": sequence_index[component],
            "kind": kind,
            "arm": meta.get("probability_arm") or component[:3],
            "trial_id": meta.get("trial_id"),
            "cell_id": meta.get("cell_id"),
            "s_variant": (re.search(r"-(S\d)$", component).group(1)
                          if re.search(r"-(S\d)$", component) else None),
            "choice": choice,
            "payoff": payoff,
            "optionB_probability": to_float(
                meta.get("option_b_probability")),
            "recorded_optionB_probability": to_float(
                item.get("optionB_probability")),
            "optionB_won": to_bool(item.get("optionB_won")),
            "headline_id": item.get("headline_id") or meta.get("headline_id"),
            "headline_valence": (item.get("headline_valence") or
                                 meta.get("headline_valence")),
            "headline_domain": (item.get("headline_domain") or
                                meta.get("headline_domain")),
            "headline_strength": meta.get("headline_strength"),
            "congruence": meta.get("headline_visual_congruence"),
            "fan_width": item.get("fan") or meta.get("fan_width"),
            "base_offset_pp": meta.get("base_offset_pp"),
            "base_target_pct": to_float(meta.get("base_target_pct")),
            "recorded_base_target_pct": to_float(item.get("basePct")),
            "slope": item.get("slope") or meta.get("slope"),
            "difficulty_score": meta.get("difficulty_score"),
            "design_correct": meta.get("correct"),
            "start_time": None,
            "end_time": None,
            "rt_ms": None,
            "source": "recovered_local_storage",
        }
        trial["chose_correct"] = (
            None if trial["design_correct"] is None
            else ({"A": "optionA", "B": "optionB"}[choice] ==
                  trial["design_correct"])
        )
        seen_components.add(component)
        trials.append(trial)

    if ignored:
        flags.append(f"recovery_entries_outside_assigned_sequence={ignored}")
    trials.sort(key=lambda trial: trial["seq_index"])
    return trials, flags


def extract_trials(pdata: dict, comp_meta: dict) -> tuple[list[dict], list[str]]:
    """Pull every investment-trial answer record out of a participantData blob."""
    flags = []
    answers = pdata.get("answers") or {}
    if not isinstance(answers, dict):
        return [], ["answers_not_a_dict"]

    trials, seen_components = [], {}
    for key, rec in answers.items():
        if not isinstance(rec, dict):
            continue
        ans = rec.get("answer")
        if not isinstance(ans, dict) or not any(k in ans for k in TRIAL_ANSWER_KEYS):
            continue

        name_from_key, seq_idx = component_name_from_key(key)
        component = rec.get("componentName") or name_from_key
        meta = comp_meta.get(component, {})
        kind = classify_trial(component, ans, meta)

        choice_raw = ans.get("investment-choice")
        choice = {"optionA": "A", "optionB": "B"}.get(str(choice_raw), None)
        payoff = to_float(ans.get("trial-payoff"))
        b_won = to_bool(ans.get("optionB-won"))
        start = to_float(rec.get("startTime"))
        end = to_float(rec.get("endTime"))

        arm = meta.get("probability_arm")
        if arm is None and component.startswith(("p55", "p75")):
            arm = component[:3]

        trial = {
            "answer_key": key,
            "component": component,
            "seq_index": seq_idx,
            "kind": kind,
            "arm": arm,
            "trial_id": meta.get("trial_id"),
            "cell_id": meta.get("cell_id"),
            "s_variant": (re.search(r"-(S\d)$", component).group(1)
                          if re.search(r"-(S\d)$", component) else None),
            "choice": choice,
            "payoff": payoff,
            "optionB_probability": to_float(ans.get("optionB-probability")
                                            if "optionB-probability" in ans
                                            else meta.get("option_b_probability")),
            "optionB_won": b_won,
            "headline_id": ans.get("headline-id") or meta.get("headline_id"),
            "headline_valence": ans.get("headline-valence") or meta.get("headline_valence"),
            "headline_domain": ans.get("headline-domain") or meta.get("headline_domain"),
            "headline_strength": meta.get("headline_strength"),
            "congruence": meta.get("headline_visual_congruence"),
            "fan_width": meta.get("fan_width"),
            "base_offset_pp": meta.get("base_offset_pp"),
            "base_target_pct": meta.get("base_target_pct"),
            "slope": meta.get("slope"),
            "difficulty_score": meta.get("difficulty_score"),
            "design_correct": meta.get("correct"),
            "start_time": start,
            "end_time": end,
            "rt_ms": (end - start) if (start is not None and end is not None) else None,
            "source": "revisit_answers",
        }
        trial["chose_correct"] = (
            None if trial["design_correct"] is None or choice is None
            else ({"A": "optionA", "B": "optionB"}[choice] == trial["design_correct"])
        )

        # Deduplicate repeated records of the same component (e.g. restarts):
        # keep the earliest by (seq_index, startTime).
        prev = seen_components.get(component)
        if prev is None:
            seen_components[component] = trial
            trials.append(trial)
        else:
            flags.append(f"duplicate_answer:{component}")
            prev_rank = (prev["seq_index"] if prev["seq_index"] is not None else 1e18,
                         prev["start_time"] if prev["start_time"] is not None else 1e18)
            this_rank = (trial["seq_index"] if trial["seq_index"] is not None else 1e18,
                         trial["start_time"] if trial["start_time"] is not None else 1e18)
            if this_rank < prev_rank:
                trials[trials.index(prev)] = trial
                seen_components[component] = trial

    trials.sort(key=lambda t: (
        t["seq_index"] if t["seq_index"] is not None else 1e18,
        t["start_time"] if t["start_time"] is not None else 1e18,
        t["component"],
    ))
    return trials, flags


def determine_completed(pdata: dict, trials: list[dict]) -> tuple[bool, str]:
    if isinstance(pdata.get("completed"), bool):
        return pdata["completed"], "completed_field"
    answers = pdata.get("answers") or {}
    if isinstance(answers, dict):
        for key in answers:
            name, _ = component_name_from_key(key)
            if name in ("debrief", "post-study-survey"):
                return True, f"answered_{name}"
    n_nonpractice = sum(1 for t in trials if t["kind"] != "practice")
    if n_nonpractice >= EXPECTED_NONPRACTICE_TRIALS:
        return True, "all_trials_present"
    return False, "insufficient_evidence"


# --------------------------------------------------------------------------
# Payoff cross-validation against the study config
# --------------------------------------------------------------------------
def expected_payoff(trial: dict):
    """Payoff implied by the design (None if it cannot be determined)."""
    if trial["choice"] == "A":
        pct = to_float(trial["base_target_pct"])
        if pct is None:
            return None
        return js_round(1000.0 * pct / 100.0)  # mirrors trial-stimulus.html
    if trial["choice"] == "B":
        if trial["optionB_won"] is True:
            return 100
        if trial["optionB_won"] is False:
            return 0
        return None
    return None


def validate_trial(trial: dict) -> str | None:
    recorded_base = trial.get("recorded_base_target_pct")
    config_base = to_float(trial.get("base_target_pct"))
    if recorded_base is not None and config_base is not None \
            and abs(recorded_base - config_base) > 1e-9:
        return ("base_target_mismatch:"
                f"recorded={recorded_base},config={config_base}")
    recorded_probability = trial.get("recorded_optionB_probability")
    config_probability = to_float(trial.get("optionB_probability"))
    if recorded_probability is not None and config_probability is not None \
            and abs(recorded_probability - config_probability) > 1e-9:
        return ("optionB_probability_mismatch:"
                f"recorded={recorded_probability},config={config_probability}")
    exp = expected_payoff(trial)
    rec = trial["payoff"]
    if rec is None and exp is None:
        return "payoff_missing_and_unrecoverable"
    if rec is None:
        return None  # recoverable; handled by effective_payoff
    if trial["choice"] == "B" and rec not in (0.0, 100.0):
        return f"optionB_payoff_not_in_{{0,100}}:recorded={rec}"
    if exp is not None and abs(rec - exp) > 1e-9:
        return f"payoff_mismatch:recorded={rec},expected={exp}"
    return None


def effective_payoff(trial: dict):
    """Payoff used for payment: recorded outcome, else design-implied."""
    if trial["payoff"] is not None:
        return trial["payoff"]
    return expected_payoff(trial)


# --------------------------------------------------------------------------
# Bonus computation (deterministic per participant)
# --------------------------------------------------------------------------
def bonus_rng(prolific_pid: str, salt: str) -> random.Random:
    digest = hashlib.sha256(f"{salt}:{prolific_pid}".encode("utf-8")).hexdigest()
    return random.Random(int(digest, 16))


def per_trial_bonus_cents(payoff_dollars: float) -> int:
    excess = max(0.0, payoff_dollars - BONUS_THRESHOLD_DOLLARS)
    return int(round(CENTS_PER_EXCESS_DOLLAR * excess))


def compute_bonus(eligible_trials: list[dict], prolific_pid: str, salt: str):
    """Return an exact three-trial bonus, or None when the log is incomplete."""
    flags = []
    if len(eligible_trials) != EXPECTED_NONPRACTICE_TRIALS:
        flags.append(
            f"exact_bonus_not_computed:n_nonpractice={len(eligible_trials)}")
        return None, [], flags
    if any(effective_payoff(t) is None for t in eligible_trials):
        flags.append("exact_bonus_not_computed:missing_payoff")
        return None, [], flags

    # Stable ordering before sampling => draw depends only on (salt, pid, set
    # of components), never on file/dict iteration order.
    ordered = sorted(eligible_trials, key=lambda t: t["component"])
    selected = bonus_rng(prolific_pid, salt).sample(ordered, N_BONUS_TRIALS)

    cents = sum(per_trial_bonus_cents(effective_payoff(t)) for t in selected)
    if cents > BONUS_CAP_CENTS:
        flags.append(f"bonus_capped_from_{cents}c")
        cents = BONUS_CAP_CENTS
    return max(0, cents), selected, flags


# --------------------------------------------------------------------------
# Main pipeline
# --------------------------------------------------------------------------
def process(data_dir: Path, config_path: Path | None, out_dir: Path,
            recovery_data_dir: Path, salt: str, include_incomplete: bool,
            include_non_prolific: bool, audit_only: bool):
    comp_meta = load_component_meta(config_path)
    files = iter_participant_files(data_dir)
    if not files:
        sys.exit(f"No participant files found under {data_dir}. "
                 "Run download_firebase_data.py first.")
    print(f"Found {len(files)} candidate file(s) in {data_dir}.")
    recovery_logs = load_recovery_logs(recovery_data_dir)
    if recovery_logs:
        print(f"Found exact browser-log recovery data for "
              f"{len(recovery_logs)} participant(s) in {recovery_data_dir}.")
    else:
        print(f"No browser-log recovery data found in {recovery_data_dir}.")

    out_dir.mkdir(parents=True, exist_ok=True)
    participants = []
    audit_rows = []
    for path in files:
        pdata = read_json(path)
        if not isinstance(pdata, dict):
            continue
        audit = audit_participant(path, pdata)
        pid, pid_source = extract_prolific_pid(pdata, path.name)
        submission_id, _ = extract_submission_id(pdata)
        native_trials, flags = extract_trials(pdata, comp_meta)
        recovery = recovery_logs.get(pid)
        recovered_trials = []
        if recovery:
            recovered_trials, recovery_flags = extract_recovered_trials(
                recovery["log"], pdata, comp_meta)
            flags += recovery_flags

        # A direct ReVISit answer is authoritative when both sources contain
        # the same component. Recovery fills the July 2026 capture gap.
        trials_by_component = {
            trial["component"]: trial for trial in recovered_trials
        }
        for trial in native_trials:
            trials_by_component[trial["component"]] = trial
        trials = sorted(trials_by_component.values(), key=lambda trial: (
            trial["seq_index"] if trial["seq_index"] is not None else 1e18,
            trial["component"],
        ))

        audit["recovery_file"] = recovery["file"] if recovery else None
        audit["recovered_trial_records"] = len(recovered_trials)
        audit["payment_ready_trial_records"] = sum(
            1 for trial in trials if trial["kind"] != "practice")
        audit_rows.append(audit)

        is_prolific = pid_source in ("searchParams", "urlParams", "queryParams")
        if not is_prolific and not include_non_prolific:
            continue
        completed, completed_via = determine_completed(pdata, trials)
        rejected = bool(pdata.get("rejected")) if pdata.get("rejected") is not None else False
        participants.append({
            "file": path.name,
            "prolific_pid": pid,
            "submission_id": submission_id,
            "pid_source": pid_source,
            "completed": completed,
            "completed_via": completed_via,
            "rejected_in_revisit": rejected,
            "recovery_file": recovery["file"] if recovery else None,
            "assigned_trial_components": assigned_trial_components(pdata),
            "trials": trials,
            "flags": flags,
        })

    audit_df = pd.DataFrame(audit_rows).sort_values(
        ["is_prolific", "completed", "arm", "participant_index"],
        ascending=[False, False, True, True],
    )
    audit_path = out_dir / "participant_data_audit.csv"
    audit_df.to_csv(audit_path, index=False)

    prolific_audit = audit_df[audit_df["is_prolific"]]
    complete_prolific = prolific_audit[prolific_audit["completed"]]
    arm_counts = complete_prolific["arm"].value_counts().to_dict()
    print(
        "Data audit: "
        f"{len(prolific_audit)} Prolific files "
        f"({len(complete_prolific)} complete; "
        f"p55={arm_counts.get('p55', 0)}, p75={arm_counts.get('p75', 0)}), "
        f"{len(audit_df) - len(prolific_audit)} non-Prolific/test files."
    )
    print(
        "Captured trial answers: "
        f"{int(audit_df['captured_trial_records'].sum())} of "
        f"{int(audit_df['started_trial_records'].sum())} started trial records."
    )
    print(f"Wrote audit: {audit_path}")

    if audit_only:
        return True
    if not participants:
        sys.exit("\nNo eligible participant sessions were found.")

    # ---- resolve duplicate Prolific IDs (restarts create multiple files) ----
    by_pid: dict[str, list[dict]] = {}
    for p in participants:
        by_pid.setdefault(p["prolific_pid"], []).append(p)
    chosen = []
    for pid, plist in by_pid.items():
        if len(plist) > 1:
            plist.sort(key=lambda p: (
                p["completed"],
                sum(1 for t in p["trials"] if t["kind"] != "practice"),
                max(((t["end_time"] or 0) for t in p["trials"]), default=0),
            ), reverse=True)
            for extra in plist[1:]:
                extra_note = f"duplicate_pid_file_ignored:{extra['file']}"
                plist[0]["flags"].append(extra_note)
            print(f"  NOTE: {len(plist)} files share PROLIFIC_PID {pid}; "
                  f"using {plist[0]['file']}.")
        chosen.append(plist[0])

    # ---------------- trial-level long dataframe + payments -----------------
    trial_rows, pay_rows, issue_rows = [], [], []
    for p in chosen:
        pid = p["prolific_pid"]
        main = [t for t in p["trials"] if t["kind"] == "main"]
        acs = [t for t in p["trials"] if t["kind"] == "attention_check"]
        practice = [t for t in p["trials"] if t["kind"] == "practice"]
        assigned = p["assigned_trial_components"]
        n_assigned_acs = sum(1 for name in assigned if "-AC" in name)
        n_assigned_main = len(assigned) - n_assigned_acs
        arm = next((t["arm"] for t in p["trials"] if t["arm"]), None)
        flags = list(p["flags"])
        participant_issue_count = 0

        for t in p["trials"]:
            issue = validate_trial(t)
            if issue:
                participant_issue_count += 1
                issue_rows.append({"prolific_pid": pid, "file": p["file"],
                                   "component": t["component"], "issue": issue})
            trial_rows.append({"prolific_pid": pid, "file": p["file"],
                               "arm": arm, **{k: v for k, v in t.items()
                                              if k != "answer_key"}})

        if len(main) != EXPECTED_MAIN_TRIALS:
            flags.append(f"n_main_trials_recovered={len(main)}")
        if len(acs) != 2:
            flags.append(f"n_attention_checks_recovered={len(acs)}")
        ac_correct = sum(1 for t in acs if t["chose_correct"] is True)
        if len(acs) == 2:
            attention_status = "complete"
            attention_score = f"{ac_correct}/2"
        elif acs:
            attention_status = "partial"
            attention_score = None
        else:
            attention_status = "not_recovered"
            attention_score = None
        eligible_trials = main + acs

        payable = p["completed"] or include_incomplete
        if not p["completed"]:
            flags.append("incomplete_review_manually")
        if p["rejected_in_revisit"]:
            flags.append("rejected_in_revisit_review_manually")

        if payable and participant_issue_count == 0:
            bonus_cents, selected, bflags = compute_bonus(
                eligible_trials, pid, salt)
            flags += bflags
            base_cents = BASE_PAY_CENTS
        elif payable:
            bonus_cents, selected, base_cents = None, [], BASE_PAY_CENTS
            flags.append("exact_bonus_not_computed:payoff_validation_failed")
        else:
            bonus_cents, selected, base_cents = None, [], 0
        bonus_computed = bonus_cents is not None
        if bonus_computed:
            payment_status = "exact_bonus_computed"
        elif not payable:
            payment_status = "incomplete_session"
        elif participant_issue_count:
            payment_status = "blocked_payoff_validation"
        else:
            payment_status = "exact_trial_data_missing"

        pay_rows.append({
            "prolific_pid": pid,
            "submission_id": p["submission_id"],
            "file": p["file"],
            "pid_source": p["pid_source"],
            "arm": arm,
            "completed": p["completed"],
            "completed_via": p["completed_via"],
            "recovery_file": p["recovery_file"],
            "trial_data_sources": ";".join(sorted({
                t.get("source", "unknown") for t in p["trials"]
            })),
            "n_trials_nonpractice_assigned": len(assigned),
            "n_trials_nonpractice_recovered": len(main) + len(acs),
            "n_main_trials_assigned": n_assigned_main,
            "n_main_trials_recovered": len(main),
            "n_attention_checks_assigned": n_assigned_acs,
            "n_attention_checks_recovered": len(acs),
            "n_practice_trials_recovered": len(practice),
            "attention_check_data_status": attention_status,
            "attention_checks_correct": attention_score,
            "payoff_validation_issues": participant_issue_count,
            "payment_status": payment_status,
            "bonus_computed": bonus_computed,
            "bonus_trial_components": ";".join(t["component"] for t in selected),
            "bonus_trial_payoffs": ";".join(
                f"{effective_payoff(t):g}" for t in selected),
            "bonus_trial_contribs_usd": ";".join(
                f"{per_trial_bonus_cents(effective_payoff(t)) / 100:.2f}"
                for t in selected),
            "base_usd": base_cents / 100,
            "bonus_usd": (bonus_cents / 100 if bonus_computed else None),
            "total_usd": ((base_cents + bonus_cents) / 100
                          if bonus_computed else None),
            "amount_to_pay_usd": ((base_cents + bonus_cents) / 100
                                  if bonus_computed else None),
            "flags": ";".join(flags),
        })

    # ------------------------------- outputs --------------------------------
    trials_df = pd.DataFrame(trial_rows)
    pay_df = pd.DataFrame(pay_rows).sort_values("prolific_pid")

    trials_path = out_dir / "trials_long.csv"
    readiness_path = out_dir / "payment_readiness.csv"
    pay_path = out_dir / "payments.csv"
    upload_path = out_dir / "prolific_bonus_upload.csv"
    blocked_path = out_dir / "PAYMENT_BLOCKED.txt"

    trials_df.to_csv(trials_path, index=False)
    pay_df.to_csv(readiness_path, index=False)

    missing_submission_ids = pay_df[
        (pay_df["completed"]) & (pay_df["bonus_computed"]) &
        (pay_df["bonus_usd"] > 0) &
        (pay_df["submission_id"].isna() | (pay_df["submission_id"] == ""))
    ]
    if issue_rows:
        issues_path = out_dir / "validation_issues.csv"
        pd.DataFrame(issue_rows).to_csv(issues_path, index=False)
        print(f"\nWARNING: {len(issue_rows)} payoff validation issue(s) "
              f"written to {issues_path} -- review before paying.")

    # ------------------------------- summary --------------------------------
    n_complete = int(pay_df["completed"].sum())
    n_bonus_computed = int(pay_df["bonus_computed"].sum())
    complete = pay_df[pay_df["completed"]].copy()
    ready_complete = complete[complete["bonus_computed"]]
    all_complete_ready = (
        n_complete > 0
        and len(ready_complete) == n_complete
        and len(missing_submission_ids) == 0
    )
    print(f"\nParticipants: {len(pay_df)} total | {n_complete} complete | "
          f"{len(pay_df) - n_complete} incomplete")
    print(f"Exact three-trial bonuses computed: {n_bonus_computed}")
    if len(ready_complete):
        paid = ready_complete
        print(f"Bonus (exact, complete): mean ${paid['bonus_usd'].mean():.2f} | "
              f"min ${paid['bonus_usd'].min():.2f} | "
              f"max ${paid['bonus_usd'].max():.2f}")
        print(f"Total payout (base + bonus, complete only): "
              f"${paid['total_usd'].sum():.2f}")
    flagged = pay_df[pay_df["flags"] != ""]
    if len(flagged):
        print(f"{len(flagged)} participant(s) carry review flags -- "
              f"see the 'flags' column in payment_readiness.csv.")

    if not all_complete_ready:
        pay_path.unlink(missing_ok=True)
        upload_path.unlink(missing_ok=True)
        missing_exact = n_complete - len(ready_complete)
        blocked_path.write_text(
            "PAYMENT WORKFLOW BLOCKED\n"
            "========================\n\n"
            "No final payment files were generated.\n\n"
            f"Completed original sessions: {n_complete}\n"
            f"Completed sessions with exact validated bonuses: "
            f"{len(ready_complete)}\n"
            f"Completed sessions still missing exact bonuses: {missing_exact}\n"
            f"Positive bonuses missing SESSION_ID: "
            f"{len(missing_submission_ids)}\n\n"
            "Required next step: collect the original browser trial logs "
            "through the demo-headline-recovery study, then run "
            "run_payment_pipeline.command again.\n\n"
            "Do not pay bonuses from payment_readiness.csv.\n",
            encoding="utf-8",
        )
        print("\nPAYMENT WORKFLOW BLOCKED")
        print(f"{missing_exact} of {n_complete} completed participant(s) still "
              "lack an exact validated bonus.")
        print("No payments.csv or Prolific upload file was generated.")
        print(f"Read: {blocked_path}")
        print(f"Audit: {readiness_path}")
        return False

    blocked_path.unlink(missing_ok=True)
    complete.to_csv(pay_path, index=False)
    upload = complete[(complete["bonus_usd"] > 0)]
    upload.assign(bonus=upload["bonus_usd"].map(lambda x: f"{x:.2f}")) \
          [["submission_id", "bonus"]] \
          .to_csv(upload_path, index=False, header=False)
    print(f"\nPAYMENT WORKFLOW READY: {n_complete} complete participants.")
    print(f"Wrote final files:\n  {pay_path}\n  {upload_path}")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Compute Prolific payments for the demo-headline study.")
    parser.add_argument("--data-dir", default=DEFAULT_DATA_DIR, type=Path)
    parser.add_argument("--config", default=None,
                        help="path to the study config.json (the repository's "
                             "public/demo-headline/config.json is the default)")
    parser.add_argument("--out-dir", default=DEFAULT_OUTPUT_DIR, type=Path)
    parser.add_argument("--recovery-data-dir", default=DEFAULT_RECOVERY_DATA_DIR,
                        type=Path, help="folder of participantData files from "
                        "the demo-headline-recovery study")
    parser.add_argument("--include-incomplete", action="store_true",
                        help="compute base+bonus even for participants not "
                             "marked complete (default: $0 + review flag)")
    parser.add_argument("--include-non-prolific", action="store_true",
                        help="include local/test sessions without Prolific URL "
                             "parameters in payment output")
    parser.add_argument("--audit-only", action="store_true",
                        help="write participant_data_audit.csv without "
                             "attempting payment computation")
    args = parser.parse_args()

    salt = os.environ.get("BONUS_SEED_SALT", DEFAULT_SALT)
    config_path = find_config(args.config)
    if config_path:
        print(f"Using study config: {config_path}")
    ready = process(args.data_dir, config_path, args.out_dir,
                    args.recovery_data_dir, salt,
                    args.include_incomplete, args.include_non_prolific,
                    args.audit_only)
    return 0 if ready else 2


if __name__ == "__main__":
    sys.exit(main())
