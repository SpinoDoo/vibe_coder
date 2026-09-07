"""
Thin wrapper around the Anthropic API. Two jobs only:
  1. propose_backlog_items()  -- read the codebase + specs, suggest candidate
     improvements when the backlog and directions queue are both empty.
  2. generate_change()        -- given one task (a direction or backlog item),
     produce a concrete set of file edits as structured JSON.

The engine applies edits itself (engine/apply_edits.py) -- the LLM never
touches the filesystem directly, so every change is inspectable before and
after, and always goes through the git branch + eval gate in orchestrator.py.

Requires ANTHROPIC_API_KEY in the environment (see .env.example).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from anthropic import Anthropic

DEFAULT_MODEL = os.environ.get("ENGINE_MODEL", "claude-sonnet-5")

EDIT_SCHEMA_INSTRUCTIONS = """
Respond with ONLY a single JSON object, no prose, no markdown fences. Schema:

{
  "commit_message": "short imperative summary of the change",
  "reasoning": "1-3 sentences on why this change should help, for the daily report",
  "files": [
    {"path": "relative/path/from/target_dir.py", "action": "replace", "content": "<full new file content>"},
    {"path": "relative/path/new_file.py", "action": "create", "content": "<full file content>"},
    {"path": "relative/path/old_file.py", "action": "delete"}
  ]
}

Rules:
- "path" is always relative to the target codebase root, never absolute, never using "..".
- "action" is one of "replace" (file must already exist), "create" (must not exist), "delete".
- For "replace"/"create", "content" is the COMPLETE new file content, not a diff/patch.
- Keep changes focused: prefer fewer files touched over a sprawling rewrite.
- Never touch files under the forbidden paths listed in the prompt.
- Never add new third-party dependencies unless explicitly told the action is allowed.
"""


class LLMAgent:
    def __init__(self, model: str = DEFAULT_MODEL, max_tokens: int = 8000):
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and fill it in."
            )
        self.client = Anthropic(api_key=api_key)
        self.model = model
        self.max_tokens = max_tokens

    def _list_target_files(self, target_dir: Path, forbidden_paths: list[str], max_files: int = 200) -> list[str]:
        files = []
        for p in sorted(target_dir.rglob("*")):
            if p.is_dir() or ".git" in p.parts:
                continue
            rel = str(p.relative_to(target_dir))
            if any(rel.startswith(fp.rstrip("/")) for fp in forbidden_paths):
                continue
            files.append(rel)
            if len(files) >= max_files:
                break
        return files

    def propose_backlog_items(self, specs, n: int = 5) -> list[dict]:
        file_list = self._list_target_files(specs.target_dir, specs.forbidden_paths)
        prompt = f"""You maintain a backlog of improvement ideas for a codebase.

Domain notes:
{specs.domain_notes}

Primary metric: {specs.metrics_primary}
Hard gates (never violate): {json.dumps(specs.hard_gates)}
Forbidden paths (do not propose touching these): {specs.forbidden_paths}
Forbidden actions: {specs.forbidden_actions}

Files in the target codebase (relative paths):
{json.dumps(file_list, indent=2)}

Propose up to {n} concrete, individually-actionable improvement ideas.
Respond with ONLY a JSON array, no prose:
[{{"description": "...", "rationale": "..."}}, ...]
"""
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        items = _extract_json(text)
        usage = resp.usage.input_tokens + resp.usage.output_tokens
        return items or [], usage

    def generate_change(self, specs, task_description: str, recent_metrics: dict | None) -> tuple[dict, int]:
        file_list = self._list_target_files(specs.target_dir, specs.forbidden_paths)
        file_contents = {}
        for rel in file_list:
            fp = specs.target_dir / rel
            try:
                if fp.stat().st_size < 20_000:  # keep prompt bounded
                    file_contents[rel] = fp.read_text(encoding="utf-8", errors="replace")
            except (UnicodeDecodeError, OSError):
                continue

        prompt = f"""You are making ONE focused improvement to a codebase.

Task: {task_description}

Domain notes:
{specs.domain_notes}

Primary metric: {specs.metrics_primary}
Recent metrics: {json.dumps(recent_metrics or {})}
Hard gates (never violate): {json.dumps(specs.hard_gates)}
Forbidden paths (never touch): {specs.forbidden_paths}
Forbidden actions (never do): {specs.forbidden_actions}
Max files you may change this cycle: {specs.max_files_changed_per_cycle}

Current file contents (relative path -> content):
{json.dumps(file_contents, indent=2)[:60000]}

{EDIT_SCHEMA_INSTRUCTIONS}
"""
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        change = _extract_json(text)
        usage = resp.usage.input_tokens + resp.usage.output_tokens
        if change is None:
            raise ValueError(f"LLM did not return valid JSON:\n{text[:2000]}")
        return change, usage


def _extract_json(text: str):
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        start_arr = text.find("[")
        candidates = [i for i in (start, start_arr) if i != -1]
        if not candidates:
            return None
        start = min(candidates)
        try:
            return json.loads(text[start:])
        except json.JSONDecodeError:
            return None
