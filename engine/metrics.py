"""
Runs the domain's eval_command/validation_command (defined in specs.md) as a
subprocess. The engine never interprets the METRICS itself -- it only
requires the command print a single JSON object to stdout, e.g.:

    {"sharpe_ratio": 1.32, "max_drawdown": 0.09, "trades": 88, "win_rate": 0.54}

This keeps the engine domain-agnostic: swap eval_command in specs.md and the
same code works for a forex ANN, a test-coverage script, anything.
"""
from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path


class EvalError(RuntimeError):
    pass


@dataclass
class EvalResult:
    metrics: dict
    raw_stdout: str
    raw_stderr: str
    passed_gates: bool
    gate_failures: list


def run_eval_command(command: str, cwd: Path, timeout: int = 1800) -> EvalResult:
    try:
        result = subprocess.run(
            shlex.split(command),
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise EvalError(f"eval command timed out after {timeout}s: {command}") from e

    if result.returncode != 0:
        raise EvalError(
            f"eval command exited {result.returncode}: {command}\nstderr:\n{result.stderr[-2000:]}"
        )

    metrics = _extract_json(result.stdout)
    if metrics is None:
        raise EvalError(
            f"could not find a JSON object in eval command stdout.\nstdout was:\n{result.stdout[-2000:]}"
        )

    return EvalResult(
        metrics=metrics,
        raw_stdout=result.stdout,
        raw_stderr=result.stderr,
        passed_gates=True,
        gate_failures=[],
    )


def _extract_json(stdout: str) -> dict | None:
    # Try whole-output parse first, then fall back to the last {...} block
    # (in case the eval script also prints progress logs before the result).
    stdout = stdout.strip()
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        pass
    start = stdout.rfind("{")
    while start != -1:
        candidate = stdout[start:]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            start = stdout.rfind("{", 0, start)
    return None


def check_hard_gates(metrics: dict, hard_gates: dict) -> list[str]:
    """
    hard_gates entries in specs.md are named like 'max_drawdown' / 'min_trades'.
    Convention: 'max_X' means the relevant metric must be <= value; 'min_X'
    means >= value.

    The relevant metric is looked up two ways, checked in this order:
      1. Literally: metrics[gate_name] -- e.g. gate 'max_drawdown' against a
         metric field also named 'max_drawdown' (common: your eval script's
         field names already match the gate names in specs.md).
      2. Prefix-stripped: metrics[gate_name without 'max_'/'min_'] -- e.g.
         gate 'min_trades' against a metric field named 'trades'.
    Both conventions are supported since real eval scripts use either.
    A gate whose metric can't be found under either name is skipped, not
    silently treated as passing -- silently ignoring a misconfigured gate
    would defeat the whole point of a hard gate, so warn upstream via the
    returned failures list using a distinct marker.
    """
    failures = []
    for gate_name, threshold in hard_gates.items():
        is_max = gate_name.startswith("max_")
        is_min = gate_name.startswith("min_")
        stripped_key = gate_name[4:] if (is_max or is_min) else None

        if gate_name in metrics:
            value = metrics[gate_name]
        elif stripped_key is not None and stripped_key in metrics:
            value = metrics[stripped_key]
        else:
            failures.append(f"{gate_name}: metric not found in eval output (gate cannot be checked -- treat as unsafe)")
            continue

        if is_max and value > threshold:
            failures.append(f"{gate_name}: {value} > {threshold}")
        elif is_min and value < threshold:
            failures.append(f"{gate_name}: {value} < {threshold}")
        elif not is_max and not is_min and value != threshold:
            failures.append(f"{gate_name}: {value} != {threshold}")
    return failures


def compare_for_regression(before: dict, after: dict, primary_metric: str) -> tuple[bool, str]:
    """Returns (is_improvement, explanation) comparing primary metric before/after."""
    if primary_metric not in before or primary_metric not in after:
        return True, f"primary metric '{primary_metric}' missing from one side; not blocking"
    b, a = before[primary_metric], after[primary_metric]
    if a >= b:
        return True, f"{primary_metric}: {b} -> {a} (improved or held)"
    return False, f"{primary_metric}: {b} -> {a} (regressed)"
