"""Module-level best-effort JSONL writer for per-turn dialogue records.

Each record is appended as one JSON line to
``logs/dialogue_YYYYMMDD.log``. Failures are silently ignored so the
dialogue tab never breaks because its log path is unwritable.
"""

from __future__ import annotations


def _append_dialogue_log(record: dict) -> None:
    try:
        import json
        from datetime import datetime
        from pathlib import Path
        ts = record.get("timestamp", datetime.now().isoformat())
        date = datetime.fromisoformat(
            ts.replace("Z", "+00:00")
        ).strftime("%Y%m%d")
        path = Path("logs") / f"dialogue_{date}.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass
