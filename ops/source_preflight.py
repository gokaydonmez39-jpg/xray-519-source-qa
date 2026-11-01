"""Fail-closed, read-only Git preflight for a redundant native source schedule.

A validated same-hour 519 receipt+bridge on remote main permits NOOP, not
source success. No network calls except the workflow's prior git fetch;
no writes, retries, market calls, strategy, orders, alerts, or secret access.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
import re
import subprocess
from pathlib import Path

from warmup_receipt_audit import ReceiptInvalid, summarize

ALLOW_SCAN = "ALLOW_SCAN"
ALREADY_PUBLISHED = "ALREADY_PUBLISHED"
MAX_RECEIPT = 200_000
MAX_BRIDGE = 8_388_608
MAX_JSON = 2_500_000
MAX_BRIDGE_RAW = 24 * 1024 * 1024


class PreflightBlocked(ValueError):
    pass


def _git(*args, allow_failure=False):
    try:
        p = subprocess.run(["git", *args], capture_output=True, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise PreflightBlocked("GIT_READ_UNAVAILABLE") from e
    if p.returncode and not allow_failure:
        raise PreflightBlocked("GIT_READ_FAILED")
    return p


def _tree(ref):
    result = {}
    for record in _git("ls-tree", "-rz", "--full-tree", ref).stdout.split(b"\0"):
        if record:
            try:
                meta, name = record.split(b"\t", 1)
                mode, kind, sha = meta.decode("ascii").split()
                path = name.decode("utf-8")
            except (ValueError, UnicodeError) as e:
                raise PreflightBlocked("INVALID_GIT_TREE") from e
            if path in result:
                raise PreflightBlocked("DUPLICATE_GIT_TREE_PATH")
            result[path] = (mode, kind, sha)
    return result


def _source_inputs(tree):
    return {k: v for k, v in tree.items()
            if k.endswith(".py") or k.startswith(".github/workflows/")}


def _git_blob(ref, tree, path, limit):
    item = tree.get(path)
    if item is None or item[:2] != ("100644", "blob"):
        raise PreflightBlocked("UNSAFE_EVIDENCE_MODE")
    refpath = ref + ":" + path
    try:
        size = int(_git("cat-file", "-s", refpath).stdout.decode("ascii").strip())
    except (UnicodeError, ValueError) as e:
        raise PreflightBlocked("INVALID_EVIDENCE_SIZE") from e
    if size <= 0 or size > limit:
        raise PreflightBlocked("EVIDENCE_SIZE_LIMIT")
    content = _git("show", refpath).stdout
    if len(content) != size:
        raise PreflightBlocked("EVIDENCE_SIZE_MISMATCH")
    return content


def _json_gzip(data, raw_limit):
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as compressed:
            raw = compressed.read(raw_limit + 1)
        if len(raw) > raw_limit:
            raise PreflightBlocked("DECOMPRESSED_EVIDENCE_LIMIT")

        def unique(pairs):
            out = {}
            for key, val in pairs:
                if key in out:
                    raise PreflightBlocked("DUPLICATE_JSON_KEY")
                out[key] = val
            return out

        def nonfinite(_):
            raise PreflightBlocked("NONFINITE_JSON")

        doc = json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
                         parse_constant=nonfinite)
    except (OSError, EOFError, ValueError, UnicodeError) as e:
        if isinstance(e, PreflightBlocked):
            raise
        raise PreflightBlocked("INVALID_PUBLISHED_EVIDENCE") from e
    if not isinstance(doc, dict):
        raise PreflightBlocked("INVALID_PUBLISHED_EVIDENCE")
    return doc


def _canonical(doc):
    try:
        return json.dumps(doc, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError) as e:
        raise PreflightBlocked("INVALID_PUBLISHED_EVIDENCE") from e


def _pair(ref, entries, mode, stamp):
    folder = f"{stamp[:4]}/{stamp[4:6]}/{stamp[6:8]}"
    suffix = f"/{stamp}-n{mode}.json.gz"
    receipt_path, bridge_path = "receipts/" + folder + suffix, "bridges/" + folder + suffix
    present = [p in entries for p in (receipt_path, bridge_path)]
    if present == [False, False]:
        return False
    if present != [True, True]:
        raise PreflightBlocked("PAIR_INCOMPLETE")
    receipt = _json_gzip(_git_blob(ref, entries, receipt_path, MAX_RECEIPT), MAX_JSON)
    bridge = _json_gzip(_git_blob(ref, entries, bridge_path, MAX_BRIDGE), MAX_BRIDGE_RAW)
    try:
        summary = summarize(receipt)
    except ReceiptInvalid as e:
        raise PreflightBlocked("INVALID_PUBLISHED_EVIDENCE") from e
    nominal = datetime.strptime(stamp, "%Y%m%dT%H00Z").replace(tzinfo=timezone.utc)
    expected_close = int(nominal.timestamp() * 1000) - 1
    if summary["source_receipt_epoch_ms"] != expected_close:
        raise PreflightBlocked("EPOCH_MISMATCH")
    source = receipt.get("public_runner")
    if (not isinstance(source, dict) or
        source.get("repository") != "gokaydonmez39-jpg/xray-519-source-qa" or
        not isinstance(source.get("run_id"), str) or
        not source["run_id"].isdecimal() or
        not isinstance(source.get("run_attempt"), str) or
        not source["run_attempt"].isdecimal() or
        receipt.get("source_qa_success") is not True or
        receipt.get("scope_stable") is not True or
        receipt.get("epoch_stable") is not True or
        receipt.get("complete_identity_scope") is not True or
        receipt.get("status_accounting_ok") is not True):
        raise PreflightBlocked("INVALID_PUBLISHED_EVIDENCE")
    # The bridge hashes the original research JSON, before public publication
    # adds the run provenance and source_receipt_sha256 wrapper fields.
    unwrapped = {key: value for key, value in receipt.items()
                 if key not in ("public_runner", "source_receipt_sha256")}
    digest = hashlib.sha256(_canonical(unwrapped)).hexdigest()
    if receipt.get("source_receipt_sha256") != digest:
        raise PreflightBlocked("PAIR_HASH_MISMATCH")
    if (bridge.get("schema") != "XRAY_PUBLIC_PRIVATE_CLOSED_BAR_BRIDGE_V1" or
        bridge.get("source_receipt_sha256") != digest or
        bridge.get("source_receipt_key") != receipt.get("receipt_key") or
        any(bridge.get(key) != receipt.get(key) for key in (
            "scope_digest_sha256", "utc_closed_epoch_1h_ms", "identity_universe"))):
        raise PreflightBlocked("PAIR_HASH_MISMATCH")
    deferred = bridge.get("deferred_symbols")
    if (type(bridge.get("raw_prefilter_symbols")) is not int or
        type(bridge.get("exported_symbols")) is not int or
        not isinstance(deferred, dict) or
        bridge["raw_prefilter_symbols"] != bridge["exported_symbols"] + len(deferred) or
        bridge.get("orders_sent") != 0 or
        bridge.get("notifications_sent") != 0 or
        bridge.get("private_strategy_evaluated") != 0 or
        bridge.get("live_al_claim") is not False):
        raise PreflightBlocked("INVALID_PUBLISHED_EVIDENCE")
    return True


def assess(mode, stamp, local="HEAD", remote="origin/main"):
    if mode not in ("250", "400", "519"):
        raise PreflightBlocked("INVALID_MODE")
    if not re.fullmatch(r"\d{8}T\d{2}00Z", stamp):
        raise PreflightBlocked("INVALID_STAMP")
    try:
        parsed = datetime.strptime(stamp, "%Y%m%dT%H00Z")
        if parsed.strftime("%Y%m%dT%H00Z") != stamp:
            raise ValueError("invalid calendar")
    except ValueError as e:
        raise PreflightBlocked("INVALID_STAMP") from e
    if local != "HEAD" or remote != "origin/main":
        raise PreflightBlocked("UNEXPECTED_REF")
    l, r = _git("rev-parse", local).stdout.strip(), _git("rev-parse", remote).stdout.strip()
    entries = _tree(remote)
    if l != r:
        if mode != "519":
            raise PreflightBlocked("STALE_HEAD_NON_519")
        if _git("merge-base", "--is-ancestor", local, remote,
                allow_failure=True).returncode != 0:
            raise PreflightBlocked("REMOTE_HISTORY_DIVERGED")
        if _source_inputs(_tree(local)) != _source_inputs(entries):
            raise PreflightBlocked("SOURCE_CHANGED")
    if mode == "519" and _pair(remote, entries, mode, stamp):
        return ALREADY_PUBLISHED
    candidate = f"receipts/{stamp[:4]}/{stamp[4:6]}/{stamp[6:8]}/{stamp}-n{mode}.json.gz"
    # A local untracked file must never be overwritten or treated as a scan
    # opportunity; a remote authentic pair was already checked above.
    if Path(candidate).exists() or Path(candidate).is_symlink():
        raise PreflightBlocked("DUPLICATE_EPOCH_NO_SCAN")
    if l != r:
        raise PreflightBlocked("STALE_HEAD_WITHOUT_VALID_EPOCH")
    if candidate in entries:
        raise PreflightBlocked("DUPLICATE_EPOCH_UNVERIFIED")
    return ALLOW_SCAN


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True)
    parser.add_argument("--stamp", required=True)
    args = parser.parse_args(argv)
    try:
        result = assess(args.mode, args.stamp)
    except PreflightBlocked as e:
        print("SOURCE_PREFLIGHT_FAIL_CLOSED " + str(e))
        return 2
    if result == ALREADY_PUBLISHED:
        print("SOURCE_ALREADY_PUBLISHED_AUTHENTIC_PAIR_NO_SCAN_NOT_NEW_SOURCE_PASS")
        return 20
    print("SOURCE_PREFLIGHT_ALLOW_SCAN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
