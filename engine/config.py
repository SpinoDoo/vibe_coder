"""
Loads specs.md: a YAML frontmatter block (structured, machine-read rules)
followed by free-text prose (domain notes, read by the LLM each cycle).

This is the ONLY file that bridges "generic engine" and "domain specifics".
Nothing else in engine/ should hardcode anything about forex, ANNs, or any
other specific target codebase.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)

DEFAULTS = {
    "target_dir": "./target",
    "eval_command": None,
    "validation_command": None,
    "validation_every_n_cycles": 5,
    "locked_test_command": None,
    "metrics": {"primary": None, "hard_gates": {}, "track": []},
    "forbidden_paths": [],
    "forbidden_actions": [],
    "budget": {"monthly_token_cap": 1_000_000, "daily_cap_pct": 10},
    "visualization_command": None,
    "max_files_changed_per_cycle": 5,
}


@dataclass
class Specs:
    target_dir: Path
    eval_command: str | None
    validation_command: str | None
    validation_every_n_cycles: int
    locked_test_command: str | None
    metrics_primary: str | None
    hard_gates: dict
    tracked_metrics: list
    forbidden_paths: list
    forbidden_actions: list
    monthly_token_cap: int
    daily_cap_pct: float
    visualization_command: str | None
    max_files_changed_per_cycle: int
    domain_notes: str
    raw: dict = field(default_factory=dict)

    def is_path_forbidden(self, path: str) -> bool:
        norm = path.replace("\\", "/").lstrip("./")
        for forbidden in self.forbidden_paths:
            f = forbidden.replace("\\", "/").lstrip("./").rstrip("/")
            if norm == f or norm.startswith(f + "/"):
                return True
        return False

    def is_action_forbidden(self, action: str) -> bool:
        return action in self.forbidden_actions


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_specs(specs_path: str | Path) -> Specs:
    specs_path = Path(specs_path)
    if not specs_path.exists():
        raise FileNotFoundError(
            f"specs file not found: {specs_path}. Copy specs.example.md to specs.md and edit it."
        )
    text = specs_path.read_text(encoding="utf-8")
    m = FRONTMATTER_RE.match(text)
    if not m:
        raise ValueError(
            "specs.md must start with a '---' YAML frontmatter block followed by '---' and prose notes."
        )
    frontmatter_raw, body = m.group(1), m.group(2)
    parsed = yaml.safe_load(frontmatter_raw) or {}
    merged = _deep_merge(DEFAULTS, parsed)

    if merged["eval_command"] is None:
        raise ValueError("specs.md frontmatter must set 'eval_command'.")

    return Specs(
        target_dir=(specs_path.parent / merged["target_dir"]).resolve(),
        eval_command=merged["eval_command"],
        validation_command=merged.get("validation_command"),
        validation_every_n_cycles=int(merged.get("validation_every_n_cycles", 5)),
        locked_test_command=merged.get("locked_test_command"),
        metrics_primary=merged["metrics"].get("primary"),
        hard_gates=merged["metrics"].get("hard_gates", {}) or {},
        tracked_metrics=merged["metrics"].get("track", []) or [],
        forbidden_paths=merged.get("forbidden_paths", []) or [],
        forbidden_actions=merged.get("forbidden_actions", []) or [],
        monthly_token_cap=int(merged["budget"]["monthly_token_cap"]),
        daily_cap_pct=float(merged["budget"]["daily_cap_pct"]),
        visualization_command=merged.get("visualization_command"),
        max_files_changed_per_cycle=int(merged.get("max_files_changed_per_cycle", 5)),
        domain_notes=body.strip(),
        raw=merged,
    )
