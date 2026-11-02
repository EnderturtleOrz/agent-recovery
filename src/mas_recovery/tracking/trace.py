"""JSONL provenance plus a lean in-memory event stream for scoring in both modes."""

import json
from pathlib import Path
from time import perf_counter
from typing import Any


class Trace:
    def __init__(self, path: Path, enabled: bool = True):
        self.path = path
        self.enabled = enabled
        if enabled:
            self.path.touch(exist_ok=False)
        self.sequence = 0
        self.write_seconds = 0.0
        self.events: list[dict] = []
        self.started = perf_counter()

    def emit(self, event: str, **data: Any) -> None:
        started = perf_counter()
        self.sequence += 1
        record = {
            "schema_version": 2,
            "sequence": self.sequence,
            "elapsed_seconds": started - self.started,
            "event": event,
            **data,
        }
        self.events.append(record)
        if self.enabled:
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        self.write_seconds += perf_counter() - started
