import json
from pathlib import Path

import pytest

from taxonomy.config.policies import ObservabilityPolicy
from taxonomy.config.settings import Settings
from taxonomy.observability import CounterRegistry, ObservabilityContext
from taxonomy.orchestration.checkpoints import CheckpointManager
from taxonomy.orchestration.manifest import RunManifest
from taxonomy.orchestration.phases import PhaseManager


def test_counter_registry_tracks_increments() -> None:
    registry = CounterRegistry(run_id="test")
    registry.push_phase("S1")
    registry.increment("records_in", 3)
    registry.increment("candidates_out", 2)
    registry.increment("retries")
    registry.pop_phase("S1")

    snapshot = registry.snapshot()
    assert snapshot.counters["S1"]["records_in"] == 3
    assert snapshot.counters["S1"]["candidates_out"] == 2
    assert snapshot.counters["S1"]["retries"] == 1


def test_observability_context_captures_evidence_and_quarantine() -> None:
    policy = ObservabilityPolicy(evidence_sampling_rate=1.0, deterministic_sampling_seed=1337)
    context = ObservabilityContext(run_id="run", policy=policy)
    with context.phase("S1") as phase:
        phase.increment("records_in", 2)
        phase.increment("candidates_out", value=1)
        phase.evidence(
            category="extraction",
            outcome="success",
            payload={"record": "abc"},
        )
        phase.quarantine(
            reason="invalid_json",
            item_id="record-123",
            payload={"error": "invalid"},
        )
        phase.log_operation(operation="test_op")
        phase.performance({"elapsed_seconds": 0.01})

    snapshot = context.snapshot()
    assert snapshot.counters["S1"]["records_in"] == 2
    assert snapshot.quarantine["total"] == 1
    assert snapshot.quarantine["by_reason"]["invalid_json"] == 1
    evidence_samples = snapshot.evidence["samples"].get("S1", [])
    assert evidence_samples
    assert evidence_samples[0]["payload"]["record"] == "abc"
    assert snapshot.operations[0].operation == "test_op"
    assert snapshot.performance["S1"]["elapsed_seconds"] == pytest.approx(0.01, rel=1e-6)


def _make_phase_manager(tmp_path: Path) -> PhaseManager:
    settings = Settings()
    manifest = RunManifest(
        "run",
        policy=settings.policies.observability,
    )
    checkpoints = CheckpointManager("run", tmp_path)

    def level_generator(context, level: int):
        with context.phase("S1") as phase:
            phase.increment("records_in", 1)
            phase.increment("candidates_out", 1)
            phase.evidence(
                category="extraction",
                outcome="success",
                payload={"level": level},
            )
        return {"stats": {"records_in": 1, "candidates_out": 1}}

    def consolidator(context):
        with context.phase("S2") as phase:
            phase.increment("candidates_in", 1)
            phase.increment("kept", 1)
        return {"stats": {"candidates_in": 1, "kept": 1}}

    def post_processor(context):
        with context.phase("S3") as phase:
            phase.increment("checked", 1)
            phase.increment("passed_rule", 1)
            phase.increment("passed_llm", 1)
        return {"changed": False}

    def finalizer(context):
        with context.phase("Hierarchy") as phase:
            phase.increment("nodes_in", 1)
            phase.increment("nodes_kept", 1)
        return {
            "stats": {"nodes_in": 1, "nodes_kept": 1},
            "validation": {"nodes": ["n1"]},
        }

    manager = PhaseManager(
        settings=settings,
        checkpoint_manager=checkpoints,
        manifest=manifest,
        level_generators={i: level_generator for i in range(4)},
        consolidator=consolidator,
        post_processors=[post_processor],
        finalizer=finalizer,
    )
    manifest.collect_versions(settings=settings)
    manifest.capture_configuration(settings=settings)
    return manager


def test_phase_manager_emits_observability_events(tmp_path) -> None:
    manager = _make_phase_manager(Path(tmp_path))
    manager.execute_all(resume_from=None)

    snapshot = manager.observability.snapshot()
    assert snapshot.counters["S1"]["records_in"] == 4
    assert snapshot.counters["S1"]["candidates_out"] == 4
    assert snapshot.counters["S2"]["kept"] == 1
    assert snapshot.counters["S3"]["checked"] == 1
    assert snapshot.counters["Hierarchy"]["nodes_in"] == 1

    data = manager.observability.export()
    assert data["performance"]
    assert any(op["operation"] == "complete" for op in data["operations"])

    manifest_data = manager._manifest.finalize()
    assert manifest_data["observability"]["counters"]["S1"]["records_in"] == 4
    assert manifest_data["observability"]["thresholds"]
    assert manifest_data["operation_logs"]
    assert manifest_data["evidence_samples"]
    assert "checksum" in manifest_data["observability"]

    # Ensure checkpoints were written
    checkpoint_path = manager._checkpoint_manager.checkpoint_path("phase1_level0")
    assert checkpoint_path.exists()
    checkpoint_payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert checkpoint_payload["phase"] == "phase1_level0"
