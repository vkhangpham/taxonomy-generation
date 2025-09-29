"""Entrypoint helpers for running one-time GEPA prompt optimization."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

from ..config.settings import Settings
from .one_time_optimizer import OneTimeGEPAOptimizer, OptimizationResult


def run_one_time_optimization(
    *,
    prompt_key: str,
    dataset_path: Path,
    deploy: bool = True,
    environment: str = "development",
    settings: Optional[Settings] = None,
) -> OptimizationResult:
    """Run the one-time optimization workflow using configured policies."""

    active_settings = settings or Settings(environment=environment, create_dirs=False)
    policy = active_settings.policies.prompt_optimization
    llm_settings = active_settings.policies.llm

    optimizer = OneTimeGEPAOptimizer(
        policy=policy,
        llm_settings=llm_settings,
        reflection_model=policy.reflection_model,
    )
    return optimizer.optimize(
        prompt_key=prompt_key,
        dataset_path=dataset_path,
        deploy=deploy,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one-time GEPA prompt optimization")
    parser.add_argument("--prompt-key", required=True, help="Prompt registry key to optimize")
    parser.add_argument("--dataset", required=True, help="Path to training dataset JSON")
    parser.add_argument(
        "--environment",
        default="development",
        help="Configuration environment to load (default: development)",
    )
    parser.add_argument(
        "--no-deploy",
        dest="deploy",
        action="store_false",
        help="Run optimization without promoting the new variant",
    )
    parser.set_defaults(deploy=True)
    return parser


def main(argv: Optional[list[str]] = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    result = run_one_time_optimization(
        prompt_key=args.prompt_key,
        dataset_path=Path(args.dataset),
        deploy=args.deploy,
        environment=args.environment,
    )
    summary = {
        "deployed_variant": result.deployed_variant,
        "deployed_template": str(result.deployed_template) if result.deployed_template else None,
        "report": result.optimization_report,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
