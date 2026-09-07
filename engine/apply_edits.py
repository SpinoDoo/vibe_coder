"""
Applies the JSON edit payload from llm_agent.generate_change() to the target
codebase. This is the only place that writes to target_dir, and it enforces
forbidden_paths / forbidden_actions / max_files_changed_per_cycle again here
(never trust a single layer of checking) before touching disk.
"""
from __future__ import annotations

from pathlib import Path


class EditRejected(RuntimeError):
    pass


def _safe_resolve(target_dir: Path, rel_path: str) -> Path:
    if rel_path.startswith("/") or ".." in Path(rel_path).parts:
        raise EditRejected(f"unsafe path rejected: {rel_path}")
    resolved = (target_dir / rel_path).resolve()
    if target_dir.resolve() not in resolved.parents and resolved != target_dir.resolve():
        raise EditRejected(f"path escapes target_dir: {rel_path}")
    return resolved


def apply_change(specs, change: dict) -> list[str]:
    files = change.get("files", [])
    if len(files) > specs.max_files_changed_per_cycle:
        raise EditRejected(
            f"change touches {len(files)} files, exceeds max_files_changed_per_cycle="
            f"{specs.max_files_changed_per_cycle}"
        )

    for f in files:
        rel = f["path"]
        if specs.is_path_forbidden(rel):
            raise EditRejected(f"refused: '{rel}' is under a forbidden path")

    touched = []
    for f in files:
        rel = f["path"]
        action = f["action"]
        abs_path = _safe_resolve(specs.target_dir, rel)

        if action == "delete":
            if abs_path.exists():
                abs_path.unlink()
            touched.append(rel)
        elif action in ("replace", "create"):
            if action == "create" and abs_path.exists():
                raise EditRejected(f"action=create but file already exists: {rel}")
            if action == "replace" and not abs_path.exists():
                raise EditRejected(f"action=replace but file does not exist: {rel}")
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            abs_path.write_text(f["content"], encoding="utf-8")
            touched.append(rel)
        else:
            raise EditRejected(f"unknown action: {action}")

    return touched
