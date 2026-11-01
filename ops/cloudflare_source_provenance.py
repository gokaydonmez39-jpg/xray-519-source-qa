"""Fail-closed Cloudflare Workers Logs origin evidence for XRAY-519.

Read-only telemetry query. Never dispatches a job, trades, edits any durable
state or treats accepted GitHub dispatch as verified source completion.
Returns only validated source epoch -> exact GitHub Actions workflow run ID.
This is NOT a production attestation until real Cloudflare API response
structure and permissions are independently verified.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

SCRIPT = "xray-519-source-qa"
VERSION_RE = re.compile(r"^[a-f0-9-]{36}$")
STAMP_RE = re.compile(r"^\d{8}T\d{2}00Z$")
TRACE_RE = re.compile(r"^[a-f0-9]{32}$")
MAX_EVENTS = 2000
MAX_RESPONSE_BYTES = 4_000_000
ALLOWED_CRONS = {"1 * * * *": 60_000, "6 * * * *": 360_000}

class ProvenanceError(ValueError):
    pass

def end_epoch(stamp):
    if not isinstance(stamp, str) or not STAMP_RE.fullmatch(stamp):
        raise ProvenanceError("INVALID_EPOCH_STAMP")
    try:
        ts = datetime.strptime(stamp, "%Y%m%dT%H00Z").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ProvenanceError("INVALID_EPOCH_STAMP") from exc
    if ts.strftime("%Y%m%dT%H00Z") != stamp:
        raise ProvenanceError("INVALID_EPOCH_STAMP")
    return ts

def query_body(end_stamp):
    end = end_epoch(end_stamp)
    first = end - timedelta(hours=47)
    return {
        "queryId": "xray-519-readonly-origin-audit-v1",
        "timeframe": {
            "from": int(first.timestamp() * 1000),
            "to": int((end + timedelta(minutes=10)).timestamp() * 1000),
        },
        "view": "events",
        "chart": False,
        "limit": MAX_EVENTS,
        "parameters": {
            "datasets": [],  # Query all datasets; exact service filter applied.
            "filterCombination": "and",
            "filters": [
                {"key": "$metadata.service", "operation": "eq",
                 "type": "string", "value": SCRIPT},
            ],
        },
    }

def _log_payload(event):
    source = event.get("source")
    if isinstance(source, dict) and source.get("event") == "XRAY_PUBLIC_DISPATCH":
        return source
    candidates = []
    if isinstance(source, str):
        candidates.append(source)
    if isinstance(source, dict) and isinstance(source.get("message"), str):
        candidates.append(source["message"])
    meta = event.get("$metadata") or {}
    if isinstance(meta.get("message"), str):
        candidates.append(meta["message"])
    for item in candidates:
        if len(item) > 12_000:
            continue
        try:
            obj = json.loads(item)
        except (ValueError, TypeError):
            continue
        if isinstance(obj, dict) and obj.get("event") == "XRAY_PUBLIC_DISPATCH":
            return obj
    return None

def _version(event):
    worker = event.get("$workers") or {}
    v = (worker.get("scriptVersion") or {}).get("id")
    return v if isinstance(v, str) and VERSION_RE.fullmatch(v) else None

def prove(events, end_stamp):
    """Require scheduled invocation + DO dispatch log, same trace/version/hour.

    No console-line count is ever treated as number of failed source hours.
    Exclude duplicate, HOLD, incomplete, malformed or contradictory evidence.
    """
    end = end_epoch(end_stamp)
    first = end - timedelta(hours=47)
    low = int(first.timestamp() * 1000)
    high = int((end + timedelta(minutes=10)).timestamp() * 1000)
    if not isinstance(events, list) or len(events) > MAX_EVENTS:
        raise ProvenanceError("CLOUDFLARE_EVENT_RANGE_INVALID")
    roots = {}
    for ev in events:
        if not isinstance(ev, dict):
            raise ProvenanceError("CLOUDFLARE_EVENT_INVALID")
        meta, worker = ev.get("$metadata"), ev.get("$workers")
        if not isinstance(meta, dict) or not isinstance(worker, dict):
            continue
        if meta.get("service") != SCRIPT or worker.get("scriptName") != SCRIPT:
            continue
        trace = meta.get("traceId")
        if not isinstance(trace, str) or not TRACE_RE.fullmatch(trace):
            continue
        stamp_ms = ev.get("timestamp")
        if type(stamp_ms) is not int or not low <= stamp_ms < high:
            continue
        if meta.get("type") != "cf-worker-event" or worker.get("eventType") != "scheduled":
            continue
        if worker.get("outcome") != "ok":
            continue
        cron = (worker.get("event") or {}).get("cron")
        if cron not in ALLOWED_CRONS:
            continue
        version = _version(ev)
        if not version:
            continue
        hour_ms = (stamp_ms // 3_600_000) * 3_600_000
        if not ALLOWED_CRONS[cron] <= stamp_ms - hour_ms <= ALLOWED_CRONS[cron] + 90_000:
            continue
        epoch = datetime.fromtimestamp(hour_ms/1000,timezone.utc).strftime("%Y%m%dT%H00Z")
        # A trace may only bind to one scheduled invocation.
        roots.setdefault(trace, set()).add((epoch, version, stamp_ms))
    candidates = {}
    conflicts = set()
    for ev in events:
        meta, worker = ev.get("$metadata"), ev.get("$workers")
        if not isinstance(meta, dict) or not isinstance(worker, dict):
            continue
        if meta.get("service") != SCRIPT or worker.get("scriptName") != SCRIPT:
            continue
        if worker.get("entrypoint") != "SourceDispatchLock" or worker.get("eventType") != "fetch":
            continue
        if meta.get("type") not in ("cf-worker", "cf-worker-log"):
            continue
        trace = meta.get("traceId")
        root = roots.get(trace, set())
        if len(root) != 1:
            continue
        payload = _log_payload(ev)
        if not payload or payload.get("decision") != "DISPATCH_ACCEPTED_NOT_SOURCE_PASS":
            continue
        stamp, run_id = payload.get("stamp"), payload.get("runId")
        if not isinstance(stamp, str) or not STAMP_RE.fullmatch(stamp):
            continue
        if type(run_id) is not int or run_id <= 0:
            continue
        version = _version(ev)
        if not version or not any(ep == stamp and ver == version and
                abs(stamp_ms - ev["timestamp"]) <= 60_000
                for ep, ver, stamp_ms in root):
            continue
        if stamp in candidates and candidates[stamp] != run_id:
            conflicts.add(stamp)
        else:
            candidates[stamp] = run_id
    for stamp in conflicts:
        candidates.pop(stamp, None)
    return candidates

def from_query_response(payload, end_stamp):
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise ProvenanceError("CLOUDFLARE_QUERY_FAILED")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise ProvenanceError("CLOUDFLARE_QUERY_INVALID")
    run = result.get("run")
    if not isinstance(run, dict) or run.get("status") != "COMPLETED":
        raise ProvenanceError("CLOUDFLARE_QUERY_NOT_COMPLETED")
    events_obj = result.get("events")
    if not isinstance(events_obj, dict):
        raise ProvenanceError("CLOUDFLARE_QUERY_NO_EVENTS")
    records = events_obj.get("events")
    count = events_obj.get("count")
    # No partial page or unknown event count may establish trusted origin.
    if not isinstance(records, list) or type(count) is not int or count < 0:
        raise ProvenanceError("CLOUDFLARE_QUERY_INCOMPLETE")
    if count != len(records) or count >= MAX_EVENTS:
        raise ProvenanceError("CLOUDFLARE_QUERY_TRUNCATED")
    return prove(records, end_stamp)

HANDLED_DUPLICATE_STATES = frozenset({
    "DISPATCH_ACCEPTED_NOT_SOURCE_PASS",
    "BACKUP_DISPATCH_ACCEPTED_NOT_SOURCE_PASS",
    "EXISTING_SOURCE_RECEIPT", "EXISTING_SOURCE_RUN",
    "SOURCE_RUN_ALREADY_ACTIVE",
    "BACKUP_EXISTING_SOURCE_RECEIPT", "BACKUP_EXISTING_SOURCE_RUN",
    "BACKUP_SOURCE_RUN_ALREADY_ACTIVE",
})
ACCEPTED_DECISIONS = frozenset({
    "DISPATCH_ACCEPTED_NOT_SOURCE_PASS",
    "EXISTING_SOURCE_RECEIPT", "EXISTING_SOURCE_RUN",
    "SOURCE_RUN_ALREADY_ACTIVE",
})

def summarize_invocations(events, end_stamp):
    """Group log lines by a real scheduled trace, not by red event rows.

    Each actual scheduled invocation contributes at most one result. Multiple
    console errors and uncaught exception logs for the same trace are not
    multiple source failures. Unknown/missing diagnostic is NOT a success.
    """
    end = end_epoch(end_stamp)
    low = int((end-timedelta(hours=47)).timestamp()*1000)
    high = int((end+timedelta(minutes=10)).timestamp()*1000)
    if not isinstance(events,list) or len(events)>MAX_EVENTS:
        raise ProvenanceError("CLOUDFLARE_EVENT_RANGE_INVALID")
    groups = {}
    for e in events:
        if not isinstance(e,dict):
            continue
        m,w=e.get("$metadata"),e.get("$workers")
        if not isinstance(m,dict) or not isinstance(w,dict):
            continue
        if m.get("service")!=SCRIPT or w.get("scriptName")!=SCRIPT:
            continue
        tid=m.get("traceId")
        if not isinstance(tid,str) or not TRACE_RE.fullmatch(tid):
            continue
        at=e.get("timestamp")
        if type(at) is not int or not low<=at<high:
            continue
        group=groups.setdefault(tid,{"root":[],"logs":[]})
        if m.get("type")=="cf-worker-event" and w.get("eventType")=="scheduled":
            cron=(w.get("event") or {}).get("cron")
            if cron in ALLOWED_CRONS:
                group["root"].append({"cron":cron,"outcome":w.get("outcome"),"timestamp":at})
        elif m.get("type") in ("cf-worker", "cf-worker-log"):
            p=_log_payload(e)
            if isinstance(p,dict):
                group["logs"].append(p)
    statuses=[]
    for group in groups.values():
        if len(group["root"])!=1:
            continue
        root=group["root"][0]
        decisions=[log for log in group["logs"] if log.get("event")=="XRAY_PUBLIC_DISPATCH"]
        # Ambiguous duplicate log lines with differing decisions are HOLD.
        if len({x.get("decision") for x in decisions})>1:
            status="UNKNOWN"
        elif not decisions:
            status="UNKNOWN"
        else:
            last=decisions[-1]
            decision=last.get("decision")
            lock=(last.get("duplicateLock") or {})
            if (root["cron"]=="6 * * * *" and decision=="DUPLICATE_EPOCH_LOCKED"
                    and isinstance(lock,dict) and
                    lock.get("state") in HANDLED_DUPLICATE_STATES):
                status="EXPECTED_BACKUP_DUPLICATE"
            elif root["outcome"]=="ok" and decision in ACCEPTED_DECISIONS:
                status="ACCEPTED_NOT_SOURCE_PASS"
            elif decision=="DUPLICATE_EPOCH_LOCKED":
                status="LOCK_HOLD"
            else:
                status="FAILURE_OR_HOLD"
        statuses.append(status)
    return {
        "raw_log_rows":len(events),
        "distinct_scheduled_invocations":len(statuses),
        "expected_backup_duplicate":statuses.count("EXPECTED_BACKUP_DUPLICATE"),
        "accepted_not_source_pass":statuses.count("ACCEPTED_NOT_SOURCE_PASS"),
        "real_failures_or_holds":statuses.count("FAILURE_OR_HOLD")+statuses.count("LOCK_HOLD"),
        "unclassified_holds":statuses.count("UNKNOWN"),
    }

def fetch_verified(end_stamp, account_id, token, transport=None, include_summary=False):
    """Only POST query, never write Worker code, data, schedules or secrets.

    Token and response bodies are never included in failures or printed.
    A Worker Metadata Read-Only role should be considered first, but current
    telemetry query endpoint documents Workers Observability Write permission;
    require separate credential review before enabling this capability.
    """
    if not (isinstance(account_id, str) and re.fullmatch(r"[a-f0-9]{32}", account_id)
            and isinstance(token, str) and len(token) >= 20):
        raise ProvenanceError("CLOUDFLARE_READ_CREDENTIALS_MISSING")
    body = json.dumps(query_body(end_stamp), separators=(",", ":")).encode()
    req = urllib.request.Request(
        "https://api.cloudflare.com/client/v4/accounts/" + account_id +
        "/workers/observability/telemetry/query",
        data=body, method="POST",
        headers={"Authorization": "Bearer " + token,
                 "Content-Type": "application/json", "Accept": "application/json"},
    )
    runner = transport or urllib.request.urlopen
    try:
        with runner(req, timeout=12) as response:
            data = response.read(MAX_RESPONSE_BYTES + 1)
            if len(data) > MAX_RESPONSE_BYTES:
                raise ProvenanceError("CLOUDFLARE_QUERY_TOO_LARGE")
            payload = json.loads(data)
    except (urllib.error.HTTPError, urllib.error.URLError, OSError,
            TimeoutError, ValueError, TypeError) as exc:
        if isinstance(exc, ProvenanceError):
            raise
        raise ProvenanceError("CLOUDFLARE_QUERY_TRANSPORT_FAILED") from None
    proof = from_query_response(payload, end_stamp)
    if include_summary:
        return proof, summarize_invocations(payload["result"]["events"]["events"], end_stamp)
    return proof
