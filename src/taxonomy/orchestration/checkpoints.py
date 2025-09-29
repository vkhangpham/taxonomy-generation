"""Checkpoint management for resumable taxonomy runs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Optional, Sequence

from taxonomy.utils.helpers import ensure_directory, serialize_json
from taxonomy.utils.logging import get_logger

import time
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

    def cleanup_checkpoints(
        self,
        keep_latest_n: int = 1,
        dry_run: bool = False,
        grace_period_s: float = 0.0,
    ) -> tuple[list[Path], list[tuple[Path, str]]]:
        """Remove stale checkpoint files while respecting recency and guardrails.

        Checkpoints are ordered by modification time (oldest first) and ties are
        resolved by filename to guarantee deterministic behaviour. The newest
        ``keep_latest_n`` checkpoints are retained, and any candidates newer than
        ``grace_period_s`` seconds (relative to the current wall clock) are
        preserved even if they exceed the retention limit. When ``dry_run`` is
        true the method only reports what *would* be removed without unlinking
        files. The return value contains the list of checkpoint paths selected
        for deletion and a list of pairs describing paths that could not be
        inspected or removed together with the associated error message.
        """

        failures: list[tuple[Path, str]] = []
        checkpoint_entries: list[tuple[Path, float]] = []
        for candidate in self.base_directory.glob("*.checkpoint.json"):
            try:
                stat_result = candidate.stat()
            except OSError as error:
                _LOGGER.warning(
                    "Unable to stat checkpoint during cleanup",
                    path=str(candidate),
                    error=str(error),
                    run_id=self.run_id,
                )
                continue
            checkpoint_entries.append((candidate, stat_result.st_mtime))

        checkpoint_entries.sort(key=lambda item: (item[1], item[0].name))
        keep = max(keep_latest_n, 0)
        if keep:
            candidates = checkpoint_entries[:-keep]
        else:
            candidates = checkpoint_entries

        now = time.time()
        to_remove: list[Path] = []
        for path, mtime in candidates:
            if grace_period_s > 0 and (now - mtime) < grace_period_s:
                _LOGGER.debug(
                    "Skipping checkpoint within grace period",
                    path=str(path),
                    run_id=self.run_id,
                    grace_period_s=grace_period_s,
                )
                continue
            to_remove.append(path)

        removed: list[Path] = []
        for path in to_remove:
            if dry_run:
                _LOGGER.info(
                    "Dry run - would remove checkpoint",
                    path=str(path),
                    run_id=self.run_id,
                )
                removed.append(path)
                continue
            try:
                path.unlink(missing_ok=True)
            except OSError as error:
                failures.append((path, str(error)))
                _LOGGER.error(
                    "Failed to remove checkpoint",
                    path=str(path),
                    error=str(error),
                    run_id=self.run_id,
                )
            else:
                removed.append(path)
                _LOGGER.info(
                    "Removed checkpoint",
                    path=str(path),
                    run_id=self.run_id,
                )

        _LOGGER.info(
            "Checkpoint cleanup finished",
            run_id=self.run_id,
            keep_latest_n=keep_latest_n,
            dry_run=dry_run,
            grace_period_s=grace_period_s,
            removed=[str(path) for path in removed],
            failures=[{"path": str(path), "error": error} for path, error in failures],
        )
        return removed, failures

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
