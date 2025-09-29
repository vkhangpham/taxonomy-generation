"""One-time GEPA optimization orchestrator for taxonomy prompts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

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

        validator = JSONValidator(schema_base_path=Path(self._llm_settings.registry.schema_root))
        metric = TaxonomyEvaluationMetric(
            validator=validator,
            schema_path="schemas/extraction.json",
            json_validity_threshold=self._policy.json_validity_threshold,
            schema_adherence_threshold=self._policy.schema_adherence_threshold,
        )

        program = TaxonomyExtractor(
            few_shot_examples=dataset.train,
            few_shot_k=self._policy.default_few_shot_k,
            constraint_variant=self._policy.constraint_variant,
            ordering_seed=self._policy.random_seed,
        )
        program.configure_examples(dataset.train)

        target_lm = self._build_target_lm()
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
        stats = getattr(metric, "stats", None)
        metric_summary = stats.summary() if stats is not None else {}

        optimization_report = {
            "auto_budget": self._policy.optimization_budget,
            "train_examples": len(dataset.train),
            "validation_examples": len(dataset.validation),
            "metric": metric_summary,
            "best_validation_score": best_val_score,
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

    def _build_target_lm(self) -> dspy.LM:
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
            temperature=self._llm_settings.temperature,
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


__all__ = ["OneTimeGEPAOptimizer", "OptimizationResult"]
