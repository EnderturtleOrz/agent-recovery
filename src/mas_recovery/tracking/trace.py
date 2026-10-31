"""Append-only JSONL trace, separate from mutable LangGraph state."""

import json
from pathlib import Path
from time import perf_counter
from typing import Any


class Trace:
    def __init__(self, path: Path):
        self.path = path
        self.path.touch(exist_ok=False)
        self.sequence = 0
        self.write_seconds = 0.0

    def emit(self, event: str, **data: Any) -> None:
        started = perf_counter()
        self.sequence += 1
        record = {"schema_version": 1, "sequence": self.sequence, "event": event, **data}
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        self.write_seconds += perf_counter() - started
