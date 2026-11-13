# Assignment A — Interaction Ledger & Reporting Pipeline

Python 3.11+ implementation using SQLite. The original assignment files and generated datasets remain outside this folder.

## Setup (from the repository root)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r solution/requirements.txt
```

On macOS/Linux, activate with `source .venv/bin/activate`.

## Generate data and run

```powershell
python assignment-a-data/tools/generate_data.py --seed 42 --scale small --out data
python solution/main.py ingest data/drop_1
python solution/main.py ingest data/drop_2
python solution/main.py report --out reports
```

The command accepts `--db`, `--schemas`, and `--dispositions` before the subcommand if you want custom locations. For example:

```powershell
python solution/main.py --db solution/ledger.sqlite3 ingest data/drop_1
```

The database is created at `solution/interaction_ledger.sqlite3`. A local Fernet key is created at `solution/.pii.key` on first run. Back up that key securely if you need to read the database later; do not commit it. Alternatively, set `LEDGER_PII_KEY` to a stable secret before running. Keep the same key across all ingestion and reporting runs.

## Tests

```powershell
python -m pytest solution/tests -q
```

## Outputs

`report --out reports` creates exactly:

- `batch_summary.csv`
- `daily_overview.csv`
- `lead_report.csv`
- `rejections.csv`
- `data_quality.json`

## Design notes

- Lead identity is `(workflow_id, HMAC-SHA256(canonical_phone))`; raw phone values are encrypted with Fernet.
- All lead attributes are encrypted as a JSON document, so fields marked PII are never persisted in plaintext.
- `events` is the durable staging table for valid event IDs, including unresolved orphans. `interaction_ledger` contains only linked, accepted events and is append-only.
- Pending events are re-evaluated after each drop. This resolves earlier orphan events when later lead batches arrive, and allows phone-less overrides to resolve after another event for the call has been linked.
- `processed_files` plus unique event IDs make exact file re-ingestion safe. Duplicate event deliveries across different files are counted and discarded.
- All report timestamps are normalised to IST before storage.

## Known trade-offs

- The implementation favours correctness and clear state transitions over the large-scale performance stretch goal. SQLite writes and application-side report aggregation may need batching/SQL aggregation for the 140k-lead scale.
- A stable encryption key is essential. Losing it makes encrypted PII unreadable; rotating it requires a planned re-encryption migration.
- Input files are treated as immutable. A changed file with the same name and content hash is a new ingestion unit; do not edit already-ingested source files in place.
