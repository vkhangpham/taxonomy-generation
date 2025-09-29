"""End-to-end smoke tests for the Typer-based taxonomy CLI."""

from __future__ import annotations

import json
from types import SimpleNamespace
from pathlib import Path

import pytest
from typer.testing import CliRunner

from taxonomy.cli.main import app
from taxonomy.cli.common import _partition_global_arguments


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def cli_env(tmp_path: Path) -> dict[str, str]:
    output_dir = tmp_path / "output"
    cache_dir = tmp_path / "cache"
    return {
        "TAXONOMY_SETTINGS__PATHS__OUTPUT_DIR": str(output_dir),
        "TAXONOMY_SETTINGS__PATHS__CACHE_DIR": str(cache_dir),
        "TAXONOMY_SETTINGS__PATHS__LOGS_DIR": str(tmp_path / "logs"),
        "TAXONOMY_SETTINGS__PATHS__METADATA_DIR": str(tmp_path / "metadata"),
    }


def test_partition_global_arguments_splits_flags_and_segments() -> None:
    global_args, command_args = _partition_global_arguments(
        ["--environment", "development", "--resume-phase", "S1"]
    )

    assert global_args == ["--environment", "development"]
    assert command_args == ["--resume-phase", "S1"]


def test_partition_global_arguments_handles_repeatable_overrides() -> None:
    global_args, command_args = _partition_global_arguments(
        ["--override", "policy.alpha=1", "-o", "policy.beta=2", "--override=policy.gamma=3"]
    )

    assert global_args == [
        "--override",
        "policy.alpha=1",
        "-o",
        "policy.beta=2",
        "--override=policy.gamma=3",
    ]
    assert command_args == []


def test_partition_stops_at_first_subcommand_token() -> None:
    global_args, command_args = _partition_global_arguments(
        ["--environment", "development", "pipeline", "--verbose", "--resume-phase", "S1"]
    )

    assert global_args == ["--environment", "development"]
    assert command_args == ["pipeline", "--verbose", "--resume-phase", "S1"]


def test_partition_supports_combined_short_flags_and_values() -> None:
    # -v (flag) combined with -o (expects value) and value provided as next token
    global_args, command_args = _partition_global_arguments(["-vo", "policy.alpha=1", "pipeline"]) 
    assert global_args == ["-v", "-o", "policy.alpha=1"]
    assert command_args == ["pipeline"]


def test_partition_supports_short_equals_and_glued_values() -> None:
    # -o=value and -ovalue forms are both accepted
    g1, c1 = _partition_global_arguments(["-o=policy.beta=2", "dev"]) 
    g2, c2 = _partition_global_arguments(["-opoly.gamma=3", "dev"]) 
    assert g1 == ["-o", "policy.beta=2"] and c1 == ["dev"]
    assert g2 == ["-o", "poly.gamma=3"] and c2 == ["dev"]


def test_partition_supports_long_equals_and_terminator() -> None:
    g, c = _partition_global_arguments(["--run-id=abc", "--", "--override", "x=1"]) 
    assert g == ["--run-id=abc"]
    assert c == ["--", "--override", "x=1"]


def test_pipeline_generate_invokes_stage(monkeypatch: pytest.MonkeyPatch, runner: CliRunner, cli_env: dict[str, str], tmp_path: Path) -> None:
    called: dict[str, Path] = {}

    def fake_extract(input_path, output_path, **kwargs):  # type: ignore[unused-argument]
        called["input"] = Path(input_path)
        called["output"] = Path(output_path)
        return {"records": []}

    monkeypatch.setattr("taxonomy.cli.pipeline.extract_from_snapshots", fake_extract)

    input_file = tmp_path / "snapshots.jsonl"
    input_file.write_text("{}\n", encoding="utf-8")
    output_file = tmp_path / "records.jsonl"

    result = runner.invoke(
        app,
        [
            "--no-observability",
            "pipeline",
            "generate",
            "--step",
            "S0",
            "--input",
            str(input_file),
            "--output",
            str(output_file),
        ],
        env=cli_env,
    )

    assert result.exit_code == 0, result.output
    assert called["input"].resolve() == input_file.resolve()
    assert called["output"].resolve() == output_file.resolve()


