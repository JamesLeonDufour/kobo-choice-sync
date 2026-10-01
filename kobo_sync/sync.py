"""Dependency-free reconciler. No submission values are written to logs or disk."""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import time
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener


class SyncError(Exception):
    """An error safe to display in public Actions logs."""


def normalized(value: str) -> str:
    return unicodedata.normalize("NFKC", " ".join(value.split())).casefold()


def choice_name(label: str, identity: tuple, names: set[str]) -> str:
    # Kobo choice values should be short, with no spaces or punctuation.
    ascii_label = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode().lower()
    base = re.sub(r"[^a-z0-9]+", "_", ascii_label).strip("_")[:64].rstrip("_")
    if base and base[0].isdigit():
        base = "c_" + base[:62].rstrip("_")
    digest = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()
    if not base:
        base = "choice"
    if base not in names:
        return base
    for length in (8, 12, 16, 24, 32, 64):
        candidate = base[:64 - length - 1].rstrip("_") + "_" + digest[:length]
        if candidate not in names:
            return candidate
    raise SyncError("Generated choice name conflicts with an existing choice; resolve manually.")


def load_config(path: str) -> dict:
    c = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    required = {"server", "asset_uid", "csv_filename",
                "select_field", "other_value", "text_field"}
    optional = {"extra_columns", "max_label_length", "page_size", "max_pages"}
    if not isinstance(c, dict) or required - c.keys() or c.keys() - required - optional:
        raise SyncError("Configuration has missing or unknown keys; see README.md.")
    for key in required:
        if not isinstance(c[key], str) or not c[key].strip() or "REPLACE" in c[key]:
            raise SyncError("Replace every configuration placeholder with a nonempty string.")
    p = urlsplit(c["server"])
    if p.scheme != "https" or not p.hostname or p.username or p.password or p.query or p.fragment or p.path not in ("", "/"):
        raise SyncError("server must be an HTTPS origin, without credentials or a path.")
    c["server"] = c["server"].rstrip("/")
    if not re.fullmatch(r"[A-Za-z0-9]+", c["asset_uid"]):
        raise SyncError("Asset UID must contain only letters and digits.")
    if not re.fullmatch(r"[A-Za-z0-9_-]+\.csv", c["csv_filename"]):
        raise SyncError("csv_filename must be a simple .csv filename.")
    c.setdefault("extra_columns", {})
    if not isinstance(c["extra_columns"], dict):
        raise SyncError("extra_columns must be an object of CSV column to source field.")
    for column, field in c["extra_columns"].items():
        if not column or column in ("name", "label") or not isinstance(field, str) or not field:
            raise SyncError("Invalid extra_columns mapping.")
    for key, default, maximum in (("max_label_length", 200, 10000), ("page_size", 500, 1000), ("max_pages", 1000, 100000)):
        c.setdefault(key, default)
        if type(c[key]) is not int or not 1 <= c[key] <= maximum:
            raise SyncError("Invalid numeric configuration limit.")
    return c


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Kobo:
    def __init__(self, server: str, token: str):
        self.server = server
        self.token = token
        self.opener = build_opener(NoRedirect())

    def request(self, method: str, path: str, payload=None, raw=False):
        url = urljoin(self.server + "/", path)
        p = urlsplit(url)
        if (p.scheme, p.netloc) != (urlsplit(self.server).scheme, urlsplit(self.server).netloc) or p.username or p.password:
            raise SyncError("Refusing to send a Kobo token to a different origin.")
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = Request(url, data=data, method=method, headers={
            "Authorization": "Token " + self.token,
            "Accept": "application/json", "Content-Type": "application/json",
            "User-Agent": "kobo-choice-sync/1.0",
        })
        for attempt in range(4):
            try:
                with self.opener.open(req, timeout=45) as response:
                    body = response.read()
                return body if raw else (json.loads(body) if body else None)
            except HTTPError as exc:
                status = exc.code
                exc.close()
                if method == "GET" and status in (429, 500, 502, 503, 504) and attempt < 3:
                    time.sleep(2 ** attempt)
                    continue
                # Do not log URLs, response bodies, headers, or submission values.
                raise SyncError(f"Kobo {method} failed (HTTP {status}); inspect Kobo settings and permissions.") from None
            except (URLError, TimeoutError, OSError):
                if method == "GET" and attempt < 3:
                    time.sleep(2 ** attempt)
                    continue
                raise SyncError(f"Kobo {method} network failure; rerun reconciliation.") from None
            except (ValueError, UnicodeError):
                raise SyncError("Kobo returned an invalid response.") from None

    def pages(self, path: str, max_pages: int):
        seen = set()
        for _ in range(max_pages):
            if path in seen:
                raise SyncError("Pagination loop detected.")
            seen.add(path)
            page = self.request("GET", path)
            if isinstance(page, list):
                yield from page
                return
            if not isinstance(page, dict) or not isinstance(page.get("results"), list):
                raise SyncError("Unexpected paginated API response.")
            yield from page["results"]
            path = page.get("next")
            if not path:
                return
        raise SyncError("Pagination limit reached; increase max_pages. No choices were updated.")


