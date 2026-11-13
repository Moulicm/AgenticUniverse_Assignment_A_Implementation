from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from pathlib import Path

from database import add_count
from security import PIIProtector
from validation import normalise_header, normalise_phone, normalise_timestamp, validate_value


def _file_key(kind: str, path: Path, workflow: str | None) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"{kind}|{workflow or ''}|{path.name}|{digest}"


def _already_processed(db: sqlite3.Connection, key: str) -> bool:
    return db.execute("SELECT 1 FROM processed_files WHERE file_key=?", (key,)).fetchone() is not None


def _mark_processed(db: sqlite3.Connection, key: str, kind: str, path: Path, workflow: str | None) -> None:
    db.execute("INSERT INTO processed_files(file_key,kind,file_name,workflow_id) VALUES(?,?,?,?)", (key, kind, path.name, workflow))


def _header_map(headers: list[str], schema: dict) -> dict[str, int]:
    aliases: dict[str, str] = {}
    for field in schema["fields"]:
        for name in [field["name"], *field.get("aliases", [])]:
            aliases[normalise_header(name)] = field["name"]
    result: dict[str, int] = {}
    for index, header in enumerate(headers):
        field_name = aliases.get(normalise_header(header))
        if field_name and field_name not in result:
            result[field_name] = index
    return result


def ingest_lead_file(db: sqlite3.Connection, path: Path, workflow_id: str, schema: dict, protector: PIIProtector) -> None:
    key = _file_key("lead", path, workflow_id)
    if _already_processed(db, key):
        return
    batch_id = path.stem
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream)
        try:
            headers = next(reader)
        except StopIteration:
            _mark_processed(db, key, "lead", path, workflow_id)
            return
        mapping = _header_map(headers, schema)
        row_number = 0
        for row in reader:
            if not any((cell or "").strip() for cell in row):
                continue
            row_number += 1
            add_count(db, "lead_rows_total")
            values: dict[str, object | None] = {}
            errors: dict[str, str] = {}
            for field in schema["fields"]:
                name = field["name"]
                raw = row[mapping[name]] if name in mapping and mapping[name] < len(row) else ""
                value, error = validate_value(field, raw)
                values[name] = value
                if error:
                    errors[name] = error
            rejection = None
            for field in schema["fields"]:
                name = field["name"]
                if field.get("required") and values.get(name) is None:
                    rejection = "invalid_phone" if field["type"] == "phone" and errors.get(name) == "invalid_phone" else f"missing_required:{name}"
                    break
            if rejection:
                add_count(db, "lead_rows_rejected")
                db.execute("INSERT INTO rejection_rows(workflow_id,batch_id,row_number,reason) VALUES(?,?,?,?)", (workflow_id, batch_id, row_number, rejection))
                db.execute("INSERT INTO rejection_reason_counts(reason,value) VALUES(?,1) ON CONFLICT(reason) DO UPDATE SET value=value+1", (rejection,))
                continue
            warnings = sum(1 for f in schema["fields"] if not f.get("required") and values.get(f["name"]) is None and errors.get(f["name"]) == "invalid")
            if warnings:
                add_count(db, "field_warnings", warnings)
            phone = str(values["phone"])
            digest = protector.phone_digest(phone)
            reference_field = next((f["name"] for f in schema["fields"] if f.get("reference")), None)
            external_ref = str(values.get(reference_field) or "")
            existing = db.execute("SELECT lead_id,attributes_cipher FROM leads WHERE workflow_id=? AND phone_hmac=?", (workflow_id, digest)).fetchone()
            if existing:
                attrs = json.loads(protector.decrypt(existing["attributes_cipher"]))
                for name, value in values.items():
                    if value is not None:
                        attrs[name] = value
                add_count(db, "duplicate_lead_rows_merged")
                db.execute("UPDATE leads SET attributes_cipher=?,phone_cipher=?,external_ref=?,updated_at=CURRENT_TIMESTAMP WHERE lead_id=?", (protector.encrypt(json.dumps(attrs, ensure_ascii=False)), protector.encrypt(phone), str(attrs.get(reference_field) or external_ref), existing["lead_id"]))
            else:
                # Defaults are deliberately applied only after the row has been merged/created.
                for field in schema["fields"]:
                    if values.get(field["name"]) is None and "default" in field:
                        values[field["name"]] = field["default"]
                db.execute("INSERT INTO leads(workflow_id,phone_hmac,phone_cipher,external_ref,batch_id,attributes_cipher) VALUES(?,?,?,?,?,?)", (workflow_id, digest, protector.encrypt(phone), external_ref, batch_id, protector.encrypt(json.dumps(values, ensure_ascii=False))))
        _mark_processed(db, key, "lead", path, workflow_id)


