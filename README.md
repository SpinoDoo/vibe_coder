# Autonomous Codebase-Improvement Engine

A generic engine (`engine/`) that repeatedly proposes and applies small
changes to a target codebase, gated by an evaluation command you define,
paced by a token budget, and fully reversible via git. Domain-specific
details (what "improvement" means, what's off-limits, how to grade a
change) live entirely in `specs.md` — the engine itself knows nothing
about forex, ANNs, or anything else specific.

**This is scaffolding, not a finished trading system.** It won't make your
ANN profitable by itself — it will faithfully run whatever loop you
configure, so the configuration (your `eval_command`, your metrics, your
hard gates) is what actually determines whether it does anything useful.

## What it does, in one paragraph

Every cycle: check if you've left a new direction in `directions.md`, and
if not, pull the next item from a self-maintained backlog (refilled by the
LLM when empty). Create a git branch. Ask the LLM to produce a focused set
of file edits for that one task. Apply them. Run your eval command before
and after. If any hard gate is violated, or the primary metric got worse,
revert the branch and log why. Otherwise commit and merge to your base
branch. Periodically also run a separate validation command and check for
train/validation divergence (an overfitting warning). Log everything to a
daily report. Repeat until the daily or monthly token budget runs out, or
you hit the kill switch.

## Setup

```bash
cd forex_engine
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # then edit .env and add your ANTHROPIC_API_KEY
cp specs.example.md specs.md  # then edit specs.md for your actual codebase
```

Put your actual project inside `target/` (or point `target_dir` in
`specs.md` somewhere else — it can be an absolute path or relative to
`specs.md`). If `target/` isn't already a git repo, the engine will `git
init` it automatically on first run.

## Before your first real run: test your eval script's contract

```bash
python run.py test-eval
```

This runs `eval_command` once, parses the JSON it prints to stdout, and
tells you whether it currently passes your hard gates. **Do this before
starting a real run.** The engine calls `eval_command` on every single
cycle, so if its output format is unstable or slow, fix that first — it's
cheap to fix now and expensive to discover after burning budget.

`eval_command` must print exactly one JSON object to stdout, e.g.:

```json
{"sharpe_ratio": 1.32, "max_drawdown": 0.09, "trades": 88, "win_rate": 0.54}
```

Extra log output before/after the JSON is fine — the parser looks for the
last valid `{...}` block. Exit code must be 0.

## Running it

```bash
python run.py run                    # runs until budget exhausted or stopped
python run.py run --max-cycles 5     # do a short bounded test run first
```

**Strongly recommended:** run `--max-cycles 3` or so first and read the
resulting `reports/<date>.md` and `target/`'s git log before letting it run
unattended for a day, let alone a month.

## Controlling it while it runs (from another terminal)

```bash
python run.py status     # budget used/remaining, backlog size, recent commits
python run.py pause       # stop spending, don't exit — resumable
python run.py resume
python run.py stop        # finish current cycle, then exit cleanly
```

Giving it direction: edit `directions.md` any time. Add a line under
`## Open`, starting with `- `. It's picked up at the start of the next
cycle and always takes priority over the self-generated backlog.

## The locked test window

```bash
python run.py locked-test
```

This is the **only** place `locked_test_command` ever runs. It is never
called automatically by the loop — on purpose. Use it yourself, by hand, at
the end of the month, as the real judgment of whether anything the engine
did generalizes — not as a signal the engine itself gets to optimize
against. If the engine could see this number, it would eventually overfit
to it the same way it could overfit to the train window.

## Files

```
run.py                  CLI entrypoint
specs.example.md        copy to specs.md and edit for your project
specs.md                (you create this) — the domain contract
directions.md           (auto-created) — your interrupt channel
.env                     (you create this) — ANTHROPIC_API_KEY
target/                 your actual codebase lives here (or point elsewhere)
reports/                one markdown file per day, appended to as it runs
state/
  budget_state.json     token usage, persisted across runs
  backlog.json           pending self-generated improvement ideas
  metrics_history.json   train/validation history, for overfit detection
  STOP / PAUSE            killswitch files (presence = active)
engine/
  config.py              parses specs.md
  budget.py              monthly cap + daily pacing
  git_manager.py          branch / commit / merge / revert
  directions_queue.py     reads/writes directions.md
  killswitch.py           STOP / PAUSE file checks
  metrics.py              runs eval commands, parses JSON, checks hard gates
  history.py              train/validation history + overfitting check
  backlog.py               self-maintained improvement backlog
  llm_agent.py             calls the Anthropic API to propose/generate changes
  apply_edits.py           safely writes LLM-proposed edits to target_dir
  reporter.py               writes reports/<date>.md
  orchestrator.py            the main loop, ties everything above together
```

## Safety properties this design gives you (and their limits)

- **Every change is a git commit, every failed change is reverted.**
  Nothing is left half-applied. But: this protects code state, not your
  actual trading capital — nothing here should be wired to a live broker.
  `forbidden_paths` in the example specs explicitly blocks a
  `target/live_trading/` directory for this reason; make sure your real
  specs.md does the same for anything broker-connected.
- **Hard gates (e.g. max_drawdown) are checked in code, not left to the
  LLM's judgment.** A change that violates them is reverted regardless of
  what the primary metric did.
- **The locked test window is structurally unreachable by the automated
  loop.** It requires a manual CLI invocation.
- **Budget is a hard ceiling enforced before spend, not a target.** The
  loop's goal is finishing useful cycles; running out of budget mid-month
  is a valid, expected outcome, not a failure.
- **The kill switch is a plain file check, evaluated at the start of every
  cycle** — it works even if the LLM or orchestrator logic misbehaves in
  some other way, because it doesn't depend on that logic to check it.

What this does **not** protect against: a bad `eval_command` (e.g. one with
look-ahead bias, or one that's simply buggy) will happily grade nonsense as
good and the engine will optimize toward it. The eval script is the most
important file in this whole system and it's entirely on you — run
`test-eval` and sanity-check it carefully before trusting it with a month
of budget.