def asset_path(uid):
    return f"/api/v2/assets/{uid}/"


def current_version(api, c):
    asset = api.request("GET", asset_path(c["asset_uid"]))
    version = asset.get("version_id")
    if not asset.get("has_deployment") or not asset.get("deployment__active"):
        raise SyncError("Target must already be deployed and active.")
    if not version or version != asset.get("deployed_version_id"):
        raise SyncError("Target has unpublished form edits. Deploy or discard them before syncing.")
    return version


def media(api, c):
    return list(api.pages(asset_path(c["asset_uid"]) + "files/?limit=100", c["max_pages"]))


def find_file(files, name):
    matches = [f for f in files if f.get("file_type") == "form_media" and f.get("metadata", {}).get("filename") == name]
    if len(matches) > 1:
        raise SyncError("Duplicate media filenames found; resolve them in Kobo before syncing.")
    return matches[0] if matches else None


def file_path(c, f):
    uid = f.get("uid", "")
    if not re.fullmatch(r"[A-Za-z0-9]+", uid):
        raise SyncError("Invalid media UID returned by Kobo.")
    return asset_path(c["asset_uid"]) + f"files/{uid}/"


def read_file(api, c, f):
    if f.get("metadata", {}).get("redirect_url"):
        raise SyncError("Use an uploaded CSV attachment, not externally hosted media.")
    return api.request("GET", file_path(c, f) + "content/", raw=True)


def upload(api, c, filename, content):
    return api.request("POST", asset_path(c["asset_uid"]) + "files/", {
        "description": "Managed by kobo-choice-sync",
        "file_type": "form_media", "metadata": {"filename": filename},
        "base64Encoded": "data:text/csv;base64," + base64.b64encode(content).decode("ascii"),
    })


def parse_csv(content, c):
    try:
        reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig"), newline=""), strict=True)
        headers = reader.fieldnames
        if not headers or len(headers) != len(set(headers)) or set(headers) != {"name", "label", *c["extra_columns"]}:
            raise SyncError("CSV must have name, label, and exactly the configured extra_columns.")
        rows = list(reader)
    except (UnicodeError, csv.Error):
        raise SyncError("Choices must be valid UTF-8 CSV.") from None
    names = set()
    for row in rows:
        if None in row or any(value is None for value in row.values()) or not row["name"] or not row["label"] or row["name"] in names:
            raise SyncError("CSV contains malformed rows, empty names/labels, or duplicate names.")
        names.add(row["name"])
    if c["other_value"] not in names:
        raise SyncError("Choices CSV must include the configured Other value.")
    return headers, rows


