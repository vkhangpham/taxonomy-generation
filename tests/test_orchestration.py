from __future__ import annotations

from pathlib import Path

import os
import time
import pytest

from taxonomy.config.settings import Settings
from taxonomy.orchestration import TaxonomyOrchestrator, run_taxonomy_pipeline
from taxonomy.orchestration.checkpoints import CheckpointManager

def _build_settings(tmp_path: Path) -> Settings:
    overrides = {
        "create_dirs": True,
        "paths": {
            "data_dir": str(tmp_path / "data"),
            "output_dir": str(tmp_path / "output"),
            "cache_dir": str(tmp_path / "cache"),
            "logs_dir": str(tmp_path / "logs"),
            "metadata_dir": str(tmp_path / "metadata"),
        },
    }
    return Settings(**overrides)


def test_phase_execution_records_all_phases(tmp_path: Path):
    settings = _build_settings(tmp_path)

    call_order: list[str] = []

    def make_level_generator(level: int):
        def generator(context, lvl: int):
            assert lvl == level
            call_order.append(f"level{lvl}")
            return {"candidates": [f"L{lvl}"], "stats": {"level": lvl}}

        return generator

    level_generators = {level: make_level_generator(level) for level in range(4)}

    def consolidator(context):
        call_order.append("consolidation")
        return {"concepts": ["c"], "stats": {"concepts": 1}}

    def validation(context):
        call_order.append("validation")
        return {"stage": "validation", "changed": False, "concepts": ["c"]}

    def dedup(context):
        call_order.append("dedup")
        return {"stage": "dedup", "changed": False, "concepts": ["c"]}

    def finalizer(context):
        call_order.append("finalize")
        return {"stats": {"concepts": 0}, "validation": {"passed": True}}

    orchestrator = TaxonomyOrchestrator.from_settings(
        settings,
        run_id="phase-test",
        adapters={
            "level_generators": level_generators,
            "consolidator": consolidator,
            "post_processors": [validation, dedup],
            "finalizer": finalizer,
        },
    )

    result = orchestrator.run()

    assert call_order == [
        "level0",
        "level1",
        "level2",
        "level3",
        "consolidation",
        "validation",
        "dedup",
        "finalize",
    ]
    assert "phase1_level0" in result.phase_results
    assert result.manifest["statistics"]


def test_orchestrator_resume_skips_completed_phases(tmp_path: Path):
    settings = _build_settings(tmp_path)

    executed: list[str] = []

    def make_level_generator(level: int):
        def generator(context, lvl: int):
            executed.append(f"level{lvl}")
            return {"candidates": [f"L{lvl}"], "stats": {"level": lvl}}

        return generator

    orchestrator = TaxonomyOrchestrator.from_settings(
        settings,
        run_id="resume-test",
        adapters={
            "level_generators": {level: make_level_generator(level) for level in range(4)},
            "consolidator": lambda ctx: {"concepts": [], "stats": {}},
            "post_processors": [lambda ctx: {"stage": "validation", "changed": False}],
            "finalizer": lambda ctx: {"stats": {}, "validation": {}},
        },
    )

    orchestrator._checkpoint_manager.save_phase_checkpoint("phase1_level0", {"status": "completed"})

    orchestrator.run()

    assert "level0" not in executed
    assert "level1" in executed


def test_run_taxonomy_pipeline_creates_manifest(tmp_path: Path):
    overrides = {
        "create_dirs": True,
        "paths": {
            "data_dir": str(tmp_path / "data"),
            "output_dir": str(tmp_path / "output"),
            "cache_dir": str(tmp_path / "cache"),
            "logs_dir": str(tmp_path / "logs"),
            "metadata_dir": str(tmp_path / "metadata"),
        },
    }
    result = run_taxonomy_pipeline(config_overrides=overrides)
    assert result.manifest_path.exists()
    assert result.manifest["run_id"]


def test_checkpoint_manager_records_artifact(tmp_path: Path):
    manager = CheckpointManager("artifact-test", tmp_path)
    dummy = tmp_path / "dummy.txt"
    dummy.write_text("data", encoding="utf-8")
    manager.record_artifact(dummy, kind="test")
    artifacts = list(manager.iter_artifacts())
    assert artifacts and artifacts[0]["kind"] == "test"


def test_cleanup_checkpoints_no_files(tmp_path: Path):
    manager = CheckpointManager("cleanup-empty", tmp_path)

    removed, failures = manager.cleanup_checkpoints()

    assert removed == []
    assert failures == []


def test_cleanup_checkpoints_respects_keep_and_ties(tmp_path: Path):
    manager = CheckpointManager("cleanup-order", tmp_path)
    older_a = manager.base_directory / "older_a.checkpoint.json"
    older_b = manager.base_directory / "older_b.checkpoint.json"
    newest = manager.base_directory / "newest.checkpoint.json"

    for path in (older_a, older_b, newest):
        path.write_text("{}", encoding="utf-8")

    past = time.time() - 3600
    os.utime(older_a, (past, past))
    os.utime(older_b, (past, past))
    now = time.time()
    os.utime(newest, (now, now))

    removed, failures = manager.cleanup_checkpoints(keep_latest_n=1)

    assert [path.name for path in removed] == [
        "older_a.checkpoint.json",
        "older_b.checkpoint.json",
    ]
    assert failures == []
    assert not older_a.exists()
    assert not older_b.exists()
    assert newest.exists()


def test_cleanup_checkpoints_handles_stat_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    manager = CheckpointManager("cleanup-stat-error", tmp_path)
    good = manager.base_directory / "good.checkpoint.json"
    bad = manager.base_directory / "bad.checkpoint.json"
    for path in (good, bad):
        path.write_text("{}", encoding="utf-8")

    real_stat = Path.stat

    def fake_stat(self: Path):
        if self.name == bad.name:
            raise OSError("stat boom")
        return real_stat(self)

    monkeypatch.setattr(Path, "stat", fake_stat)

    removed, failures = manager.cleanup_checkpoints(keep_latest_n=0)

    monkeypatch.setattr(Path, "stat", real_stat)

    assert removed == [good]
    assert failures == []
    assert not good.exists()
    assert bad.exists()


def test_cleanup_checkpoints_dry_run_reports_candidates(tmp_path: Path):
    manager = CheckpointManager("cleanup-dry-run", tmp_path)
    old_file = manager.base_directory / "old.checkpoint.json"
    fresh_file = manager.base_directory / "fresh.checkpoint.json"

    for path in (old_file, fresh_file):
        path.write_text("{}", encoding="utf-8")

    now = time.time()
    os.utime(old_file, (now - 120, now - 120))
    os.utime(fresh_file, (now, now))

    removed, failures = manager.cleanup_checkpoints(
        keep_latest_n=0,
        dry_run=True,
        grace_period_s=60,
    )

    assert removed == [old_file]
    assert failures == []
    assert old_file.exists()
    assert fresh_file.exists()
