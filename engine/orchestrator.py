"""
Main loop. See README.md for the full cycle description. Short version:

  check killswitch -> check directions -> else backlog (refill via LLM if
  empty) -> branch -> generate change -> apply -> run eval -> hard gates ->
  compare to baseline -> commit+merge or revert -> log -> check validation
  periodically -> check overfitting -> deduct budget -> repeat or stop.

The locked_test_command is NEVER called from here. It only runs via
`python run.py locked-test`, invoked by hand.
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path

from . import metrics as metrics_mod
from .apply_edits import apply_change, EditRejected
from .backlog import Backlog
from .budget import BudgetTracker
from .config import Specs
from .directions_queue import DirectionsQueue
from .git_manager import GitManager
from .history import MetricsHistory
from .killswitch import KillSwitch
from .llm_agent import LLMAgent
from .reporter import Reporter


class Orchestrator:
    def __init__(self, specs: Specs, project_dir: Path):
        self.specs = specs
        self.project_dir = Path(project_dir)
        self.state_dir = self.project_dir / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self.budget = BudgetTracker(
            self.state_dir / "budget_state.json", specs.monthly_token_cap, specs.daily_cap_pct
        )
        self.git = GitManager(specs.target_dir)
        self.directions = DirectionsQueue(self.project_dir / "directions.md")
        self.backlog = Backlog(self.state_dir / "backlog.json")
        self.history = MetricsHistory(self.state_dir / "metrics_history.json")
        self.killswitch = KillSwitch(self.state_dir)
        self.reporter = Reporter(self.project_dir / "reports")
        self.llm = LLMAgent()
        self.cycle_count = 0

    def run_forever(self, max_cycles: int | None = None):
        while True:
            if self.killswitch.is_stopped():
                self.reporter.log_note("STOP file present. Halting cleanly.")
                break
            if self.killswitch.is_paused():
                time.sleep(30)
                continue
            if self.budget.is_month_exhausted():
                self.reporter.log_note("Monthly token budget exhausted. Halting.")
                break
            if self.budget.is_day_exhausted():
                self.reporter.finalize_day(self.budget.summary())
                time.sleep(60)  # re-checked; new day rolls over on next BudgetTracker load
                self.budget = BudgetTracker(
                    self.state_dir / "budget_state.json",
                    self.specs.monthly_token_cap,
                    self.specs.daily_cap_pct,
                )
                continue

            self.reporter.ensure_today_header(self.budget.summary())
            self.run_one_cycle()

            if max_cycles is not None and self.cycle_count >= max_cycles:
                break

        self.reporter.finalize_day(self.budget.summary())

    def run_one_cycle(self):
        # Incremented here (not by the caller) so cycle counting -- and
        # anything paced off it, like periodic validation below -- is
        # correct regardless of whether this is called via run_forever()
        # or directly (e.g. in tests / a single manual cycle).
        self.cycle_count += 1
        cycle_id = uuid.uuid4().hex[:8]

        # 1. Determine task source: directions take priority over backlog.
        direction = self.directions.claim_next()
        if direction:
            source, task = "direction", direction
        else:
            if self.backlog.is_empty():
                self._refill_backlog()
            item = self.backlog.pop_next()
            if item is None:
                self.reporter.log_note("No directions and no backlog items available. Idling this cycle.")
                return
            source, task = "backlog", item["description"]

        # 2. Baseline metrics before the change.
        try:
            before = metrics_mod.run_eval_command(self.specs.eval_command, self.specs.target_dir)
        except metrics_mod.EvalError as e:
            self.reporter.log_cycle(cycle_id, source, task, f"ABORTED: baseline eval failed: {e}",
                                     None, None, None, "", 0)
            return

        recent_metrics = before.metrics

        # 3. Branch, generate + apply change.
        branch = self.git.create_cycle_branch(cycle_id)
        try:
            change, tokens_used = self.llm.generate_change(self.specs, task, recent_metrics)
            self.budget.record_spend(tokens_used)
            touched = apply_change(self.specs, change)
        except (EditRejected, ValueError) as e:
            self.git.abandon_branch(branch)
            self.reporter.log_cycle(cycle_id, source, task, f"REJECTED: {e}", None,
                                     before.metrics, None, "", tokens_used if 'tokens_used' in dir() else 0)
            if source == "direction":
                self.directions.mark_done(task, f"rejected: {e}")
            return

        # 4. Run eval on the change; check hard gates + regression vs baseline.
        try:
            after = metrics_mod.run_eval_command(self.specs.eval_command, self.specs.target_dir)
        except metrics_mod.EvalError as e:
            self.git.abandon_branch(branch)
            self.reporter.log_cycle(cycle_id, source, task, f"REVERTED: eval crashed after change: {e}",
                                     None, before.metrics, None, change.get("reasoning", ""), tokens_used)
            if source == "direction":
                self.directions.mark_done(task, "reverted: eval crashed")
            return

        gate_failures = metrics_mod.check_hard_gates(after.metrics, self.specs.hard_gates)
        improved, compare_note = metrics_mod.compare_for_regression(
            before.metrics, after.metrics, self.specs.metrics_primary
        )

        if gate_failures:
            self.git.abandon_branch(branch)
            outcome = f"REVERTED: hard gate violations: {'; '.join(gate_failures)}"
            self.reporter.log_cycle(cycle_id, source, task, outcome, None,
                                     before.metrics, after.metrics, change.get("reasoning", ""), tokens_used)
            if source == "direction":
                self.directions.mark_done(task, "reverted: hard gate violation")
            return

        if not improved:
            self.git.abandon_branch(branch)
            outcome = f"REVERTED: regressed primary metric ({compare_note})"
            self.reporter.log_cycle(cycle_id, source, task, outcome, None,
                                     before.metrics, after.metrics, change.get("reasoning", ""), tokens_used)
            if source == "direction":
                self.directions.mark_done(task, "reverted: regressed primary metric")
            return

        # 5. Accepted: commit on branch, merge to base.
        commit_msg = change.get("commit_message", f"engine: {task}")[:200]
        sha = self.git.commit_all(f"{commit_msg}\n\ncycle={cycle_id} files={touched}")
        self.git.merge_to_base(branch, f"Merge cycle {cycle_id}: {commit_msg}")
        self.history.record(cycle_id, "train", after.metrics)

        overfit_warning = None

        # 6. Periodic validation-window check (every Nth cycle: 1-indexed,
        # so N=5 validates on cycles 5, 10, 15... not on cycle 0).
        if self.specs.validation_command and self.cycle_count % self.specs.validation_every_n_cycles == 0:
            try:
                val_result = metrics_mod.run_eval_command(self.specs.validation_command, self.specs.target_dir)
                self.history.record(cycle_id, "validation", val_result.metrics)
                is_overfit, note = self.history.check_overfitting(self.specs.metrics_primary)
                if is_overfit:
                    overfit_warning = note
            except metrics_mod.EvalError as e:
                self.reporter.log_note(f"Validation command failed this cycle: {e}")

        outcome = f"ACCEPTED: {compare_note}"
        self.reporter.log_cycle(
            cycle_id, source, task, outcome, sha, before.metrics, after.metrics,
            change.get("reasoning", ""), tokens_used, overfit_warning,
        )
        if source == "direction":
            self.directions.mark_done(task, "accepted")

        self.reporter.run_visualization(self.specs, self.specs.target_dir)

    def _refill_backlog(self):
        try:
            items, tokens_used = self.llm.propose_backlog_items(self.specs)
            self.budget.record_spend(tokens_used)
            for item in items:
                if isinstance(item, dict) and "description" in item:
                    self.backlog.add(item["description"], item.get("rationale", ""))
            self.reporter.log_note(f"Refilled backlog with {len(items)} new candidate items.")
        except Exception as e:  # noqa: BLE001
            self.reporter.log_note(f"Backlog refill failed: {e}")
