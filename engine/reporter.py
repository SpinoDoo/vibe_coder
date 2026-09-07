"""
Writes/append to reports/YYYY-MM-DD.md. One report per day, cycles appended
as they happen, so if the process is killed mid-day you still have a
complete record of everything up to that point -- nothing is buffered and
lost.
"""
from __future__ import annotations

import subprocess
import shlex
from datetime import date, datetime, timezone
from pathlib import Path


class Reporter:
    def __init__(self, reports_dir: Path):
        self.reports_dir = Path(reports_dir)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def _today_path(self) -> Path:
        return self.reports_dir / f"{date.today().isoformat()}.md"

    def ensure_today_header(self, budget_summary: dict):
        path = self._today_path()
        if path.exists():
            return
        header = f"""# Report — {date.today().isoformat()}

Budget at start of day: {budget_summary['used_today']} / {budget_summary['daily_cap_today']} tokens today,
{budget_summary['remaining_total']} / {budget_summary['monthly_cap']} remaining this month.

---

"""
        path.write_text(header)

    def log_cycle(
        self,
        cycle_id: str,
        source: str,
        task: str,
        outcome: str,
        commit_sha: str | None,
        metrics_before: dict | None,
        metrics_after: dict | None,
        reasoning: str,
        tokens_spent: int,
        overfit_warning: str | None = None,
    ):
        path = self._today_path()
        ts = datetime.now(timezone.utc).strftime("%H:%M UTC")
        lines = [
            f"## Cycle {cycle_id} — {ts}",
            f"- **Source:** {source}",
            f"- **Task:** {task}",
            f"- **Outcome:** {outcome}",
        ]
        if commit_sha:
            lines.append(f"- **Commit:** `{commit_sha[:10]}`")
        if metrics_before is not None or metrics_after is not None:
            lines.append(f"- **Metrics before:** `{metrics_before}`")
            lines.append(f"- **Metrics after:** `{metrics_after}`")
        if reasoning:
            lines.append(f"- **Reasoning:** {reasoning}")
        if overfit_warning:
            lines.append(f"- ⚠️ **Overfitting warning:** {overfit_warning}")
        lines.append(f"- **Tokens spent this cycle:** {tokens_spent}")
        lines.append("")
        with path.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")

    def log_note(self, text: str):
        path = self._today_path()
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"> {text}\n\n")

    def run_visualization(self, specs, target_dir: Path):
        """If specs.visualization_command is set, run it and note the output
        location in the report. The command itself is responsible for saving
        image files (e.g. into reports/); the engine doesn't know what a
        forex equity curve or any other chart looks like -- that's domain
        logic, same as everything else that lives behind specs.md."""
        if not specs.visualization_command:
            return
        try:
            result = subprocess.run(
                shlex.split(specs.visualization_command),
                cwd=target_dir,
                capture_output=True,
                text=True,
                timeout=600,
            )
            if result.returncode == 0:
                self.log_note(f"Visualization command ran successfully: `{specs.visualization_command}`")
            else:
                self.log_note(
                    f"Visualization command failed (exit {result.returncode}): {result.stderr[-500:]}"
                )
        except Exception as e:  # noqa: BLE001
            self.log_note(f"Visualization command errored: {e}")

    def finalize_day(self, budget_summary: dict):
        path = self._today_path()
        footer = f"""
---

## Day summary
- Tokens used today: {budget_summary['used_today']} / {budget_summary['daily_cap_today']}
- Tokens remaining this month: {budget_summary['remaining_total']} / {budget_summary['monthly_cap']}
"""
        with path.open("a", encoding="utf-8") as fh:
            fh.write(footer)
