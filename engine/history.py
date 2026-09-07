"""
Persists train/validation metric history across cycles and implements the
overfitting circuit breaker: if train performance keeps climbing while
validation performance stalls/drops for N consecutive checks, flag it so the
orchestrator throttles down (prefer simplifying, stop adding complexity)
instead of blindly continuing to optimize the train metric.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class HistoryEntry:
    timestamp: str
    cycle_id: str
    kind: str  # "train" or "validation"
    metrics: dict


class MetricsHistory:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.entries: list[dict] = []
        if self.path.exists():
            self.entries = json.loads(self.path.read_text())

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.entries, indent=2))

    def record(self, cycle_id: str, kind: str, metrics: dict):
        self.entries.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cycle_id": cycle_id,
            "kind": kind,
            "metrics": metrics,
        })
        self.save()

    def recent(self, kind: str, n: int) -> list[dict]:
        matches = [e for e in self.entries if e["kind"] == kind]
        return matches[-n:]

    def check_overfitting(self, primary_metric: str, window: int = 3) -> tuple[bool, str]:
        """
        Compares the trend of the last `window` train checks vs the last
        `window` validation checks. Flags divergence: train rising while
        validation flat/falling.
        """
        train = self.recent("train", window)
        val = self.recent("validation", window)
        if len(train) < window or len(val) < window:
            return False, "not enough history yet to evaluate overfitting trend"

        train_vals = [e["metrics"].get(primary_metric) for e in train]
        val_vals = [e["metrics"].get(primary_metric) for e in val]
        if any(v is None for v in train_vals + val_vals):
            return False, "primary metric missing from some history entries"

        train_trend = train_vals[-1] - train_vals[0]
        val_trend = val_vals[-1] - val_vals[0]

        if train_trend > 0 and val_trend <= 0:
            return True, (
                f"train {primary_metric} rose by {train_trend:.4f} over last {window} checks "
                f"while validation moved by {val_trend:.4f} -- possible overfitting"
            )
        return False, f"train/validation trends consistent (train {train_trend:.4f}, val {val_trend:.4f})"
