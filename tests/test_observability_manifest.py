from taxonomy.observability.context import ObservabilityContext, ObservabilitySnapshot
from taxonomy.observability.manifest import ObservabilityManifest


def _make_snapshot(
    *,
    counters: dict[str, dict[str, object]],
    thresholds: dict[str, object] | None = None,
) -> ObservabilitySnapshot:
    return ObservabilitySnapshot(
        counters=counters,
        quarantine={},
        evidence={},
        operations=(),
        performance={},
        prompt_versions={},
        thresholds=thresholds or {},
        seeds={},
        checksum="checksum",
        snapshot_timestamp=0.0,
        captured_at="1970-01-01T00:00:00Z",
    )


def test_aggregate_counters_coerces_invalid_values() -> None:
    context = ObservabilityContext(run_id="aggregate")
    manifest = ObservabilityManifest(context=context)

    snapshot = _make_snapshot(
        counters={
            "S1": {
                "int_value": 3,
                "none_value": None,
                "numeric_string": "7",
                "float_value": 2.8,
                "bad_string": "not-a-number",
                "labeled_metric": {
                    "ok": "5",
                    "float": 3.4,
                    "none": None,
                    "invalid": "oops",
                },
            }
        }
    )

    aggregated = manifest.aggregate_counters(snapshot)
    counters = aggregated["S1"]

    # None and other invalid inputs should default to 0 so manifests never raise.
    assert counters["none_value"] == 0
    assert counters["bad_string"] == 0

    # Numeric strings and floats are coerced to integers to stabilise payload types.
    assert counters["numeric_string"] == 7
    assert counters["float_value"] == 2

    labeled = counters["labeled_metric"]
    # Nested label values follow the same coercion and fallback policy.
    assert labeled["ok"] == 5
    assert labeled["float"] == 3
    assert labeled["none"] == 0
    assert labeled["invalid"] == 0


def test_build_payload_merges_thresholds_with_conflicts_and_empty_segments() -> None:
    context = ObservabilityContext(run_id="thresholds")
    manifest = ObservabilityManifest(context=context)

    snapshot = _make_snapshot(
        counters={"S1": {"ok": 1}},
        thresholds={
            "S1.limit": 5,
            "S1.limit.min": 1,
            "S1..anomaly": 3,
            "S2.threshold": 4,
            "S2.threshold.min": 2,
            ".global": 10,
            "S3": {"raw": True},
        },
    )

    payload = manifest.build_payload(snapshot)
    thresholds = payload["thresholds"]

    # Longer dotted keys replace earlier scalar values so nested structures always win.
    assert thresholds["S1"]["limit"] == {"min": 1}
    assert thresholds["S2"]["threshold"] == {"min": 2}

    # Empty segments produce explicit empty-string keys to preserve the original path.
    assert thresholds["S1"][""]["anomaly"] == 3
    assert thresholds[""]["global"] == 10

    # Keys without dots remain as-is, ensuring top-level overrides persist.
    assert thresholds["S3"] == {"raw": True}