def merge(content, submissions, c):
    headers, rows = parse_csv(content, c)
    extra = list(c["extra_columns"])

    def key(row):
        # Labels are normalized; filter values remain exact and case-sensitive.
        return (normalized(row["label"]), *(row[col] for col in extra))

    known = {key(row) for row in rows}
    names = {row["name"] for row in rows}
    added = 0
    scanned = 0
    select_seen = False
    for submission in submissions:
        if not isinstance(submission, dict):
            raise SyncError("Unexpected submission structure.")
        scanned += 1
        select_seen = select_seen or c["select_field"] in submission
        if submission.get(c["select_field"]) != c["other_value"]:
            continue
        value = submission.get(c["text_field"])
        if not isinstance(value, str) or not value.strip():
            raise SyncError("An Other submission has missing/invalid text; correct the data or field mapping.")
        label = " ".join(unicodedata.normalize("NFKC", value).split())
        if len(label) > c["max_label_length"] or any(unicodedata.category(ch).startswith("C") for ch in label):
            raise SyncError("An Other value exceeds the label limit or contains control characters.")
        row = {"label": label}
        for col, field in c["extra_columns"].items():
            v = submission.get(field)
            if not isinstance(v, (str, int, float)) or isinstance(v, bool) or not str(v).strip():
                raise SyncError("An Other submission is missing a configured filter column.")
            row[col] = str(v)
        identity = key(row)
        if identity in known:
            continue
        row["name"] = choice_name(label, identity, names)
        rows.append(row)
        known.add(identity)
        names.add(row["name"])
        added += 1
    if scanned and not select_seen:
        raise SyncError("select_field was absent from every submission; check the configured field path.")
    other_row = next((row for row in rows if row["name"] == c["other_value"]), None)
    if other_row is not None and rows[-1] is not other_row:
        rows.remove(other_row)
        rows.append(other_row)
    elif not added:
        return content, 0
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=headers, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8"), added


def reconcile(api, c, dry_run=False):
    version = current_version(api, c)
    filename = c["csv_filename"]
    backup_name = filename[:-4] + "_sync_recovery.csv"
    files = media(api, c)
    target = find_file(files, filename)
    backup = find_file(files, backup_name)
    if not target and not backup:
        raise SyncError("Upload the initial choices CSV to target project Media before running.")
    original = read_file(api, c, target or backup)
    fields = list(dict.fromkeys(["_id", c["select_field"], c["text_field"], *c["extra_columns"].values()]))
    query = urlencode({"fields": json.dumps(fields), "sort": json.dumps({"_id": 1}), "limit": c["page_size"]})
    # Full reconciliation deliberately does not depend on dispatch payloads or a cursor.
    submissions = api.pages(asset_path(c["asset_uid"]) + "data/?" + query, c["max_pages"])
    updated, added = merge(original, submissions, c)
    needs_write = updated != original or target is None
    if dry_run:
        print(f"Dry run: {added} new choices; recovery pending: {bool(backup)}. No changes made.")
        return
    if not needs_write and not backup:
        print("Choices already synchronized.")
        return
    if current_version(api, c) != version:
        raise SyncError("Form changed during reconciliation; rerun after edits are settled.")
    # Optimistic check plus the workflow's single-writer concurrency group.
    fresh_target = find_file(media(api, c), filename)
    if (fresh_target or {}).get("uid") != (target or {}).get("uid"):
        raise SyncError("Choices attachment changed during reconciliation; rerun.")
    if target and read_file(api, c, target) != original:
        raise SyncError("Choices contents changed during reconciliation; rerun.")
    if needs_write:
        if not backup:
            backup = upload(api, c, backup_name, original)
            if read_file(api, c, backup) != original:
                raise SyncError("Recovery copy verification failed; original CSV has not been removed.")
        if target:
            api.request("DELETE", file_path(c, target))
        try:
            upload(api, c, filename, updated)
        except SyncError:
            # A timed-out POST may have succeeded. Never blindly overwrite it.
            existing = find_file(media(api, c), filename)
            if not existing:
                upload(api, c, filename, original)
            raise SyncError("CSV replacement did not complete cleanly. Recovery copy retained; rerun.") from None
        new_target = find_file(media(api, c), filename)
        if not new_target or read_file(api, c, new_target) != updated:
            raise SyncError("Uploaded CSV verification failed. Recovery copy retained; rerun.")
    # version_id forces a real redeploy; active alone only toggles archival state.
    if current_version(api, c) != version:
        raise SyncError("Form changed before redeployment. Recovery copy retained; settle edits and rerun.")
    api.request("PATCH", asset_path(c["asset_uid"]) + "deployment/", {"version_id": version})
    api.request("DELETE", file_path(c, backup))
    print(f"Synchronized and redeployed successfully; {added} choices added.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        c = load_config(args.config)
        token = os.environ.get("KOBO_API_TOKEN", "").strip()
        if not token:
            raise SyncError("Set KOBO_API_TOKEN in the environment or GitHub Actions secrets.")
        reconcile(Kobo(c["server"], token), c, args.dry_run)
        return 0
    except SyncError as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
    except (OSError, ValueError, TypeError, KeyError):
        print("ERROR: Invalid configuration or unexpected API data. No response data logged.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
