"""Dataset loading utilities for one-time GEPA prompt optimization."""

from __future__ import annotations

import json
import math
import random
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence

import dspy


@dataclass(frozen=True)
class DatasetSplit:
    """Container holding deterministic train/validation splits."""

    train: List[dspy.Example]
    validation: List[dspy.Example]


class DatasetLoader:
    """Load taxonomy prompt optimization datasets with stratified splitting."""

    def __init__(
        self,
        dataset_path: Path,
        *,
        validation_ratio: float = 0.2,
        seed: int = 20250927,
    ) -> None:
        if not 0.0 < validation_ratio < 1.0:
            raise ValueError("validation_ratio must be in the interval (0, 1)")
        self._dataset_path = dataset_path
        self._validation_ratio = validation_ratio
        self._seed = seed

    def load(self) -> DatasetSplit:
        """Read dataset from disk, validate structure, and return DSPy examples."""

        raw_records = self._read_records()
        examples = [self._to_example(record) for record in raw_records]
        train, validation = self._split_examples(examples)
        return DatasetSplit(train=train, validation=validation)

    def _read_records(self) -> Sequence[dict]:
        if not self._dataset_path.exists():
            raise FileNotFoundError(f"Optimization dataset not found: {self._dataset_path}")
        with self._dataset_path.open("r", encoding="utf-8") as handle:
            try:
                data = json.load(handle)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON in optimization dataset '{self._dataset_path}': {exc}"
                ) from exc
        if not isinstance(data, list) or not all(isinstance(entry, dict) for entry in data):
            raise ValueError("Optimization dataset must be a list of objects")
        if not data:
            raise ValueError("Optimization dataset is empty")
        return data

    def _to_example(self, record: dict) -> dspy.Example:
        source_text = self._first_non_empty(
            record,
            keys=("source_text", "text", "input", "document"),
        )
        if not source_text:
            raise ValueError("Dataset entry missing source text")

        gold_labels = record.get("gold_labels") or record.get("expected") or record.get("labels")
        if isinstance(gold_labels, (str, bytes)):
            raise ValueError(
                "Dataset entry gold labels must be a collection, not a raw string/bytes value"
            )
        if isinstance(gold_labels, dict) or not isinstance(gold_labels, Collection):
            raise ValueError("Dataset entry missing gold label collection")
        normalized_labels: List[str] = []
        for label in gold_labels:
            if label is None:
                continue
            if isinstance(label, float) and math.isnan(label):
                continue
            label_str = str(label).strip()
            if label_str:
                normalized_labels.append(label_str)
        if not normalized_labels:
            raise ValueError("Dataset entry must contain at least one gold label")

        institution = self._first_non_empty(
            record,
            keys=("institution", "campus", "organization"),
            default="Unknown Institution",
        )
        if "level" in record and record["level"] is not None:
            level_value = record["level"]
        elif "hierarchy_level" in record and record["hierarchy_level"] is not None:
            level_value = record["hierarchy_level"]
        else:
            level_value = 0
        try:
            level_int = int(level_value)
        except (TypeError, ValueError):
            level_int = 0

        example = dspy.Example(
            institution=str(institution),
            level=level_int,
            source_text=str(source_text),
            gold_labels=normalized_labels,
        ).with_inputs("institution", "level", "source_text")
        return example

    def _split_examples(self, examples: List[dspy.Example]) -> tuple[List[dspy.Example], List[dspy.Example]]:
        buckets: dict[int, List[dspy.Example]] = {}
        for example in examples:
            level = getattr(example, "level", 0)
            buckets.setdefault(int(level), []).append(example)

        rng = random.Random(self._seed)
        train: List[dspy.Example] = []
        validation: List[dspy.Example] = []
        for level, bucket in buckets.items():
            rng.shuffle(bucket)
            bucket_size = len(bucket)
            if bucket_size == 1:
                train.append(bucket[0])
                continue
            split_index = max(1, int(bucket_size * (1.0 - self._validation_ratio)))
            if split_index >= bucket_size:
                split_index = bucket_size - 1
            if split_index <= 0:
                split_index = 1
            train.extend(bucket[:split_index])
            validation.extend(bucket[split_index:])
        rng.shuffle(train)
        rng.shuffle(validation)
        if validation == [] and train:
            validation.append(train.pop())
        if not train or not validation:
            raise ValueError("Dataset split produced empty train or validation set; adjust ratio")
        return train, validation

    @staticmethod
    def _first_non_empty(record: dict, *, keys: Sequence[str], default: str | None = None) -> str | None:
        for key in keys:
            value = record.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return default


__all__ = ["DatasetLoader", "DatasetSplit"]
