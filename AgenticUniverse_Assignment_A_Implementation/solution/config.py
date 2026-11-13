from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = ROOT / "schemas"
DEFAULT_DB = ROOT / "solution" / "interaction_ledger.sqlite3"
KEY_PATH = ROOT / "solution" / ".pii.key"


def load_schemas(schema_dir: Path = SCHEMA_DIR) -> dict[str, dict]:
    schemas: dict[str, dict] = {}
    for path in sorted(schema_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        schemas[data["workflow_id"]] = data
    if not schemas:
        raise FileNotFoundError(f"No workflow schemas found in {schema_dir}")
    return schemas


def get_secret() -> bytes:
    """Load a stable local secret, or create one for first-time use."""
    configured = os.environ.get("LEDGER_PII_KEY")
    if configured:
        return configured.encode("utf-8")
    KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    if KEY_PATH.exists():
        return KEY_PATH.read_bytes()
    from cryptography.fernet import Fernet
    secret = Fernet.generate_key()
    try:
        fd = os.open(KEY_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(secret)
    except FileExistsError:
        secret = KEY_PATH.read_bytes()
    return secret
