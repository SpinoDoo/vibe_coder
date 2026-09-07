"""
When directions.md has nothing pending, the engine works from a backlog of
candidate improvements it maintains itself (state/backlog.json). Items are
proposed by the LLM (via llm_agent.propose_backlog_items) and consumed one
at a time. Kept as plain JSON so you can hand-edit or clear it yourself too.
"""
from __future__ import annotations

import json
from pathlib import Path


class Backlog:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.items: list[dict] = []
        if self.path.exists():
            self.items = json.loads(self.path.read_text())

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.items, indent=2))

    def add(self, description: str, rationale: str = ""):
        self.items.append({"description": description, "rationale": rationale})
        self.save()

    def pop_next(self) -> dict | None:
        if not self.items:
            return None
        item = self.items.pop(0)
        self.save()
        return item

    def is_empty(self) -> bool:
        return not self.items

    def peek_all(self) -> list[dict]:
        return list(self.items)