def test_postprocess_validate_reports_summary(monkeypatch: pytest.MonkeyPatch, runner: CliRunner, cli_env: dict[str, str], tmp_path: Path) -> None:
    class Decision:
        def __init__(self, passed: bool) -> None:
            self.passed = passed

    class Outcome:
        def __init__(self, passed: bool) -> None:
            self.decision = Decision(passed)

    def fake_validate(input_path, snapshots, output_path, **kwargs):  # type: ignore[unused-argument]
        return [Outcome(True), Outcome(False)]

    monkeypatch.setattr("taxonomy.cli.postprocess.validate_concepts", fake_validate)

    concepts = tmp_path / "concepts.jsonl"
    concepts.write_text("{}\n", encoding="utf-8")
    output = tmp_path / "validated.jsonl"

    result = runner.invoke(
        app,
        [
            "--no-observability",
            "postprocess",
            "validate",
            "--input",
            str(concepts),
            "--output",
            str(output),
        ],
        env=cli_env,
    )

    assert result.exit_code == 0, result.output
    assert "Passed" in result.output


def test_utilities_optimize_prompt_uses_objective(monkeypatch: pytest.MonkeyPatch, runner: CliRunner, cli_env: dict[str, str], tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    class StubOptimizer:
        def __init__(self, *, policy, llm_settings, reflection_model=None):  # type: ignore[unused-argument]
            captured["policy_budget"] = getattr(policy, "optimization_budget", "")

        def optimize(self, prompt_key, dataset_path, deploy=True):  # type: ignore[unused-argument]
            return SimpleNamespace(
                optimization_report={"selected_config": {}, "best_validation_score": 0.42},
                deployed_variant=None,
            )

    def fake_builder(objective):  # type: ignore[unused-argument]
        return StubOptimizer

    monkeypatch.setattr("taxonomy.cli.utilities._build_objective_optimizer", fake_builder)

    dataset = tmp_path / "dataset.json"
    dataset.write_text(json.dumps({"train": [], "validation": []}), encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "--no-observability",
            "utilities",
            "optimize-prompt",
            "--prompt-key",
            "s1",
            "--dataset",
            str(dataset),
            "--objective",
            "precision",
            "--max-trials",
            "8",
            "--no-deploy",
        ],
        env=cli_env,
    )

    assert result.exit_code == 0, result.output
    assert captured["policy_budget"] == "light"


def test_management_manifest_yaml_output(runner: CliRunner, cli_env: dict[str, str], tmp_path: Path) -> None:
    run_dir = tmp_path / "output" / "runs" / "run-123"
    run_dir.mkdir(parents=True)
    manifest_path = run_dir / "run_manifest.json"
    manifest_path.write_text(json.dumps({"run_id": "run-123", "phases": []}), encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "--no-observability",
            "manage",
            "manifest",
            "--run-id",
            "run-123",
            "--format",
            "yaml",
        ],
        env=cli_env,
    )

    assert result.exit_code == 0, result.output
    assert "run-123" in result.output


def test_development_export_filters_level(runner: CliRunner, cli_env: dict[str, str], tmp_path: Path) -> None:
    source = tmp_path / "concepts.jsonl"
    source.write_text("""{"level": 1, "label": "A"}\n{"level": 2, "label": "B"}\n""", encoding="utf-8")
    destination = tmp_path / "subset.json"

    result = runner.invoke(
        app,
        [
            "--no-observability",
            "dev",
            "export",
            "--source",
            str(source),
            "--output",
            str(destination),
            "--format",
            "json",
            "--level",
            "1",
        ],
        env=cli_env,
    )

    assert result.exit_code == 0, result.output
    exported = json.loads(destination.read_text(encoding="utf-8"))
    assert exported == [{"level": 1, "label": "A"}]
