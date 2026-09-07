#!/usr/bin/env python3
"""
CLI entrypoint.

  python run.py run [--specs specs.md] [--max-cycles N]
      Start (or resume) the loop. Runs until STOP, monthly budget exhausted,
      or --max-cycles is hit (omit --max-cycles to run indefinitely).

  python run.py status [--specs specs.md]
      Print budget summary, killswitch state, backlog size, directions
      pending, and recent git log -- no LLM calls, no cost.

  python run.py pause / resume / stop
      Control the killswitch.

  python run.py test-eval [--specs specs.md]
      Run just eval_command once and print the parsed metrics + gate check.
      Use this to confirm your eval script's output contract before
      starting a real run.

  python run.py locked-test [--specs specs.md]
      Manually run locked_test_command. NEVER called automatically by the
      loop -- this is the one number you look at yourself at the end of
      the month to judge whether anything real was learned.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).parent.resolve()

load_dotenv(PROJECT_DIR / ".env")

from engine.config import load_specs  # noqa: E402
from engine.killswitch import KillSwitch  # noqa: E402
from engine.budget import BudgetTracker  # noqa: E402
from engine.backlog import Backlog  # noqa: E402
from engine.directions_queue import DirectionsQueue  # noqa: E402
from engine.git_manager import GitManager  # noqa: E402
from engine import metrics as metrics_mod  # noqa: E402


def cmd_run(args):
    from engine.orchestrator import Orchestrator
    specs = load_specs(PROJECT_DIR / args.specs)
    orch = Orchestrator(specs, PROJECT_DIR)
    orch.killswitch.clear_stop()
    orch.run_forever(max_cycles=args.max_cycles)


def cmd_status(args):
    specs = load_specs(PROJECT_DIR / args.specs)
    state_dir = PROJECT_DIR / "state"
    budget = BudgetTracker(state_dir / "budget_state.json", specs.monthly_token_cap, specs.daily_cap_pct)
    ks = KillSwitch(state_dir)
    backlog = Backlog(state_dir / "backlog.json")
    directions = DirectionsQueue(PROJECT_DIR / "directions.md")
    git = GitManager(specs.target_dir)

    print("=== Budget ===")
    for k, v in budget.summary().items():
        print(f"  {k}: {v}")
    print("\n=== Killswitch ===")
    print(f"  stopped: {ks.is_stopped()}")
    print(f"  paused:  {ks.is_paused()}")
    print("\n=== Backlog ===")
    print(f"  {len(backlog.peek_all())} items pending")
    print("\n=== Directions ===")
    print(f"  pending: {directions.has_pending()}")
    print("\n=== Recent commits (target repo) ===")
    for line in git.log_recent(10):
        print(f"  {line}")


def cmd_pause(args):
    KillSwitch(PROJECT_DIR / "state").pause()
    print("Paused. Run 'python run.py resume' to continue.")


def cmd_resume(args):
    KillSwitch(PROJECT_DIR / "state").resume()
    print("Resumed.")


def cmd_stop(args):
    KillSwitch(PROJECT_DIR / "state").stop()
    print("Stop flag set. The loop will halt cleanly after its current cycle (or immediately if idle).")


def cmd_test_eval(args):
    specs = load_specs(PROJECT_DIR / args.specs)
    try:
        result = metrics_mod.run_eval_command(specs.eval_command, specs.target_dir)
    except metrics_mod.EvalError as e:
        print(f"eval_command FAILED: {e}", file=sys.stderr)
        sys.exit(1)
    print("Parsed metrics:", result.metrics)
    failures = metrics_mod.check_hard_gates(result.metrics, specs.hard_gates)
    if failures:
        print("Hard gate check: FAIL")
        for f in failures:
            print(f"  - {f}")
    else:
        print("Hard gate check: PASS")


def cmd_locked_test(args):
    specs = load_specs(PROJECT_DIR / args.specs)
    if not specs.locked_test_command:
        print("No locked_test_command set in specs.md.", file=sys.stderr)
        sys.exit(1)
    print("Running locked test window manually. This is NEVER run automatically by the loop.")
    result = metrics_mod.run_eval_command(specs.locked_test_command, specs.target_dir)
    print("Locked test metrics:", result.metrics)


def main():
    parser = argparse.ArgumentParser(description="Autonomous codebase-improvement engine")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="start/resume the loop")
    p_run.add_argument("--specs", default="specs.md")
    p_run.add_argument("--max-cycles", type=int, default=None)
    p_run.set_defaults(func=cmd_run)

    p_status = sub.add_parser("status", help="show budget/killswitch/backlog status")
    p_status.add_argument("--specs", default="specs.md")
    p_status.set_defaults(func=cmd_status)

    sub.add_parser("pause", help="pause the loop").set_defaults(func=cmd_pause)
    sub.add_parser("resume", help="resume the loop").set_defaults(func=cmd_resume)
    sub.add_parser("stop", help="stop the loop cleanly").set_defaults(func=cmd_stop)

    p_test = sub.add_parser("test-eval", help="run eval_command once, print parsed metrics")
    p_test.add_argument("--specs", default="specs.md")
    p_test.set_defaults(func=cmd_test_eval)

    p_locked = sub.add_parser("locked-test", help="manually run locked_test_command")
    p_locked.add_argument("--specs", default="specs.md")
    p_locked.set_defaults(func=cmd_locked_test)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
