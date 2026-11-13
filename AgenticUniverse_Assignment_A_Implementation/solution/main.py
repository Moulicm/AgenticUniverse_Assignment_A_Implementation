from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from config import DEFAULT_DB, SCHEMA_DIR, get_secret, load_schemas
from database import connect
from ingestion import ingest_drop
from reporting import generate_reports
from security import PIIProtector


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Agentic Universe Assignment A interaction ledger")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite database path")
    parser.add_argument("--schemas", type=Path, default=SCHEMA_DIR, help="Workflow schema directory")
    parser.add_argument("--dispositions", type=Path, default=SCHEMA_DIR / "dispositions.csv", help="Disposition catalogue CSV")
    sub = parser.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("ingest", help="Ingest one generated drop directory")
    ingest.add_argument("drop", type=Path)
    report = sub.add_parser("report", help="Generate all five reports")
    report.add_argument("--out", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    schemas = load_schemas(args.schemas)
    protector = PIIProtector(get_secret())
    db = connect(args.db)
    try:
        if args.command == "ingest":
            if not args.drop.is_dir():
                raise FileNotFoundError(f"Drop directory not found: {args.drop}")
            with db:
                ingest_drop(db, args.drop, schemas, args.dispositions, protector)
            print(f"Ingested drop: {args.drop}")
        elif args.command == "report":
            generate_reports(db, args.out, protector, args.dispositions)
            print(f"Reports written to: {args.out}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
