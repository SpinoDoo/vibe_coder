"""
directions.md is YOUR channel into the loop. Lines under an '## Open' section
that start with '- ' are pending directions. The engine claims one at the
start of a cycle by moving it to '## In Progress', and moves it to
'## Done (date)' once the cycle completes (success or failure both count as
handled -- a failed attempt still gets reported, not silently dropped).
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

OPEN_HEADER = "## Open"
IN_PROGRESS_HEADER = "## In Progress"
DONE_HEADER = "## Done"

TEMPLATE = f"""# Directions

Add lines under "{OPEN_HEADER}" any time, one per line, starting with "- ".
The engine checks this file at the start of every cycle. New entries here
always take priority over whatever the engine would otherwise pick from its
own backlog.

{OPEN_HEADER}

{IN_PROGRESS_HEADER}

{DONE_HEADER}
"""


class DirectionsQueue:
    def __init__(self, path: Path):
        self.path = Path(path)
        if not self.path.exists():
            self.path.write_text(TEMPLATE)

    def _sections(self) -> dict:
        text = self.path.read_text()
        sections = {OPEN_HEADER: [], IN_PROGRESS_HEADER: [], DONE_HEADER: []}
        current = None
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("## "):
                # match by prefix so "## Done (2026-09-02)" still maps to Done
                for header in sections:
                    if stripped.startswith(header):
                        current = header
                        break
                else:
                    current = None
                continue
            if current and stripped.startswith("- "):
                sections[current].append(stripped[2:].strip())
        return sections

    def _write(self, sections: dict):
        lines = ["# Directions", "", "Add lines under \"## Open\" any time, one per line, starting with \"- \".", ""]
        lines += [OPEN_HEADER, ""]
        lines += [f"- {d}" for d in sections[OPEN_HEADER]]
        lines += ["", IN_PROGRESS_HEADER, ""]
        lines += [f"- {d}" for d in sections[IN_PROGRESS_HEADER]]
        lines += ["", f"{DONE_HEADER} ({date.today().isoformat()})", ""]
        lines += [f"- {d}" for d in sections[DONE_HEADER]]
        lines.append("")
        self.path.write_text("\n".join(lines))

    def claim_next(self) -> str | None:
        """Pop the oldest open direction and mark it in-progress. Returns None if empty."""
        sections = self._sections()
        if not sections[OPEN_HEADER]:
            return None
        direction = sections[OPEN_HEADER].pop(0)
        sections[IN_PROGRESS_HEADER].append(direction)
        self._write(sections)
        return direction

    def mark_done(self, direction: str, outcome: str):
        sections = self._sections()
        if direction in sections[IN_PROGRESS_HEADER]:
            sections[IN_PROGRESS_HEADER].remove(direction)
        sections[DONE_HEADER].append(f"{direction} -> {outcome}")
        self._write(sections)

    def has_pending(self) -> bool:
        return bool(self._sections()[OPEN_HEADER])
