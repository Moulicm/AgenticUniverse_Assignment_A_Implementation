import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import connect
from ingestion import ingest_drop
from reporting import generate_reports
from security import PIIProtector
from cryptography.fernet import Fernet


def make_repo(tmp_path: Path):
    schemas_dir = tmp_path / "schemas"
    schemas_dir.mkdir()
    (schemas_dir / "motor_renewal.json").write_text(json.dumps({
        "workflow_id": "motor_renewal",
        "fields": [
            {"name": "customer_name", "type": "string", "required": True, "pii": True, "aliases": ["name"]},
            {"name": "phone", "type": "phone", "required": True, "pii": True, "aliases": ["mobile"]},
            {"name": "policy_number", "type": "string", "required": True, "reference": True, "aliases": ["policy"]},
            {"name": "preferred_language", "type": "enum", "required": False, "values": ["en", "hi"], "default": "en"}
        ]
    }))
    dispositions = schemas_dir / "dispositions.csv"
    dispositions.write_text("workflow_id,code,label,is_terminal,is_success\nmotor_renewal,renewed,Renewed,true,true\nmotor_renewal,callback_requested,Callback,false,false\n")
    return schemas_dir, dispositions


def write_drop(root: Path, batch: str, leads: str | None, events: list[dict] | None):
    (root / "leads" / "motor_renewal").mkdir(parents=True, exist_ok=True)
    (root / "events").mkdir(parents=True, exist_ok=True)
    if leads is not None:
        (root / "leads" / "motor_renewal" / f"{batch}.csv").write_text(leads)
    if events is not None:
        with (root / "events" / f"{batch}.jsonl").open("w") as f:
            for event in events:
                f.write(json.dumps(event) + "\n")


def test_orphan_resolves_later_and_rerun_is_idempotent(tmp_path):
    schemas_dir, dispositions = make_repo(tmp_path)
    db = connect(tmp_path / "ledger.sqlite3")
    protector = PIIProtector(Fernet.generate_key())
    schemas = {"motor_renewal": json.loads((schemas_dir / "motor_renewal.json").read_text())}
    drop1 = tmp_path / "drop_1"
    write_drop(drop1, "events_0001", None, [{"event_id":"e1","event_type":"call.initiated","workflow_id":"motor_renewal","call_id":"c1","occurred_at":"2026-10-03T10:00:00Z","phone":"7718750036","payload":{}}])
    with db:
        ingest_drop(db, drop1, schemas, dispositions, protector)
    assert db.execute("SELECT COUNT(*) FROM events WHERE state='pending'").fetchone()[0] == 1
    drop2 = tmp_path / "drop_2"
    write_drop(drop2, "batch_003", "customer_name,mobile,policy\nAsha,7718750036,P-1\n", None)
    with db:
        ingest_drop(db, drop2, schemas, dispositions, protector)
    assert db.execute("SELECT COUNT(*) FROM interaction_ledger").fetchone()[0] == 1
    before = db.execute("SELECT value FROM counters WHERE name='events_total'").fetchone()[0]
    with db:
        ingest_drop(db, drop1, schemas, dispositions, protector)
    assert db.execute("SELECT value FROM counters WHERE name='events_total'").fetchone()[0] == before
    out = tmp_path / "reports"
    generate_reports(db, out, protector, dispositions)
    assert (out / "batch_summary.csv").exists()
    lead_report = list(csv.DictReader((out / "lead_report.csv").open()))
    assert lead_report[0]["total_calls"] == "1"
    assert lead_report[0]["last_call_at"].endswith("+05:30")
    db.close()


def test_pii_not_stored_as_plaintext(tmp_path):
    schemas_dir, dispositions = make_repo(tmp_path)
    db = connect(tmp_path / "ledger.sqlite3")
    protector = PIIProtector(Fernet.generate_key())
    schemas = {"motor_renewal": json.loads((schemas_dir / "motor_renewal.json").read_text())}
    drop = tmp_path / "drop"
    write_drop(drop, "batch_001", "customer_name,mobile,policy\nAsha,7718750036,P-1\n", [])
    with db:
        ingest_drop(db, drop, schemas, dispositions, protector)
    row = db.execute("SELECT phone_cipher,attributes_cipher FROM leads").fetchone()
    assert "Asha" not in row["attributes_cipher"]
    assert "7718750036" not in row["phone_cipher"]
    db.close()
