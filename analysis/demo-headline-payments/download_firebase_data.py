#!/usr/bin/env python3
"""Incrementally sync demo-headline participant JSON from Firebase Storage.

The script uses a service-account key when one is configured. Otherwise it
uses Firebase's REST API, which works while the bucket permits public reads.
An on-disk manifest tracks object generations so files are refreshed when
ReVISit overwrites an existing participant object.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

DEFAULT_BUCKET = "financial-uncertainty.firebasestorage.app"
DEFAULT_PREFIX = "prod-demo-headline/participants/"
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_LOCAL_DIR = SCRIPT_DIR / "data"
MANIFEST_NAME = ".firebase-sync-manifest.json"


@dataclass(frozen=True)
class RemoteObject:
    name: str
    generation: str | None
    size: int | None
    md5_hash: str | None
    updated: str | None


def fail(message: str) -> "NoReturn":
    raise SystemExit(message)


def normalize_prefix(prefix: str) -> str:
    return f"{prefix.rstrip('/')}/" if prefix else ""


def service_account_path(explicit: str | None) -> Path | None:
    raw = explicit
    if raw is None:
        raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
    if raw is None:
        raw = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not raw:
        return None
    path = Path(raw).expanduser().resolve()
    if not path.is_file():
        fail(f"Firebase service-account file does not exist: {path}")
    return path


def request_bytes(url: str, headers: dict[str, str] | None = None):
    request = Request(url, headers=headers or {})
    try:
        return urlopen(request, timeout=120)
    except HTTPError as exc:
        detail = exc.read(500).decode("utf-8", errors="replace")
        raise RuntimeError(f"Firebase returned HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach Firebase: {exc.reason}") from exc


class RestStorageClient:
    """Small Firebase Storage REST client; no third-party package required."""

    def __init__(self, bucket: str, api_key: str | None, access_token: str | None):
        self.bucket = bucket
        self.api_key = api_key
        self.headers = ({"Authorization": f"Bearer {access_token}"}
                        if access_token else {})
        self.base = (
            "https://firebasestorage.googleapis.com/v0/b/"
            f"{quote(bucket, safe='')}/o"
        )

    def url(self, object_name: str | None = None, **params) -> str:
        url = self.base
        if object_name is not None:
            url += f"/{quote(object_name, safe='')}"
        query = {key: value for key, value in params.items() if value is not None}
        if self.api_key:
            query["key"] = self.api_key
        return f"{url}?{urlencode(query)}" if query else url

    def get_json(self, url: str) -> dict:
        with request_bytes(url, self.headers) as response:
            return json.load(response)

    def object_metadata(self, name: str) -> RemoteObject:
        item = self.get_json(self.url(name))
        raw_size = item.get("size")
        return RemoteObject(
            name=name,
            generation=item.get("generation"),
            size=int(raw_size) if raw_size is not None else None,
            md5_hash=item.get("md5Hash"),
            updated=item.get("updated"),
        )

    def list_objects(self, prefix: str, workers: int) -> list[RemoteObject]:
        names: list[str] = []
        page_token = None
        while True:
            page = self.get_json(self.url(prefix=prefix, pageToken=page_token,
                                          maxResults=1000))
            names.extend(item["name"] for item in page.get("items", [])
                         if not item["name"].endswith("/"))
            page_token = page.get("nextPageToken")
            if not page_token:
                break
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            return sorted(pool.map(self.object_metadata, names),
                          key=lambda item: item.name)

    def download(self, item: RemoteObject, destination: Path) -> None:
        with request_bytes(self.url(item.name, alt="media"), self.headers) as source:
            with destination.open("wb") as target:
                shutil.copyfileobj(source, target)


class AdminStorageClient:
    """Firebase Admin client for use after public bucket reads are disabled."""

    def __init__(self, bucket: str, key_path: Path):
        try:
            import firebase_admin
            from firebase_admin import credentials, storage
        except ImportError:
            fail("firebase-admin is required for service-account mode. Run:\n"
                 "    python3 -m pip install firebase-admin")
        app_name = "demo-headline-data-download"
        try:
            app = firebase_admin.get_app(app_name)
        except ValueError:
            app = firebase_admin.initialize_app(
                credentials.Certificate(str(key_path)),
                {"storageBucket": bucket},
                name=app_name,
            )
        self.bucket = storage.bucket(app=app)

    def list_objects(self, prefix: str, workers: int) -> list[RemoteObject]:
        del workers
        objects = []
        for blob in self.bucket.list_blobs(prefix=prefix):
            if blob.name.endswith("/"):
                continue
            objects.append(RemoteObject(
                name=blob.name,
                generation=str(blob.generation) if blob.generation else None,
                size=blob.size,
                md5_hash=blob.md5_hash,
                updated=blob.updated.isoformat() if blob.updated else None,
            ))
        return sorted(objects, key=lambda item: item.name)

    def download(self, item: RemoteObject, destination: Path) -> None:
        self.bucket.blob(item.name).download_to_filename(destination)


def load_manifest(path: Path) -> dict:
    if not path.is_file():
        return {"objects": {}}
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"WARNING: ignoring unreadable sync manifest: {exc}")
        return {"objects": {}}
    if not isinstance(data.get("objects"), dict):
        return {"objects": {}}
    return data


def save_json_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def local_path_for(item: RemoteObject, prefix: str, local_dir: Path) -> Path:
    relative = item.name[len(prefix):] if prefix else item.name
    path = PurePosixPath(relative)
    if not relative or path.is_absolute() or ".." in path.parts:
        fail(f"Unsafe Firebase object path: {item.name}")
    return local_dir.joinpath(*path.parts)


def local_md5(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return base64.b64encode(digest.digest()).decode("ascii")


def is_current(path: Path, item: RemoteObject, recorded: dict | None) -> bool:
    if not path.is_file():
        return False
    if recorded and item.generation and recorded.get("generation") == item.generation:
        return True
    if item.size is not None and path.stat().st_size != item.size:
        return False
    return bool(item.md5_hash and local_md5(path) == item.md5_hash)


def download_atomic(client, item: RemoteObject, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{destination.name}.",
                                     dir=destination.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        client.download(item, temp_path)
        if item.size is not None and temp_path.stat().st_size != item.size:
            raise RuntimeError(
                f"size mismatch for {item.name}: expected {item.size}, "
                f"downloaded {temp_path.stat().st_size}")
        if item.md5_hash and local_md5(temp_path) != item.md5_hash:
            raise RuntimeError(f"MD5 mismatch for {item.name}")
        os.replace(temp_path, destination)
    finally:
        temp_path.unlink(missing_ok=True)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Incrementally sync demo-headline participant data.")
    parser.add_argument("--bucket", default=os.environ.get(
        "FIREBASE_STORAGE_BUCKET", DEFAULT_BUCKET))
    parser.add_argument("--prefix", default=os.environ.get(
        "FIREBASE_BUCKET_FOLDER", DEFAULT_PREFIX))
    parser.add_argument("--data-dir", type=Path, default=Path(os.environ.get(
        "LOCAL_DATA_DIR", DEFAULT_LOCAL_DIR)))
    parser.add_argument("--auth-mode", choices=("auto", "rest", "service-account"),
                        default="auto")
    parser.add_argument("--service-account", default=None)
    parser.add_argument("--api-key", default=os.environ.get("FIREBASE_API_KEY"))
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    prefix = normalize_prefix(args.prefix)
    data_dir = args.data_dir.expanduser().resolve()
    key_path = service_account_path(args.service_account)
    use_admin = args.auth_mode == "service-account" or (
        args.auth_mode == "auto" and key_path is not None)
    if args.auth_mode == "service-account" and key_path is None:
        fail("--auth-mode service-account requires --service-account or "
             "FIREBASE_SERVICE_ACCOUNT.")

    if use_admin:
        client = AdminStorageClient(args.bucket, key_path)
        auth_label = "Firebase service account"
    else:
        client = RestStorageClient(
            args.bucket,
            args.api_key,
            os.environ.get("FIREBASE_ACCESS_TOKEN"),
        )
        auth_label = "Firebase REST (bucket read rules)"

    print(f"Bucket: {args.bucket}")
    print(f"Prefix: {prefix or '(bucket root)'}")
    print(f"Local:  {data_dir}")
    print(f"Auth:   {auth_label}\n")

    try:
        remote = client.list_objects(prefix, args.workers)
    except RuntimeError as exc:
        fail(f"Unable to list Firebase participant data: {exc}\n"
             "For a private bucket, configure FIREBASE_SERVICE_ACCOUNT and "
             "install firebase-admin.")

    manifest_path = data_dir / MANIFEST_NAME
    manifest = load_manifest(manifest_path)
    recorded = manifest.get("objects", {})
    targets = []
    for item in remote:
        destination = local_path_for(item, prefix, data_dir)
        if args.force or not is_current(destination, item, recorded.get(item.name)):
            targets.append((item, destination))

    print(f"Remote objects: {len(remote)}")
    print(f"Files to download: {len(targets)}")
    if not targets:
        print("All participant files are up to date.")
        return 0

    failures = 0
    for item, destination in targets:
        relative = destination.relative_to(data_dir)
        if args.dry_run:
            print(f"  [dry-run] {item.name} -> {relative}")
            continue
        print(f"  Downloading {relative}")
        try:
            download_atomic(client, item, destination)
            recorded[item.name] = asdict(item)
        except Exception as exc:
            failures += 1
            print(f"    ERROR: {exc}")

    if args.dry_run:
        return 0

    manifest.update({
        "bucket": args.bucket,
        "prefix": prefix,
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "objects": recorded,
    })
    save_json_atomic(manifest_path, manifest)
    print(f"\nDone. {len(targets) - failures} downloaded, {failures} failed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
