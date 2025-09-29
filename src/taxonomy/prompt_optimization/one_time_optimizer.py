"""One-time GEPA optimization orchestrator for taxonomy prompts."""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import dspy

from ..config.policies import LLMDeterminismSettings, PromptOptimizationPolicy
from ..llm.validation import JSONValidator
from .dataset_loader import DatasetLoader
from .deployment import deploy_optimized_variant
from .dspy_program import TaxonomyExtractor
from .evaluation_metric import TaxonomyEvaluationMetric


@dataclass
class OptimizationResult:
    """Artifacts returned after running a one-time optimization."""

    optimized_program: TaxonomyExtractor
    optimization_report: Dict[str, Any]
    deployed_variant: Optional[str] = None
    deployed_template: Optional[Path] = None


@dataclass(frozen=True)
class LeverConfig:
    """Search lever combination explored during optimization."""

    few_shot_k: int
    constraint_variant: str
    temperature: float


@dataclass
class LeverRun:
    """Captured results for a single lever configuration."""

    config: LeverConfig
    optimized_program: TaxonomyExtractor
    metric_summary: Dict[str, float]
    best_validation_score: Optional[float]
    detailed_results: Any


class OneTimeGEPAOptimizer:
    """Run GEPA once with comprehensive search and optional deployment."""

    def __init__(
        self,
        *,
        policy: PromptOptimizationPolicy,
        llm_settings: LLMDeterminismSettings,
        reflection_model: Optional[str] = None,
    ) -> None:
        self._policy = policy
        self._llm_settings = llm_settings
        self._reflection_model = reflection_model or self._default_reflection_model()

    def optimize(
        self,
        *,
        prompt_key: str,
        dataset_path: Path,
        deploy: bool = True,
    ) -> OptimizationResult:
        """Run GEPA with strict guardrails and optionally deploy the best variant."""

        dataset = DatasetLoader(
            dataset_path,
            validation_ratio=self._policy.validation_ratio,
            seed=self._policy.random_seed,
        ).load()

        lever_configs = self._generate_lever_configs(len(dataset.train))
        lever_runs: List[LeverRun] = []
        validator_root = Path(self._llm_settings.registry.schema_root)

        for config in lever_configs:
            validator = JSONValidator(schema_base_path=validator_root)
            metric = TaxonomyEvaluationMetric(
                validator=validator,
                schema_path="schemas/extraction.json",
                json_validity_threshold=self._policy.json_validity_threshold,
                schema_adherence_threshold=self._policy.schema_adherence_threshold,
            )

            program = TaxonomyExtractor(
                few_shot_examples=dataset.train,
                few_shot_k=config.few_shot_k,
                constraint_variant=config.constraint_variant,
                ordering_seed=self._policy.random_seed,
                temperature=config.temperature,
            )
            program.configure_examples(dataset.train)

            target_lm = self._build_target_lm(config.temperature)
            with dspy.settings.configure(lm=target_lm):
                reflection_lm = self._build_reflection_lm()
                gepa = dspy.GEPA(
                    metric=metric,
                    auto=self._policy.optimization_budget,
                    reflection_lm=reflection_lm,
                    track_stats=True,
                    track_best_outputs=True,
                    use_merge=self._policy.use_merge,
                    seed=self._policy.random_seed,
                    failure_score=0.0,
                    perfect_score=1.0,
                )

                optimized_program = gepa.compile(
                    program,
                    trainset=dataset.train,
                    valset=dataset.validation,
                )

            detailed_results = getattr(optimized_program, "detailed_results", None)
            best_val_score = None
            if detailed_results is not None:
                best_val_score = getattr(detailed_results, "best_val_score", None)
            metric_summary = metric.stats.summary()
            lever_runs.append(
                LeverRun(
                    config=config,
                    optimized_program=optimized_program,
                    metric_summary=metric_summary,
                    best_validation_score=best_val_score,
                    detailed_results=detailed_results,
                )
            )

        best_run = self._select_best_run(lever_runs)
        if best_run is None:
            raise RuntimeError("Prompt optimization produced no viable candidates")

        optimized_program = best_run.optimized_program
        detailed_results = best_run.detailed_results
        best_val_score = best_run.best_validation_score
        metric_summary = best_run.metric_summary

        optimization_report = {
            "auto_budget": self._policy.optimization_budget,
            "train_examples": len(dataset.train),
            "validation_examples": len(dataset.validation),
            "metric": metric_summary,
            "best_validation_score": best_val_score,
            "selected_config": {
                "few_shot_k": best_run.config.few_shot_k,
                "constraint_variant": best_run.config.constraint_variant,
                "temperature": best_run.config.temperature,
            },
            "lever_trials": [
                {
                    "few_shot_k": run.config.few_shot_k,
                    "constraint_variant": run.config.constraint_variant,
                    "temperature": run.config.temperature,
                    "best_validation_score": run.best_validation_score,
                    "metric": run.metric_summary,
                }
                for run in lever_runs
            ],
        }

        deployed_variant: Optional[str] = None
        deployed_template: Optional[Path] = None
        if deploy and self._policy.deploy_immediately:
            deployed_variant, deployed_template = self._deploy(
                prompt_key=prompt_key,
                program=optimized_program,
                report=optimization_report,
            )

        return OptimizationResult(
            optimized_program=optimized_program,
            optimization_report=optimization_report,
            deployed_variant=deployed_variant,
            deployed_template=deployed_template,
        )

    def _deploy(
        self,
        *,
        prompt_key: str,
        program: TaxonomyExtractor,
        report: Dict[str, Any],
    ) -> Tuple[str, Path]:
        variant, template_path = deploy_optimized_variant(
            prompt_key=prompt_key,
            program=program,
            optimization_report=report,
            llm_settings=self._llm_settings,
            backup_before_deployment=self._policy.backup_before_deployment,
            activate=True,
        )
        return variant, template_path

    def _build_target_lm(self, temperature: float) -> dspy.LM:
        profiles = self._llm_settings.profiles
        default_profile = self._llm_settings.default_profile
        if default_profile not in profiles:
            available = ", ".join(sorted(profiles.keys())) or "<none>"
            raise KeyError(
                f"LLM profile '{default_profile}' is not configured. Available profiles: {available}"
            )
        profile = profiles[default_profile]
        model_identifier = f"{profile.provider}/{profile.model}"
        return dspy.LM(
            model=model_identifier,
            temperature=temperature,
            max_tokens=self._llm_settings.token_budget,
            num_retries=self._llm_settings.retry_attempts,
        )

    def _build_reflection_lm(self) -> dspy.LM:
        return dspy.LM(
            model=self._reflection_model,
            temperature=1.0,
            max_tokens=min(self._llm_settings.token_budget * 2, 8192),
            num_retries=self._llm_settings.retry_attempts,
        )

    def _default_reflection_model(self) -> str:
        profile = self._llm_settings.profiles[self._llm_settings.default_profile]
        return f"{profile.provider}/{profile.model}"

    def _generate_lever_configs(self, train_size: int) -> List[LeverConfig]:
        """Enumerate lever combinations based on policy flags."""

        constrained_variants = self._resolve_constraint_variants()
        few_shot_values = self._resolve_few_shot_values(train_size)
        temperature_values = self._resolve_temperature_values()

        lever_configs: List[LeverConfig] = []
        seen: set[LeverConfig] = set()
        for few_shot_k, constraint_variant, temperature in itertools.product(
            few_shot_values, constrained_variants, temperature_values
        ):
            config = LeverConfig(
                few_shot_k=few_shot_k,
                constraint_variant=constraint_variant,
                temperature=temperature,
            )
            if config not in seen:
                lever_configs.append(config)
                seen.add(config)
        return lever_configs

    def _resolve_few_shot_values(self, train_size: int) -> Sequence[int]:
        default_k = max(0, min(train_size, self._policy.default_few_shot_k))
        candidates: List[int] = [default_k]
        if self._policy.explore_all_few_shot_k:
            if self._policy.few_shot_k_options:
                candidates.extend(self._policy.few_shot_k_options)
            else:
                candidates.extend([0, default_k + 2])
        values: List[int] = []
        for value in candidates:
            clamped = max(0, min(train_size, int(value)))
            if clamped not in values:
                values.append(clamped)
        if not values:
            values.append(default_k)
        return values

    def _resolve_constraint_variants(self) -> Sequence[str]:
        available = set(TaxonomyExtractor.available_constraint_variants())
        default_variant = (
            self._policy.constraint_variant
            if self._policy.constraint_variant in available
            else "baseline"
        )
        candidates: List[str] = [default_variant]
        if self._policy.explore_constraint_variants:
            if self._policy.constraint_variants:
                candidates.extend(self._policy.constraint_variants)
            else:
                candidates.extend(sorted(available))
        normalized: List[str] = []
        for variant in candidates:
            candidate = str(variant).strip()
            if candidate and candidate in available and candidate not in normalized:
                normalized.append(candidate)
        if not normalized:
            normalized.append("baseline")
        return normalized

    def _resolve_temperature_values(self) -> Sequence[float]:
        default_temp = max(0.0, float(self._llm_settings.temperature))
        candidates: List[float] = [default_temp]
        if self._policy.explore_temperature_variants:
            if self._policy.temperature_variants:
                candidates.extend(self._policy.temperature_variants)
            else:
                candidates.extend([0.2])
        values: List[float] = []
        for value in candidates:
            temperature = round(max(0.0, float(value)), 3)
            if temperature not in values:
                values.append(temperature)
        if not values:
            values.append(default_temp)
        return values

    @staticmethod
    def _select_best_run(runs: Sequence[LeverRun]) -> Optional[LeverRun]:
        """Choose the lever run with the highest validation score."""

        best_run: Optional[LeverRun] = None
        best_score = float("-inf")
        for run in runs:
            score = run.best_validation_score if run.best_validation_score is not None else 0.0
            if best_run is None or score > best_score:
                best_run = run
                best_score = score
        return best_run


__all__ = ["OneTimeGEPAOptimizer", "OptimizationResult"]
