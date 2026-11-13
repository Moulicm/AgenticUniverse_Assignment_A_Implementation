from __future__ import annotations

import csv
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

from database import count
from security import PIIProtector

CSV_HEADERS = {
    "batch_summary.csv": ["workflow_id", "batch_id", "total_leads", "yet_to_reach_out", "in_progress_telephony_failed", "in_progress_dialed", "completed"],
    "daily_overview.csv": ["workflow_id", "date", "total_calls", "connected_calls", "connectivity_rate", "success_leads"],
    "lead_report.csv": ["workflow_id", "external_ref", "batch_id", "phone_masked", "bucket", "total_calls", "connected_calls", "last_call_at", "current_disposition", "ever_success"],
    "rejections.csv": ["workflow_id", "batch_id", "row_number", "reason"],
}


def _write_csv(path: Path, headers: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=headers, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _effective_disposition(events: list[sqlite3.Row], dispositions: dict) -> tuple[str | None, dict | None]:
    overrides = [e for e in events if e["event_type"] == "disposition.override"]
    candidates = overrides or [e for e in events if e["event_type"] == "disposition.set"]
    if not candidates:
        return None, None
    chosen = max(candidates, key=lambda e: (e["occurred_at"], e["event_id"]))
    code = json.loads(chosen["payload_json"]).get("disposition_code")
    return code, dispositions.get(code)


def generate_reports(db: sqlite3.Connection, out_dir: Path, protector: PIIProtector, disposition_path: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    dispositions: dict[str, dict] = {}
    with disposition_path.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            dispositions.setdefault(row["workflow_id"], {})[row["code"]] = {
                "is_terminal": row["is_terminal"].strip().lower() == "true",
                "is_success": row["is_success"].strip().lower() == "true",
            }

    leads = db.execute("SELECT * FROM leads ORDER BY workflow_id,external_ref").fetchall()
    ledger = db.execute("SELECT * FROM interaction_ledger ORDER BY occurred_at,event_id").fetchall()
    by_lead: dict[int, list[sqlite3.Row]] = defaultdict(list)
    by_call: dict[tuple[str, str], list[sqlite3.Row]] = defaultdict(list)
    for event in ledger:
        by_lead[event["lead_id"]].append(event)
        if event["call_id"]:
            by_call[(event["workflow_id"], event["call_id"])].append(event)

    lead_rows: list[dict] = []
    buckets: dict[int, str] = {}
    call_records: list[dict] = []
    for lead in leads:
        events = by_lead[lead["lead_id"]]
        initiated = [e for e in events if e["event_type"] == "call.initiated"]
        calls: list[dict] = []
        for init in initiated:
            call_events = [e for e in by_call.get((lead["workflow_id"], init["call_id"]), []) if e["lead_id"] == lead["lead_id"]]
            code, disp = _effective_disposition(call_events, dispositions.get(lead["workflow_id"], {}))
            calls.append({"call_id": init["call_id"], "date": init["occurred_at"][:10], "initiated_at": init["occurred_at"], "connected": any(e["event_type"] == "call.connected" for e in call_events), "telephony_failed": any(e["event_type"] == "call.telephony_failed" for e in call_events), "disposition": code, "disposition_meta": disp})
        calls.sort(key=lambda c: (c["initiated_at"], c["call_id"] or ""))
        if not calls:
            bucket = "yet_to_reach_out"
        elif any(c["disposition_meta"] and c["disposition_meta"]["is_terminal"] for c in calls):
            bucket = "completed"
        elif all(c["telephony_failed"] for c in calls):
            bucket = "in_progress_telephony_failed"
        else:
            bucket = "in_progress_dialed"
        buckets[lead["lead_id"]] = bucket
        phone = protector.decrypt(lead["phone_cipher"])
        latest_call = calls[-1] if calls else None
        current = next((c["disposition"] for c in reversed(calls) if c["disposition"] is not None), None)
        ever_success = any(c["disposition_meta"] and c["disposition_meta"]["is_success"] for c in calls)
        lead_rows.append({"workflow_id": lead["workflow_id"], "external_ref": lead["external_ref"], "batch_id": lead["batch_id"], "phone_masked": "+91******" + phone[-4:], "bucket": bucket, "total_calls": len(calls), "connected_calls": sum(1 for c in calls if c["connected"]), "last_call_at": latest_call["initiated_at"] if latest_call else "", "current_disposition": current or "", "ever_success": str(bool(ever_success)).lower()})
        for call in calls:
            call_records.append({"workflow_id": lead["workflow_id"], "lead_id": lead["lead_id"], **call})

    batch_counts: dict[tuple[str, str], dict] = {}
    for lead in leads:
        key = (lead["workflow_id"], lead["batch_id"])
        bucket = buckets[lead["lead_id"]]
        row = batch_counts.setdefault(key, {h: 0 for h in CSV_HEADERS["batch_summary.csv"][2:]})
        row["total_leads"] += 1
        row[bucket] += 1
    batch_rows = [{"workflow_id": w, "batch_id": b, **vals} for (w, b), vals in sorted(batch_counts.items())]
    _write_csv(out_dir / "batch_summary.csv", CSV_HEADERS["batch_summary.csv"], batch_rows)

    daily: dict[tuple[str, str], dict] = {}
    success_leads: dict[tuple[str, str], set[int]] = defaultdict(set)
    for call in call_records:
        key = (call["workflow_id"], call["date"])
        row = daily.setdefault(key, {"total_calls": 0, "connected_calls": 0})
        row["total_calls"] += 1
        row["connected_calls"] += int(call["connected"])
        if call["disposition_meta"] and call["disposition_meta"]["is_success"]:
            success_leads[key].add(call["lead_id"])
    daily_rows = []
    for (workflow, day), vals in sorted(daily.items()):
        total = vals["total_calls"]
        daily_rows.append({"workflow_id": workflow, "date": day, "total_calls": total, "connected_calls": vals["connected_calls"], "connectivity_rate": f"{vals['connected_calls'] / total:.4f}", "success_leads": len(success_leads[(workflow, day)])})
    _write_csv(out_dir / "daily_overview.csv", CSV_HEADERS["daily_overview.csv"], daily_rows)

    _write_csv(out_dir / "lead_report.csv", CSV_HEADERS["lead_report.csv"], lead_rows)
    rejection_rows = [dict(row) for row in db.execute("SELECT workflow_id,batch_id,row_number,reason FROM rejection_rows ORDER BY workflow_id,batch_id,row_number")]
    _write_csv(out_dir / "rejections.csv", CSV_HEADERS["rejections.csv"], rejection_rows)

    reason_counts = {row["reason"]: row["value"] for row in db.execute("SELECT reason,value FROM rejection_reason_counts ORDER BY reason")}
    quality = {
        "lead_rows_total": count(db, "lead_rows_total"),
        "lead_rows_rejected": count(db, "lead_rows_rejected"),
        "rejections_by_reason": reason_counts,
        "duplicate_lead_rows_merged": count(db, "duplicate_lead_rows_merged"),
        "field_warnings": count(db, "field_warnings"),
        "events_total": count(db, "events_total"),
        "malformed_events": count(db, "malformed_events"),
        "duplicate_events_dropped": count(db, "duplicate_events_dropped"),
        "orphan_events": db.execute("SELECT COUNT(*) FROM events WHERE state='pending'").fetchone()[0],
        "unknown_disposition_events": count(db, "unknown_disposition_events"),
    }
    (out_dir / "data_quality.json").write_text(json.dumps(quality, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
