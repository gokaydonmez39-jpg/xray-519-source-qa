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
        "dry": True,  # API executes without persisting query results.
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
    worker = event.get("$workers")
    version = worker.get("scriptVersion") if isinstance(worker, dict) else None
    v = version.get("id") if isinstance(version, dict) else None
    return v if isinstance(v, str) and VERSION_RE.fullmatch(v) else None

def _proof_with_diagnostics(events, end_stamp):
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
    observed_hours = set()
    current_hour_ms = int(end.timestamp()*1000)
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
        trigger = worker.get("event")
        cron = trigger.get("cron") if isinstance(trigger, dict) else None
        if not isinstance(cron, str) or cron not in ALLOWED_CRONS:
            continue
        hour_ms = (stamp_ms // 3_600_000) * 3_600_000
        observed_hours.add(hour_ms)
        if worker.get("outcome") != "ok":
            continue
        version = _version(ev)
        if not version:
            continue
        if not ALLOWED_CRONS[cron] <= stamp_ms - hour_ms <= ALLOWED_CRONS[cron] + 90_000:
            continue
        epoch = datetime.fromtimestamp(hour_ms/1000,timezone.utc).strftime("%Y%m%dT%H00Z")
        # A trace may only bind to one scheduled invocation.
        roots.setdefault(trace, set()).add((epoch, version, stamp_ms))
    current_roots = {trace: links for trace, links in roots.items()
                     if len(links) == 1 and next(iter(links))[0] == end_stamp}
    current_parent_logs = 0
    current_accepted_logs = 0
    current_without_run_id = 0
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
        at_ms = ev.get("timestamp")
        if not isinstance(trace, str) or type(at_ms) is not int or not low <= at_ms < high:
            continue
        root = roots.get(trace, set())
        if len(root) != 1:
            continue
        payload = _log_payload(ev)
        current_trace = trace in current_roots
        if current_trace:
            current_parent_logs += 1
        if not payload or payload.get("decision") != "DISPATCH_ACCEPTED_NOT_SOURCE_PASS":
            continue
        stamp, run_id = payload.get("stamp"), payload.get("runId")
        if not isinstance(stamp, str) or not STAMP_RE.fullmatch(stamp):
            continue
        if current_trace and stamp == end_stamp:
            current_accepted_logs += 1
        if type(run_id) is not int or run_id <= 0:
            if current_trace and stamp == end_stamp:
                current_without_run_id += 1
            continue
        version = _version(ev)
        if not version or not any(ep == stamp and ver == version and
                abs(stamp_ms - at_ms) <= 60_000
                for ep, ver, stamp_ms in root):
            continue
        if stamp in candidates and candidates[stamp] != run_id:
            conflicts.add(stamp)
        else:
            candidates[stamp] = run_id
    for stamp in conflicts:
        candidates.pop(stamp, None)
    if end_stamp in candidates:
        reason = "EXACT_CLOUDFLARE_RUN_PROOF_OBSERVED"
    elif end_stamp in conflicts:
        reason = "CONFLICTING_CLOUDFLARE_RUN_IDS"
    elif current_hour_ms not in observed_hours:
        reason = "NO_SCHEDULED_LOG_FOR_EPOCH_IN_QUERY"
    elif not current_roots:
        reason = "NO_UNAMBIGUOUS_ELIGIBLE_SCHEDULED_ROOT"
    elif current_parent_logs == 0:
        reason = "NO_SAME_TRACE_DISPATCH_LOG_IN_QUERY"
    elif current_accepted_logs == 0:
        reason = "NO_SAME_EPOCH_ACCEPTED_DISPATCH_LOG_IN_QUERY"
    elif current_without_run_id == current_accepted_logs:
        reason = "ACCEPTED_DISPATCH_LOG_WITHOUT_EXACT_RUN_ID"
    else:
        reason = "ACCEPTED_DISPATCH_VERSION_OR_CLOCK_NOT_PROVEN"
    diagnostics = {
        "schema": "XRAY_CLOUDFLARE_ORIGIN_OBSERVATION_V1",
        "queried_epoch_count": 48,
        "epochs_with_observed_scheduled_log": len(observed_hours),
        "epochs_with_exact_correlation": len(candidates),
        "current_epoch_reason": reason,
    }
    return candidates, diagnostics

def prove(events, end_stamp):
    return _proof_with_diagnostics(events, end_stamp)[0]

def from_query_response(payload, end_stamp, *, include_diagnostics=False):
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
    result = _proof_with_diagnostics(records, end_stamp)
    return result if include_diagnostics else result[0]

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
            trigger=w.get("event")
            cron=trigger.get("cron") if isinstance(trigger,dict) else None
            if isinstance(cron,str) and cron in ALLOWED_CRONS:
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
        if len({_enum(x.get("decision"), _DIAG_DECISIONS) for x in decisions})>1:
            status="UNKNOWN"
        elif not decisions:
            status="UNKNOWN"
        else:
            last=decisions[-1]
            decision=_enum(last.get("decision"), _DIAG_DECISIONS)
            lock=(last.get("duplicateLock") or {})
            if (root["cron"]=="6 * * * *" and decision=="DUPLICATE_EPOCH_LOCKED"
                    and isinstance(lock,dict) and
                    _enum(lock.get("state"), HANDLED_DUPLICATE_STATES) in HANDLED_DUPLICATE_STATES):
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

# Public diagnostic only: bounded, fixed enum output. Never an admission gate.
_DIAG_DECISIONS = ACCEPTED_DECISIONS | frozenset({
    "INVALID_SCHEDULE", "STALE_OR_EARLY_CRON", "SECRET_NOT_CONFIGURED",
    "BAD_ADAPTER", "LOCK_STORAGE_FAILURE", "DUPLICATE_EPOCH_LOCKED",
    "POST_RESERVATION_AUDIT_FAILURE", "SOURCE_RECEIPT_LOOKUP_UNAVAILABLE",
    "GITHUB_RUNS_UNAVAILABLE", "GITHUB_RUNS_INDETERMINATE",
    "GITHUB_RUN_TIME_INVALID", "DISPATCH_REJECTED",
    "GITHUB_PRE_DISPATCH_NETWORK_ERROR", "GITHUB_NETWORK_OR_RESPONSE_UNKNOWN",
})
_DIAG_LOCKS = HANDLED_DUPLICATE_STATES | _DIAG_DECISIONS | frozenset(
    "BACKUP_" + value for value in _DIAG_DECISIONS
) | frozenset({"RESERVED", "BACKUP_RESERVED_PREPOST", "GITHUB_HTTP_ACCESS_BLOCKED",
               "ABSENT", "READBACK_UNAVAILABLE", "UNKNOWN_STATE"})

def _enum(value, allowed):
    return value if isinstance(value, str) and value in allowed else "UNKNOWN"

def summarize_epoch_incidents(events, end_stamp):
    """Attribute sanitized failures to observed UTC cron slots, never to a trade.
    Missing, duplicate or mismatched telemetry is explicitly unknown.
    No new API query, no trace IDs, arbitrary log messages or credentials.
    """
    end = end_epoch(end_stamp)
    end_ms = int(end.timestamp()*1000)
    low = end_ms - 47*3600000
    high = end_ms + 600000
    if not isinstance(events, list) or len(events) > MAX_EVENTS:
        raise ProvenanceError("CLOUDFLARE_EVENT_RANGE_INVALID")
    groups = {}
    for e in events:
        if not isinstance(e, dict):
            continue
        m, w, at = e.get("$metadata"), e.get("$workers"), e.get("timestamp")
        if not isinstance(m, dict) or not isinstance(w, dict):
            continue
        if m.get("service") != SCRIPT or w.get("scriptName") != SCRIPT:
            continue
        trace = m.get("traceId")
        if not isinstance(trace, str) or not TRACE_RE.fullmatch(trace) or type(at) is not int or not low <= at < high:
            continue
        g = groups.setdefault(trace, {"roots": [], "logs": []})
        if m.get("type") == "cf-worker-event" and w.get("eventType") == "scheduled":
            event = w.get("event")
            cron = event.get("cron") if isinstance(event, dict) else None
            if isinstance(cron, str) and cron in ALLOWED_CRONS:
                g["roots"].append((at, cron, _version(e), w.get("outcome") == "ok"))
        elif m.get("type") in ("cf-worker", "cf-worker-log") and w.get("eventType") == "fetch" and w.get("entrypoint") == "SourceDispatchLock":
            p = _log_payload(e)
            if isinstance(p, dict):
                g["logs"].append((at, _version(e), p))
    # Only known upstream HTTP failure decisions may carry a numeric status.
    status_decisions = {"DISPATCH_REJECTED", "GITHUB_RUNS_UNAVAILABLE", "SOURCE_RECEIPT_LOOKUP_UNAVAILABLE"}
    slots = {}
    for g in groups.values():
        for at, cron, version, ok in g["roots"]:
            hour = at//3600000*3600000
            stamp = datetime.fromtimestamp(hour/1000, timezone.utc).strftime("%Y%m%dT%H00Z")
            slot = slots.setdefault((hour, cron), [])
            if len(g["roots"]) != 1:
                slot.append(("AMBIGUOUS_ROOT", "UNKNOWN", "UNKNOWN", None))
                continue
            if not ALLOWED_CRONS[cron] <= at-hour <= ALLOWED_CRONS[cron]+90000:
                slot.append(("OUTSIDE_NOMINAL_WINDOW", "UNKNOWN", "UNKNOWN", None))
                continue
            decisions = set()
            for log_at, log_version, p in g["logs"]:
                if not version or version != log_version or abs(log_at-at)>60000 or p.get("stamp") != stamp:
                    continue
                lock = p.get("duplicateLock")
                state = _enum(lock.get("state"), _DIAG_LOCKS) if isinstance(lock, dict) else "UNKNOWN"
                decision = _enum(p.get("decision"), _DIAG_DECISIONS)
                code = p.get("httpStatus")
                code = code if decision in status_decisions and type(code) is int and 100 <= code <= 599 else None
                decisions.add((decision, state, code))
            if len(decisions) != 1:
                slot.append(("MISSING_MATCHED_DECISION" if not decisions else "CONFLICTING_DECISIONS", "UNKNOWN", "UNKNOWN", None))
                continue
            decision, lock, code = next(iter(decisions))
            if decision == "UNKNOWN":
                status = "UNKNOWN_DECISION"
            elif cron == "6 * * * *" and decision == "DUPLICATE_EPOCH_LOCKED" and lock in HANDLED_DUPLICATE_STATES:
                status = "EXPECTED_BACKUP_DUPLICATE"
            elif ok and decision in ACCEPTED_DECISIONS:
                status = "ACCEPTED_NOT_SOURCE_PASS"
            else:
                status = "FAILURE_OR_HOLD"
            slot.append((status, decision, lock, code))
    good = {"ACCEPTED_NOT_SOURCE_PASS", "EXPECTED_BACKUP_DUPLICATE"}
    rows = []
    for hour in range(low, end_ms+1, 3600000):
        row = {"epoch_utc": datetime.fromtimestamp(hour/1000, timezone.utc).strftime("%Y-%m-%dT%H:00:00Z")}
        for cron, label in (("1 * * * *", "primary"), ("6 * * * *", "backup")):
            found = slots.get((hour, cron), [])
            status, decision, lock, code = found[0] if len(found)==1 else (
                "NO_SCHEDULED_LOG" if not found else "MULTIPLE_ROOTS", "UNKNOWN", "UNKNOWN", None)
            row[label] = {"status":status,"decision":decision,"lock_state":lock,"root_count":len(found),"http_status":code}
        if any(row[label]["status"] not in good for label in ("primary","backup")):
            rows.append(row)
    return {"schema":"XRAY_CF_EPOCH_INCIDENTS_V1", "release_authority":False,
            "queried_epochs":48, "incident_epochs":rows}

def _fetch_dry_query(query, account_id, token, transport=None):
    """Only POST query, never write Worker code, data, schedules or secrets.

    Token and response bodies are never included in failures or printed.
    A Worker Metadata Read-Only role should be considered first, but current
    telemetry query endpoint documents Workers Observability Write permission;
    require separate credential review before enabling this capability.
    """
    if not (isinstance(account_id, str) and re.fullmatch(r"[a-f0-9]{32}", account_id)
            and isinstance(token, str) and len(token) >= 20):
        raise ProvenanceError("CLOUDFLARE_READ_CREDENTIALS_MISSING")
    if query.get("dry") is not True:
        raise ProvenanceError("CLOUDFLARE_NON_DRY_QUERY_BLOCKED")
    body = json.dumps(query, separators=(",", ":")).encode()
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
    return payload

def fetch_verified(end_stamp, account_id, token, transport=None, include_summary=False):
    payload = _fetch_dry_query(query_body(end_stamp), account_id, token, transport)
    if not include_summary:
        return from_query_response(payload, end_stamp)
    proof, diagnostics = from_query_response(payload, end_stamp, include_diagnostics=True)
    summary = summarize_invocations(payload["result"]["events"]["events"], end_stamp)
    summary["origin_observation"] = diagnostics
    summary["epoch_incident_diagnostics"] = summarize_epoch_incidents(payload["result"]["events"]["events"], end_stamp)
    return proof, summary

# Diagnostic-only comparison. Fixed historical evidence; never used by a gate.
COMPARISON_EPOCH = "20261119T1400Z"
COMPARISON_RUN = 44539384391

def compare_fixed_window(account_id, token, transport=None):
    """Same filter/cutoff, two bounded dry reads. Publish only sanitized counters."""
    h = int(end_epoch(COMPARISON_EPOCH).timestamp()*1000)
    out = {"schema": "XRAY_CF_FIXED_WINDOW_COMPARISON_V1",
           "stamp": COMPARISON_EPOCH, "release_authority": False}
    for label in ("wide", "one_hour"):
        query = query_body(COMPARISON_EPOCH)
        query["queryId"] = "xray-519-fixed-window-diagnostic-v1"
        if label == "one_hour":
            query["timeframe"]["from"] = query["timeframe"]["to"] - 3_600_000
        frame = query["timeframe"]
        try:
            payload = _fetch_dry_query(query, account_id, token, transport)
            proof, diag = from_query_response(payload, COMPARISON_EPOCH, include_diagnostics=True)
        except ProvenanceError as exc:
            code = str(exc)
            out[label] = {"status": code if re.fullmatch(r"[A-Z_]{1,90}", code)
                          else "CLOUDFLARE_DIAGNOSTIC_FAILED"}
            continue
        result = payload["result"]
        echoed = result["run"].get("timeframe")
        echo = "NOT_RETURNED"
        if echoed is not None:
            echo = "MATCHED" if echoed == frame else "MISMATCH"
        rows = result["events"]["events"]
        if any(type(r.get("timestamp")) is not int or
               not frame["from"] <= r["timestamp"] < frame["to"] for r in rows):
            out[label] = {"status": "RETURNED_ROWS_OUTSIDE_REQUEST_WINDOW"}
            continue
        stats = result.get("statistics")
        if not isinstance(stats, dict):
            stats = result["run"].get("statistics")
        if not isinstance(stats, dict):
            stats = {}
        abr = stats.get("abr_level")
        if type(abr) not in (int, float) or not 0 <= abr <= 1_000_000_000:
            abr = None
        match = proof.get(COMPARISON_EPOCH)
        out[label] = {"status": "OBSERVED" if echo != "MISMATCH" else "TIMEFRAME_ECHO_MISMATCH",
                      "timeframe_echo": echo, "total_rows": len(rows),
                      "target_rows": sum(h <= r["timestamp"] < frame["to"] for r in rows),
                      "origin_reason": diag["current_epoch_reason"],
                      "exact_expected_run": match == COMPARISON_RUN,
                      "other_run_returned": match is not None and match != COMPARISON_RUN,
                      "query_abr_level": abr}
    return out
