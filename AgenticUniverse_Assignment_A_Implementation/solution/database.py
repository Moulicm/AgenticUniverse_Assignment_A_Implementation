from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS processed_files (
    file_key TEXT PRIMARY KEY, kind TEXT NOT NULL, file_name TEXT NOT NULL,
    workflow_id TEXT, processed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS leads (
    lead_id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id TEXT NOT NULL,
    phone_hmac TEXT NOT NULL,
    phone_cipher TEXT NOT NULL,
    external_ref TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    attributes_cipher TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(workflow_id, phone_hmac)
);
CREATE INDEX IF NOT EXISTS idx_leads_ref ON leads(workflow_id, external_ref);
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    call_id TEXT,
    event_type TEXT NOT NULL,
    occurred_at TEXT,
    phone_hmac TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    state TEXT NOT NULL CHECK(state IN ('pending','linked','ignored')),
    lead_id INTEGER REFERENCES leads(lead_id),
    ignore_reason TEXT,
    source_file TEXT NOT NULL,
    FOREIGN KEY(lead_id) REFERENCES leads(lead_id)
);
CREATE INDEX IF NOT EXISTS idx_events_call ON events(workflow_id, call_id);
CREATE INDEX IF NOT EXISTS idx_events_phone ON events(workflow_id, phone_hmac);
CREATE INDEX IF NOT EXISTS idx_events_state ON events(state);
CREATE TABLE IF NOT EXISTS interaction_ledger (
    ledger_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE REFERENCES events(event_id),
    lead_id INTEGER NOT NULL REFERENCES leads(lead_id),
    workflow_id TEXT NOT NULL,
    call_id TEXT,
    event_type TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_ledger_call ON interaction_ledger(workflow_id, call_id);
CREATE INDEX IF NOT EXISTS idx_ledger_lead ON interaction_ledger(lead_id);
CREATE TABLE IF NOT EXISTS rejection_rows (
    rejection_id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id TEXT NOT NULL, batch_id TEXT NOT NULL,
    row_number INTEGER NOT NULL, reason TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rejection_reason_counts (
    reason TEXT PRIMARY KEY, value INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS counters (
    name TEXT PRIMARY KEY, value INTEGER NOT NULL DEFAULT 0
);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript(SCHEMA)
    return db


def add_count(db: sqlite3.Connection, name: str, amount: int = 1) -> None:
    db.execute("INSERT INTO counters(name,value) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET value=value+excluded.value", (name, amount))


def count(db: sqlite3.Connection, name: str) -> int:
    row = db.execute("SELECT value FROM counters WHERE name=?", (name,)).fetchone()
    return int(row[0]) if row else 0