def _disposition_catalog(path: Path) -> dict[str, dict[str, bool]]:
    result: dict[str, dict[str, bool]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            result.setdefault(row["workflow_id"], {})[row["code"]] = {
                "is_terminal": row["is_terminal"].strip().lower() == "true",
                "is_success": row["is_success"].strip().lower() == "true",
            }
    return result


def _link_event(db: sqlite3.Connection, event: sqlite3.Row, lead_id: int) -> None:
    db.execute("UPDATE events SET state='linked',lead_id=?,ignore_reason=NULL WHERE event_id=?", (lead_id, event["event_id"]))
    db.execute("INSERT OR IGNORE INTO interaction_ledger(event_id,lead_id,workflow_id,call_id,event_type,occurred_at,payload_json) VALUES(?,?,?,?,?,?,?)", (event["event_id"], lead_id, event["workflow_id"], event["call_id"], event["event_type"], event["occurred_at"], event["payload_json"]))


def resolve_pending_events(db: sqlite3.Connection, protector: PIIProtector, catalog: dict | None = None) -> None:
    pending = db.execute("SELECT * FROM events WHERE state='pending' ORDER BY rowid").fetchall()
    changed = True
    while changed:
        changed = False
        for event in pending:
            if event["state"] != "pending":
                continue
            lead = None
            if event["event_type"] == "disposition.override":
                lead = db.execute("SELECT lead_id FROM interaction_ledger WHERE workflow_id=? AND call_id=? ORDER BY ledger_id LIMIT 1", (event["workflow_id"], event["call_id"])).fetchone()
                if lead:
                    lead_id = int(lead[0])
                else:
                    continue
            elif event["phone_hmac"]:
                lead = db.execute("SELECT lead_id FROM leads WHERE workflow_id=? AND phone_hmac=?", (event["workflow_id"], event["phone_hmac"])).fetchone()
                if not lead:
                    continue
                lead_id = int(lead[0])
            else:
                continue
            payload = json.loads(event["payload_json"])
            if event["event_type"].startswith("disposition."):
                code = payload.get("disposition_code")
                if catalog is not None and code not in catalog.get(event["workflow_id"], {}):
                    db.execute("UPDATE events SET state='ignored',ignore_reason='unknown_disposition' WHERE event_id=?", (event["event_id"],))
                    add_count(db, "unknown_disposition_events")
                    changed = True
                    continue
            _link_event(db, event, lead_id)
            changed = True
        if changed:
            pending = db.execute("SELECT * FROM events WHERE state='pending' ORDER BY rowid").fetchall()


def ingest_event_file(db: sqlite3.Connection, path: Path, protector: PIIProtector, catalog: dict) -> None:
    key = _file_key("event", path, None)
    if _already_processed(db, key):
        return
    with path.open("r", encoding="utf-8-sig") as stream:
        for line in stream:
            if not line.strip():
                continue
            add_count(db, "events_total")
            try:
                event = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                add_count(db, "malformed_events")
                continue
            event_id = event.get("event_id") if isinstance(event, dict) else None
            if not event_id:
                add_count(db, "malformed_events")
                continue
            if db.execute("SELECT 1 FROM events WHERE event_id=?", (str(event_id),)).fetchone():
                add_count(db, "duplicate_events_dropped")
                continue
            workflow = str(event.get("workflow_id") or "")
            event_type = str(event.get("event_type") or "")
            occurred = normalise_timestamp(str(event.get("occurred_at") or ""))
            if not workflow or not event_type or occurred is None:
                add_count(db, "malformed_events")
                continue
            phone = normalise_phone(str(event.get("phone") or ""))
            phone_hmac = protector.phone_digest(phone) if phone else None
            call_id = str(event.get("call_id") or "") or None
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            db.execute("INSERT INTO events(event_id,workflow_id,call_id,event_type,occurred_at,phone_hmac,payload_json,state,source_file) VALUES(?,?,?,?,?,?,?,?,?)", (str(event_id), workflow, call_id, event_type, occurred.isoformat(), phone_hmac, json.dumps(payload, ensure_ascii=False), "pending", path.name))
    _mark_processed(db, key, "event", path, None)
    resolve_pending_events(db, protector, catalog)


def ingest_drop(db: sqlite3.Connection, drop: Path, schemas: dict, dispositions_path: Path, protector: PIIProtector) -> None:
    catalog = _disposition_catalog(dispositions_path)
    leads_root = drop / "leads"
    if leads_root.exists():
        for workflow_dir in sorted(p for p in leads_root.iterdir() if p.is_dir()):
            workflow = workflow_dir.name
            if workflow not in schemas:
                continue
            for path in sorted(workflow_dir.glob("*.csv"), key=lambda p: p.name):
                ingest_lead_file(db, path, workflow, schemas[workflow], protector)
    events_root = drop / "events"
    if events_root.exists():
        for path in sorted(events_root.glob("*.jsonl"), key=lambda p: p.name):
            ingest_event_file(db, path, protector, catalog)
    resolve_pending_events(db, protector, catalog)
