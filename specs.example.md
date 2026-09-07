---
# Where your actual codebase lives, relative to this specs.md file.
target_dir: ./target

# Required. Must print a single JSON object to stdout with your metrics, e.g.:
#   {"sharpe_ratio": 1.32, "max_drawdown": 0.09, "trades": 88, "win_rate": 0.54, "profit_factor": 1.6}
# Runs against your TRAIN/dev window. This is what the engine optimizes against
# every cycle, so keep it reasonably fast (seconds, not tens of minutes) or the
# loop will burn most of its time/budget on evaluation instead of improvement.
eval_command: "python eval/run_backtest.py --window=train"

# Runs less often (every N cycles, see below) against data the train loop
# doesn't get to fit against every cycle. This is your real overfitting check.
validation_command: "python eval/run_backtest.py --window=validation"
validation_every_n_cycles: 5

# NEVER auto-run. Only invoked by hand via `python run.py locked-test`.
# Use this to judge, at the end of the month, whether anything real was learned
# — not to guide any decision the engine itself makes.
locked_test_command: "python eval/run_backtest.py --window=test"

metrics:
  # The single number the engine compares before/after each change to decide
  # accept vs revert. Risk-adjusted, not raw profit -- see domain notes below.
  primary: sharpe_ratio

  # Hard gates: violating ANY of these reverts the change automatically,
  # regardless of what happened to the primary metric.
  hard_gates:
    max_drawdown: 0.15       # reject if max_drawdown > 0.15 (15%)
    min_trades: 30           # reject if trade count is too low to be meaningful

  # Metrics logged in every report even though only `primary` gates decisions.
  track:
    - sharpe_ratio
    - sortino_ratio
    - win_rate
    - profit_factor
    - max_drawdown
    - trades

# Paths the engine will refuse to touch, no matter what the LLM proposes.
forbidden_paths:
  - eval/                # don't let it rewrite the thing that grades it
  - tests/
  - target/live_trading/ # anything that could touch a real broker connection

# Actions the engine will refuse to take, checked before every change.
forbidden_actions:
  - add_dependency
  - modify_test_files
  - network_calls
  - push_to_remote

budget:
  monthly_token_cap: 5000000
  # Daily cap = this % of whatever budget REMAINS (not of the original total),
  # so a slow week doesn't starve the rest of the month and spend naturally
  # tapers rather than dumping everything on the last day.
  daily_cap_pct: 5

# Optional: a script that generates chart images (equity curve, drawdown,
# trade distribution) into reports/. Purely domain logic -- the engine just
# runs it and notes in the report that it ran.
visualization_command: "python eval/make_visualizations.py"

max_files_changed_per_cycle: 5
---

## Domain notes (read by the LLM every cycle)

This is a forex trading ANN. The goal is BETTER RISK-ADJUSTED PERFORMANCE,
not raw profit. Raw profit alone is easy to game by curve-fitting to noise
in the historical training window, and that would look like success right
up until it loses real money live.

Concretely:
- Optimize for sharpe_ratio (or sortino_ratio as a secondary check), never
  raw profit in isolation.
- Be suspicious of any change that improves the train-window metric a lot in
  one cycle -- large single-step jumps are a common overfitting signature.
  Prefer smaller, more defensible changes over big rewrites.
- If validation-window performance stalls or drops while train-window
  performance keeps climbing (the engine tracks and flags this
  automatically), treat that as a signal to SIMPLIFY -- remove recently
  added complexity/parameters -- rather than add more.
- Do not add filters or conditions whose only apparent purpose is to skip
  historically bad periods; that's overfitting to the calendar, not a real
  strategy improvement.
- Trade count matters: a "profitable" strategy that only trades a handful of
  times isn't statistically meaningful. Don't let trade count drop just to
  raise per-trade metrics.
- This system has NOT been connected to live paper trading yet. Do not
  write code that assumes a live broker connection, and do not attempt to
  add one -- that step is deliberately left for a human to build and wire
  up manually, outside this loop.
