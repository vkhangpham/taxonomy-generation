"""Checkpoint management for resumable taxonomy runs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Optional, Sequence

from taxonomy.utils.helpers import ensure_directory, serialize_json
from taxonomy.utils.logging import get_logger

_LOGGER = get_logger(module=__name__)


class CheckpointManager:
    """Persists phase checkpoints and associated metadata to disk."""

    def __init__(self, run_id: str, base_directory: Path | str) -> None:
        self.run_id = run_id
        base = Path(base_directory)
        if base.name == run_id:
            target = base
        else:
            target = base / run_id
        self.base_directory = ensure_directory(target)
        self._meta_path = self.base_directory / "artifacts.json"
        if not self._meta_path.exists():
            serialize_json({"artifacts": []}, self._meta_path)

    # ------------------------------------------------------------------
    # Phase checkpoint persistence
    # ------------------------------------------------------------------
    def checkpoint_path(self, phase: str) -> Path:
        return self.base_directory / f"{phase}.checkpoint.json"

    def save_phase_checkpoint(self, phase: str, state: Dict[str, object]) -> Path:
        payload = {
            "run_id": self.run_id,
            "phase": phase,
            "state": state,
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        path = self.checkpoint_path(phase)
        serialize_json(payload, path)
        _LOGGER.info("Saved phase checkpoint", run_id=self.run_id, phase=phase)
        return path

    def load_phase_checkpoint(self, phase: str) -> Optional[dict]:
        path = self.checkpoint_path(phase)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.validate_checkpoint(payload)
        return payload

    def validate_checkpoint(self, checkpoint: dict) -> None:
        run_id = checkpoint.get("run_id")
        if run_id != self.run_id:
            raise ValueError(
                f"Checkpoint run_id mismatch: expected {self.run_id}, found {run_id}"
            )

    def determine_resume_point(self, phases: Sequence[str]) -> Optional[str]:
        completed = [phase for phase in phases if self.checkpoint_path(phase).exists()]
        return completed[-1] if completed else None

    def recover_progress(self, phase: str) -> Optional[dict]:
        checkpoint = self.load_phase_checkpoint(phase)
        if checkpoint is None:
            return None
        return checkpoint.get("state")

    def cleanup_checkpoints(self, keep_final: bool = True) -> None:
        checkpoints = sorted(
            self.base_directory.glob("*.checkpoint.json"),
            key=lambda candidate: candidate.stat().st_mtime,
        )
        if keep_final and checkpoints:
            checkpoints = checkpoints[:-1]
        for path in checkpoints:
            path.unlink(missing_ok=True)
        _LOGGER.info("Cleaned up checkpoints", run_id=self.run_id)

    # ------------------------------------------------------------------
    # Artifact tracking
    # ------------------------------------------------------------------
    def record_artifact(self, path: Path | str, *, kind: str) -> None:
        payload = json.loads(self._meta_path.read_text(encoding="utf-8"))
        artifacts = payload.setdefault("artifacts", [])
        artifacts.append(
            {
                "path": str(Path(path).resolve()),
                "kind": kind,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        serialize_json(payload, self._meta_path)

    def iter_artifacts(self) -> Iterable[dict]:
        payload = json.loads(self._meta_path.read_text(encoding="utf-8"))
        yield from payload.get("artifacts", [])


__all__ = ["CheckpointManager"]
