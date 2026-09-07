"""
Token/cost budget tracking with daily pacing.

The whole point of this module: the engine's job is never "spend the budget",
it's "stop safely once the budget (or a daily slice of it) runs out."
Spending is a side effect of doing useful cycles, never the goal itself.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import date, datetime
from pathlib import Path


@dataclass
class BudgetState:
    monthly_token_cap: int
    tokens_used_total: int = 0
    day: str = ""  # ISO date of the current tracking day
    tokens_used_today: int = 0
    days_elapsed: int = 0
    history: list = None  # list of {date, tokens_used}

    def __post_init__(self):
        if self.history is None:
            self.history = []


class BudgetTracker:
    def __init__(self, state_path: Path, monthly_token_cap: int, daily_cap_pct: float):
        self.state_path = Path(state_path)
        self.monthly_token_cap = monthly_token_cap
        self.daily_cap_pct = daily_cap_pct
        self.state = self._load_or_init()

    def _load_or_init(self) -> BudgetState:
        today = date.today().isoformat()
        if self.state_path.exists():
            data = json.loads(self.state_path.read_text())
            state = BudgetState(**data)
            if state.day != today:
                state.history.append({"date": state.day, "tokens_used": state.tokens_used_today})
                state.day = today
                state.tokens_used_today = 0
                state.days_elapsed += 1
            # allow monthly cap to be edited in specs.md between runs
            state.monthly_token_cap = self.monthly_token_cap
            return state
        return BudgetState(monthly_token_cap=self.monthly_token_cap, day=today)

    def save(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(asdict(self.state), indent=2))

    @property
    def tokens_remaining_total(self) -> int:
        return max(0, self.monthly_token_cap - self.state.tokens_used_total)

    @property
    def daily_cap_tokens(self) -> int:
        # Daily cap is a percentage of what's LEFT, not of the original total.
        # This naturally tapers spend so a bad early week doesn't starve the rest
        # of the month, and unused days don't force a huge dump at month end.
        return max(1, int(self.tokens_remaining_total * (self.daily_cap_pct / 100.0)))

    def can_spend(self, estimated_tokens: int) -> bool:
        if self.state.tokens_used_total + estimated_tokens > self.monthly_token_cap:
            return False
        if self.state.tokens_used_today + estimated_tokens > self.daily_cap_tokens:
            return False
        return True

    def record_spend(self, tokens: int):
        self.state.tokens_used_total += tokens
        self.state.tokens_used_today += tokens
        self.save()

    def is_month_exhausted(self) -> bool:
        return self.tokens_remaining_total <= 0

    def is_day_exhausted(self) -> bool:
        return self.state.tokens_used_today >= self.daily_cap_tokens

    def summary(self) -> dict:
        return {
            "monthly_cap": self.monthly_token_cap,
            "used_total": self.state.tokens_used_total,
            "remaining_total": self.tokens_remaining_total,
            "used_today": self.state.tokens_used_today,
            "daily_cap_today": self.daily_cap_tokens,
            "days_elapsed": self.state.days_elapsed,
            "day": self.state.day,
        }
