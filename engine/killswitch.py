"""
Two files, checked at the START of every single cycle (never mid-cycle, so a
cycle always finishes cleanly or reverts cleanly -- never half-applied):

  state/STOP   -> present means: finish current cycle bookkeeping, then exit.
  state/PAUSE  -> present means: sleep and re-check, don't burn budget, don't exit.

Delete the file (or use `python run.py resume` / `python run.py stop`) to
change state. This is the "big red button" -- it works even if the LLM or
orchestrator logic misbehaves, because it's checked by plain file existence,
nothing fancier.
"""
from __future__ import annotations

from pathlib import Path


class KillSwitch:
    def __init__(self, state_dir: Path):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.stop_file = self.state_dir / "STOP"
        self.pause_file = self.state_dir / "PAUSE"

    def is_stopped(self) -> bool:
        return self.stop_file.exists()

    def is_paused(self) -> bool:
        return self.pause_file.exists()

    def stop(self):
        self.stop_file.touch()

    def resume(self):
        self.pause_file.unlink(missing_ok=True)

    def pause(self):
        self.pause_file.touch()

    def clear_stop(self):
        self.stop_file.unlink(missing_ok=True)
