"""
Audit trail for auto-resolved breaks.

Nothing gets auto-closed silently. Every auto-resolution is logged with a timestamp,
the exact rule that fired, and the $ exposure it was cleared at — so an auto-resolve
decision can always be reconstructed and defended later, which is the actual substance
behind "compliance and adherence with existing regulations" / "controls and procedures"
in an Ops context: not a policy document, a traceable log.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

LOG_PATH = Path(__file__).parent.parent / "data" / "audit_log.jsonl"


def record_auto_resolution(break_row, run_timestamp=None):
    entry = {
        "timestamp": run_timestamp or datetime.now(timezone.utc).isoformat(),
        "trade_id": break_row["trade_id"],
        "break_type": break_row["break_type"],
        "exposure_usd": break_row["exposure_usd"],
        "rule_fired": break_row["auto_resolve_rule"],
    }
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def reset_log():
    LOG_PATH.write_text("")


def load_log():
    if not LOG_PATH.exists():
        return []
    with open(LOG_PATH) as f:
        return [json.loads(line) for line in f if line.strip()]
