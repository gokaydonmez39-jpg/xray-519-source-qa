"""Research-only create-only publisher for a separate public evidence ref.

NOT wired to a production workflow. The code branch remains main; immutable
hourly receipts/bridges may be appended to an independent evidence ref only
after a reviewed migration. No orders, alerts, secrets, direct API trading or
historical backfill.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

from ops.evidence_ref_pair_audit import PairRejected, audit_pair

EVIDENCE_BRANCH = "xray-source-evidence"
SHA = re.compile(r"[0-9a-f]{40}\Z")
PATH = re.compile(
    r"(receipts|bridges)/\d{4}/\d{2}/\d{2}/\d{8}T\d{2}00Z-n([1-9]\d{0,2})\.json\.gz\Z"
)


class EvidenceBlocked(ValueError):
    pass


def git(*args: str, env: dict | None = None, check: bool = True,
        stdin: bytes | None = None) -> subprocess.CompletedProcess:
    cmd = ["git", *args]
    r = subprocess.run(cmd, input=stdin, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, env=env, timeout=30, check=False)
    if check and r.returncode:
        # Never echo stderr; remotes can contain credentials.
        raise EvidenceBlocked("GIT_FAILED_" + args[0].upper())
    return r


def out(*args: str) -> str:
    return git(*args).stdout.decode("ascii").strip()


def tree(sha: str) -> dict[str, tuple[str, str, str]]:
    entries = {}
    for item in git("ls-tree", "-rz", sha).stdout.split(b"\0"):
        if not item:
            continue
        meta, filename = item.split(b"\t", 1)
        mode, kind, blob = meta.decode("ascii").split()
        entries[filename.decode("utf-8")] = (mode, kind, blob)
    return entries


def path_contract(paths: tuple[str, ...]) -> None:
    if len(paths) != 2 or len(set(paths)) != 2:
        raise EvidenceBlocked("PAIR_CARDINALITY_INVALID")
    receipts = [p for p in paths if p.startswith("receipts/")]
    if len(receipts) != 1:
        raise EvidenceBlocked("RECEIPT_REQUIRED")
    receipt = receipts[0]
    if set(paths) != {receipt, receipt.replace("receipts/", "bridges/", 1)}:
        raise EvidenceBlocked("PAIR_PATHS_DIVERGE")
    match = PATH.fullmatch(receipt)
    if match is None or not 401 <= int(match.group(2)) <= 564:
        raise EvidenceBlocked("DYNAMIC_IDENTITY_PATH_INVALID")
    if not all(PATH.fullmatch(p) for p in paths):
        raise EvidenceBlocked("UNSAFE_EVIDENCE_PATH")


def append_pair(*, code_base: str, evidence_origin: str,
                paths: tuple[str, str], attempts: int = 3,
                shadow_source_main: bool = False) -> dict:
    """Run only in a clean Github Actions checkout with two new local files.

    Precondition: an authorized administrator initialized evidence branch at
    evidence_origin, without any extra hourly task or replacing production
    consumers. This routine never pushes main.
    """
    if (not SHA.fullmatch(code_base) or not SHA.fullmatch(evidence_origin)
            or not 1 <= attempts <= 3):
        raise EvidenceBlocked("UNTRUSTED_RELEASE_REFERENCE")
    path_contract(paths)
    original, staged = tree(code_base), tree("HEAD")
    if out("rev-parse", "HEAD") == code_base:
        raise EvidenceBlocked("LOCAL_PAIR_COMMIT_MISSING")
    changes = {p for p in original.keys() | staged.keys()
               if original.get(p) != staged.get(p)}
    if changes != set(paths) or any(p in original for p in paths):
        raise EvidenceBlocked("LOCAL_NON_CREATE_ONLY_CHANGE")
    if git("diff", "--quiet", "HEAD", check=False).returncode:
        raise EvidenceBlocked("DIRTY_TRACKED_WORKTREE")
    buffers = {}
    for path in paths:
        if staged[path][:2] != ("100644", "blob"):
            raise EvidenceBlocked("UNSAFE_BLOB_MODE")
        content = git("show", "HEAD:" + path).stdout
        cap = 200_000 if path.startswith("receipts/") else 8_388_608
        if not 0 < len(content) <= cap:
            raise EvidenceBlocked("BLOB_SIZE_INVALID")
        buffers[path] = content

    # Before any remote ref update, reject mismatched/grafted source evidence.
    checked = audit_pair(
        buffers[paths[0] if paths[0].startswith("receipts/") else paths[1]],
        buffers[paths[0] if paths[0].startswith("bridges/") else paths[1]],
        next(p for p in paths if p.startswith("receipts/")),
        next(p for p in paths if p.startswith("bridges/")),
    )
    if type(shadow_source_main) is not bool:
        raise EvidenceBlocked("INVALID_SHADOW_RELEASE_MODE")
    # NO_BACKFILL: evidence-ref writes only for the current genuine UTC H.
    # Time-window < H+15 remains a separate live source/private acceptance
    # check; this local shadow projection never claims that acceptance.
    if checked["epoch_utc"][:13] != datetime.now(timezone.utc).strftime("%Y-%m-%dT%H"):
        raise EvidenceBlocked("NOT_CURRENT_UTC_HOUR_NO_BACKFILL")
    for _ in range(attempts):
        # In shadow mode, the existing canonical publisher has *already*
        # appended exactly this pair to main. Verify no executable source
        # change, missing half-pair, other epoch, or bytes mismatch.
        git("fetch", "--no-tags", "origin", "refs/heads/main")
        remote_main = out("rev-parse", "FETCH_HEAD")
        if shadow_source_main:
            current = tree(remote_main)
            changed = {p for p in original.keys() | current.keys()
                       if original.get(p) != current.get(p)}
            if (changed != set(paths)
                    or any(current.get(p) != staged[p] for p in paths)):
                raise EvidenceBlocked("SHADOW_MAIN_NOT_EXACT_VERIFIED_PAIR")
        elif remote_main != code_base:
            raise EvidenceBlocked("CODE_MAIN_CHANGED_DURING_SCAN")
        git("fetch", "--no-tags", "origin",
            "refs/heads/" + EVIDENCE_BRANCH)
        remote = out("rev-parse", "FETCH_HEAD")
        if git("merge-base", "--is-ancestor", evidence_origin, remote,
               check=False).returncode:
            raise EvidenceBlocked("EVIDENCE_HISTORY_NOT_DESCENDANT")
        # Evidence history may append files only, never alter old receipts,
        # source Python, workflows or any other tracked code.
        diff = git("diff", "--name-status", evidence_origin, remote).stdout
        for item in diff.decode("utf-8").splitlines():
            status, _, filename = item.partition("\t")
            if status != "A" or PATH.fullmatch(filename) is None:
                raise EvidenceBlocked("EVIDENCE_REF_NON_APPEND_CHANGE")
        existing = tree(remote)
        collisions = [p for p in paths if p in existing]
        if collisions:
            if len(collisions) != 2 or any(
                existing[p] != staged[p] for p in paths
            ):
                raise EvidenceBlocked("IMMUTABLE_EPOCH_COLLISION")
            committed = remote  # lost acknowledgment, exact bytes already live
        else:
            with tempfile.TemporaryDirectory(prefix="xray-evref-index-") as tmp:
                idx = dict(os.environ, GIT_INDEX_FILE=str(Path(tmp) / "index"))
                git("read-tree", remote, env=idx)
                for path in paths:
                    git("update-index", "--add", "--cacheinfo",
                        "100644", staged[path][2], path, env=idx)
                newtree = git("write-tree", env=idx).stdout.decode().strip()
            committed = git(
                "commit-tree", newtree, "-p", remote,
                stdin=b"research: create-only evidence-ref pair [skip ci]\n"
            ).stdout.decode("ascii").strip()
            pushed = git(
                "push", "origin",
                committed + ":refs/heads/" + EVIDENCE_BRANCH,
                check=False
            )
            if pushed.returncode:
                continue  # bounded CAS retry after refetch
        git("fetch", "--no-tags", "origin",
            "refs/heads/" + EVIDENCE_BRANCH)
        readback = out("rev-parse", "FETCH_HEAD")
        if git("merge-base", "--is-ancestor", committed, readback,
               check=False).returncode:
            raise EvidenceBlocked("REMOTE_READBACK_ANCESTRY_INVALID")
        verified = tree(readback)
        for path in paths:
            if verified.get(path) != staged[path]:
                raise EvidenceBlocked("REMOTE_BLOB_MODE_OR_SHA_MISMATCH")
            real = hashlib.sha256(
                git("show", readback + ":" + path).stdout
            ).hexdigest()
            if real != hashlib.sha256(buffers[path]).hexdigest():
                raise EvidenceBlocked("REMOTE_BYTES_SHA256_MISMATCH")
        git("fetch", "--no-tags", "origin", "refs/heads/main")
        if out("rev-parse", "FETCH_HEAD") != remote_main:
            raise EvidenceBlocked("CODE_OR_SOURCE_DRIFT_AFTER_READBACK")
        return {
            "status": ("SHADOW_EVIDENCE_REF_PAIR_DURABLE_READBACK_NO_LIVE_CONSUMER"
                       if shadow_source_main else "EVIDENCE_REF_PAIR_DURABLE_READBACK_ONLY"),
            "code_main_unchanged": not shadow_source_main,
            "source_main_exact_pair_verified": shadow_source_main,
            "evidence_branch": EVIDENCE_BRANCH,
            "evidence_commit": readback,
            "source_code_sha": code_base,
            "files": [{"path": p, "sha256": hashlib.sha256(buffers[p]).hexdigest()}
                      for p in sorted(paths)],
            "research_only": True,
            "orders_sent": 0,
            "notifications_sent": 0,
            "full_final_start": False,
        }
    raise EvidenceBlocked("CONCURRENT_EVIDENCE_PUSH_RETRY_EXHAUSTED")


def main() -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--code-base", required=True)
    p.add_argument("--evidence-origin", required=True)
    p.add_argument("--shadow-source-main", action="store_true",
                   help="verify the already-published exact pair on main; never publish to main")
    p.add_argument("receipt")
    p.add_argument("bridge")
    args = p.parse_args()
    try:
        result = append_pair(code_base=args.code_base,
                             evidence_origin=args.evidence_origin,
                             paths=(args.receipt, args.bridge),
                             shadow_source_main=args.shadow_source_main)
    except (EvidenceBlocked, PairRejected, OSError, subprocess.TimeoutExpired, UnicodeError):
        print(json.dumps({"status": "HOLD_EVIDENCE_REF_NOT_PUBLISHED",
                          "research_only": True, "orders_sent": 0}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
