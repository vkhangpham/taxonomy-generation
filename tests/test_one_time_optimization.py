"""Tests for the one-time GEPA prompt optimization workflow."""

from __future__ import annotations

import contextlib
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import dspy
import pytest
import yaml

from taxonomy.config.settings import Settings
from taxonomy.prompt_optimization.dataset_loader import DatasetLoader
from taxonomy.prompt_optimization.deployment import VariantDeployer
from taxonomy.prompt_optimization.evaluation_metric import TaxonomyEvaluationMetric
from taxonomy.prompt_optimization.one_time_optimizer import OneTimeGEPAOptimizer

from taxonomy.llm.validation import JSONValidator

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROMPTS_DIR = PROJECT_ROOT / "prompts"


def _write_dataset(path: Path) -> None:
    records = [
        {
            "input": "College of Engineering",
            "expected": ["engineering"],
            "level": 0,
        },
        {
            "input": "School of Medicine",
            "expected": ["medicine"],
            "level": 0,
        },
        {
            "input": "Department of Computer Science",
            "expected": ["computer science"],
            "level": 1,
        },
        {
            "input": "Center for Quantum Computing",
            "expected": ["quantum computing"],
            "level": 2,
        },
    ]
    path.write_text(json.dumps(records), encoding="utf-8")


def test_dataset_loader_split(tmp_path: Path) -> None:
    dataset_path = tmp_path / "dataset.json"
    _write_dataset(dataset_path)
    loader = DatasetLoader(dataset_path, validation_ratio=0.25, seed=13)
    split = loader.load()
    assert len(split.train) + len(split.validation) == 4
    assert {getattr(example, "level") for example in split.train + split.validation} == {0, 1, 2}
    assert set(example.gold_labels[0] for example in split.train) | set(
        example.gold_labels[0] for example in split.validation
    ) == {"engineering", "medicine", "computer science", "quantum computing"}


def test_taxonomy_evaluation_metric_guardrails() -> None:
    validator = JSONValidator(schema_base_path=PROMPTS_DIR)
    metric = TaxonomyEvaluationMetric(validator=validator)

    gold = dspy.Example(
        institution="Test",
        level=0,
        source_text="Sample",
        gold_labels=["engineering"],
    ).with_inputs("institution", "level", "source_text")

    valid_payload = json.dumps(
        [
            {
                "label": "College of Engineering",
                "normalized": "engineering",
                "aliases": ["engineering"],
                "parents": [],
            }
        ]
    )
    prediction = SimpleNamespace(response=valid_payload)
    result = metric(gold, prediction)
    assert pytest.approx(result.score) == 1.0

    invalid_prediction = SimpleNamespace(response="not-json")
    result = metric(gold, invalid_prediction)
    assert result.score == 0.0
    assert "Guardrail violation" in result.feedback


def test_variant_deployer_creates_new_variant(tmp_path: Path) -> None:
    registry_src = PROMPTS_DIR / "registry.yaml"
    registry_copy = tmp_path / "registry.yaml"
    shutil.copy2(registry_src, registry_copy)
    templates_root = tmp_path / "prompts" / "templates"

    class StubProgram:
        def render_template(self) -> str:
            return "You are an optimized extractor."

        def prompt_metadata(self) -> dict:
            return {"constraint_variant": "baseline"}

    deployer = VariantDeployer(
        registry_file=registry_copy,
        templates_root=templates_root,
        backup_before_deployment=False,
    )
    report = {"description": "Test deployment", "best_validation_score": 0.91}
    variant_key, template_path = deployer.deploy(
        prompt_key="taxonomy.extract",
        program=StubProgram(),
        optimization_report=report,
        activate=True,
    )

    assert variant_key.startswith("v")
    created_template = templates_root.parent / template_path
    assert created_template.exists()

    with registry_copy.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    prompt_entry = data["prompts"]["taxonomy.extract"]
    assert prompt_entry["active_variant"] == variant_key
    assert variant_key in prompt_entry["variants"]


def test_one_time_optimizer_runs_without_deploy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    dataset_path = tmp_path / "dataset.json"
    _write_dataset(dataset_path)

    settings = Settings(environment="development", create_dirs=False)
    policy = settings.policies.prompt_optimization.model_copy(update={"deploy_immediately": False})

    @contextlib.contextmanager
    def _mock_configure(self, **_: object):  # type: ignore[override]
        yield

    monkeypatch.setattr(dspy.settings.__class__, "configure", _mock_configure, raising=False)

    class DummyGEPA:
        def __init__(self, *_, **__):
            self.compile_calls = 0

        def compile(self, program, trainset, valset):
            self.compile_calls += 1
            program.detailed_results = SimpleNamespace(best_val_score=0.88)
            assert len(trainset) > 0
            assert len(valset) > 0
            return program

    monkeypatch.setattr(dspy, "GEPA", DummyGEPA)

    optimizer = OneTimeGEPAOptimizer(
        policy=policy,
        llm_settings=settings.policies.llm,
        reflection_model=policy.reflection_model,
    )

    result = optimizer.optimize(
        prompt_key="taxonomy.extract",
        dataset_path=dataset_path,
        deploy=False,
    )

    assert result.deployed_variant is None
    assert result.optimization_report["train_examples"] > 0
    assert result.optimization_report["validation_examples"] > 0
    assert "metric" in result.optimization_report
