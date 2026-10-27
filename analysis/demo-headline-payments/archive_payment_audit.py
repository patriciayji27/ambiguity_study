#!/usr/bin/env python3
"""Archive the verified payment record after bonuses have been issued."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "output"
DEFAULT_ARCHIVE_DIR = SCRIPT_DIR / "audit-archives"
FIXED_SALT = "demo-headline-v4-bonus"


def fail(message: str) -> "NoReturn":
    raise SystemExit(f"PAYMENT AUDIT ARCHIVE BLOCKED: {message}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, check=True,
        capture_output=True, text=True,
    )
    return result.stdout.strip()


def archive(out_dir: Path, archive_dir: Path) -> Path:
    required = [
        out_dir / "payments.csv",
        out_dir / "prolific_bonus_upload.csv",
        out_dir / "payment_readiness.csv",
        out_dir / "participant_data_audit.csv",
        out_dir / "trials_long.csv",
        out_dir / "PAYMENT_VERIFIED.txt",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        fail("missing required verified output(s): " + ", ".join(missing))
    if (out_dir / "PAYMENT_BLOCKED.txt").is_file():
        fail("PAYMENT_BLOCKED.txt still exists")

    commit = git_commit()
    timestamp = datetime.now().astimezone()
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / (
        f"headline-payments-{timestamp.date().isoformat()}-{commit[:10]}.tar.gz")

    included = required + [
        SCRIPT_DIR / "compute_payments.py",
        SCRIPT_DIR / "finalize_after_recovery.py",
        SCRIPT_DIR / "verify_payment_outputs.py",
        SCRIPT_DIR / "PAYMENT_POLICY.md",
        REPO_ROOT / "public" / "demo-headline" / "config.json",
    ]
    optional = [
        out_dir / "fallback_policy_applied.json",
        SCRIPT_DIR / "data" / ".firebase-sync-manifest.json",
        SCRIPT_DIR / "recovery-data" / ".firebase-sync-manifest.json",
    ]
    included.extend(path for path in optional if path.is_file())

    metadata = {
        "archivedAt": timestamp.isoformat(),
        "bonusSeedSalt": FIXED_SALT,
        "gitCommit": commit,
        "files": {
            str(path.relative_to(REPO_ROOT)): sha256(path)
            for path in included
        },
    }
    with tempfile.TemporaryDirectory() as temp_dir:
        metadata_path = Path(temp_dir) / "payment_audit_metadata.json"
        metadata_path.write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        with tarfile.open(archive_path, "w:gz") as bundle:
            bundle.add(metadata_path, arcname="payment_audit_metadata.json")
            for path in included:
                bundle.add(path, arcname=str(path.relative_to(REPO_ROOT)))

    checksum_path = archive_path.with_suffix(archive_path.suffix + ".sha256")
    checksum_path.write_text(
        f"{sha256(archive_path)}  {archive_path.name}\n", encoding="utf-8")
    archive_path.chmod(0o400)
    checksum_path.chmod(0o400)
    print("PAYMENT AUDIT ARCHIVED")
    print(f"Git commit: {commit}")
    print(f"Fixed bonus seed salt: {FIXED_SALT}")
    print(f"Archive: {archive_path}")
    print(f"Checksum: {checksum_path}")
    return archive_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Archive verified headline-study payment records.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--archive-dir", type=Path, default=DEFAULT_ARCHIVE_DIR)
    args = parser.parse_args()
    archive(args.out_dir, args.archive_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
