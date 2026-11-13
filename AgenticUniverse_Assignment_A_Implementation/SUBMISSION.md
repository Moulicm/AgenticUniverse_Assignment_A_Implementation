# Submission

## Candidate
- Name:Chandramauli BJ
- Assignment chosen: A
- Time spent (honest estimate):3 Hours
## How to run
From a clean clone, using Python 3.11+:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r solution/requirements.txt
python assignment-a-data/tools/generate_data.py --seed 42 --scale small --out data
python solution/main.py ingest data/drop_1
python solution/main.py ingest data/drop_2
python solution/main.py report --out reports
python -m pytest solution/tests -q
```

## Design
The implementation uses SQLite with four core data areas: `leads`, `events`, `interaction_ledger`, and `processed_files`. Leads are unique by workflow and HMAC digest of the canonical phone. Lead attributes and canonical phone values are encrypted using Fernet. The event staging table stores every valid event ID and its resolution state. Only accepted, linked events are copied into the append-only interaction ledger.

Pending events are retried after each drop. This is necessary because events may arrive before their leads, and overrides contain no phone number and must be resolved through another event for the same call. Reports are derived from the ledger rather than maintained as mutable counters.

## Decisions & assumptions

| Decision | Why | Alternative considered |
|---|---|---|
| Use SQLite | It is explicitly permitted and keeps local setup simple | PostgreSQL |
| Encrypt the full lead attributes document | Prevents accidental plaintext persistence of any schema field marked PII | Encrypt individual columns |
| Use HMAC-SHA256 for phone lookup | Supports deterministic matching without storing plaintext phone values | Hash without a secret (more vulnerable to enumeration) |
| Keep unresolved events in a staging table | Allows later drops to resolve earlier orphans without losing event IDs | Drop orphan events permanently |
| Treat source files as immutable ingestion units | Makes re-ingestion deterministic using file name and content hash | Reconcile in-place file edits |

## Failure modes considered
- Invalid CSV values are rejected or converted to null according to required/optional field rules.
- Blank lead rows are skipped and do not affect row counts.
- Malformed JSONL lines are counted and skipped.
- Duplicate event IDs are discarded across files and drops.
- Orphan events remain pending and can resolve after later lead ingestion.
- SQLite transactions protect each drop from partial commits on an exception.
- Losing the local encryption key makes PII unreadable; the key must be backed up securely and never committed.

## Testing
The included pytest suite covers phone canonicalisation, day-first dates, impossible dates, decimal currency parsing, naive IST timestamps, orphan resolution, idempotent re-ingestion, report generation, and encrypted PII storage. Run the full provided generator with a fresh seed and inspect all five outputs before submission.

## Results
[Run the provided generator and record your actual seed, counts, and timings here. Do not claim a full dataset run until you have completed it locally.]

## If I had another day
1. Add golden-file tests against the complete generated small dataset and additional seeds.
2. Add a measured large-scale run and optimise SQLite bulk writes and report aggregation if needed.
3. Add key rotation and database backup/restore procedures.
