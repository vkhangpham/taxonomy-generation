import json
from pathlib import Path
from unittest import mock

import pytest

from taxonomy.config.policies import ObservabilityPolicy
from taxonomy.observability import ObservabilityContext, stable_hash
from taxonomy.orchestration.manifest import RunManifest


@pytest.mark.parametrize(
    ("context_policy_config", "manifest_policy_config", "expected"),
    [
        ({"audit_trail_generation": True}, None, True),
        (None, {"audit_trail_generation": True}, True),
        ({"audit_trail_generation": False}, {"audit_trail_generation": True}, False),
        ({"audit_trail_generation": False}, None, False),
        (None, None, True),
    ],
)
def test_ensure_observability_manifest_respects_policy(
    context_policy_config, manifest_policy_config, expected
) -> None:
    context_policy = (
        ObservabilityPolicy(**context_policy_config)
        if context_policy_config is not None
        else None
    )
    manifest_policy = (
        ObservabilityPolicy(**manifest_policy_config)
        if manifest_policy_config is not None
        else None
    )

    manifest = RunManifest("run", policy=manifest_policy)
    context = ObservabilityContext(run_id="run", policy=context_policy)
    manifest.attach_observability(context)

    result = manifest._ensure_observability_manifest()
    assert (result is not None) is expected


def test_finalize_integrates_observability_payload(tmp_path, caplog) -> None:
    policy = ObservabilityPolicy(audit_trail_generation=True)
    manifest = RunManifest("obs-run", policy=policy)
    context = ObservabilityContext(run_id="obs-run", policy=policy)
    manifest.attach_observability(context)
    manifest._data.setdefault("configuration", {}).setdefault("paths", {})[
        "metadata_dir"
    ] = str(tmp_path)

    context.register_prompt_version("prompt-A", "v1")
    context.register_seed("valid_seed", 7)
    context._seeds["invalid.seed"] = "oops"  # type: ignore[index]
    with context.phase("S1") as phase:
        phase.increment("records_in", 1)

    with mock.patch.object(
        manifest,
        "_ensure_observability_manifest",
        wraps=manifest._ensure_observability_manifest,
    ) as ensure_spy:
        with caplog.at_level("WARNING"):
            result = manifest.finalize()

    ensure_spy.assert_called()

    observability_meta = result["observability"]
    assert set(observability_meta) == {"path", "checksum"}
    artifact_entries = {entry["kind"]: entry for entry in result["artifacts"]}
    assert "observability" in artifact_entries

    observability_path = Path(observability_meta["path"])
    assert observability_path.exists()
    assert artifact_entries["observability"]["path"] == str(observability_path.resolve())

    exported_payload = json.loads(observability_path.read_text(encoding="utf-8"))
    assert exported_payload["counters"]["S1"]["records_in"] == 1
    assert exported_payload["prompt_versions"]["prompt-A"] == "v1"
    assert exported_payload["seeds"]["valid_seed"] == 7
    assert "invalid.seed" not in exported_payload["seeds"]

    assert observability_meta["checksum"] == stable_hash(exported_payload)

    assert result["prompt_versions"]["prompt-A"] == "v1"
    assert result["configuration"]["seeds"]["valid_seed"] == 7
    assert "invalid.seed" not in result["configuration"]["seeds"]
    assert any(
        "Skipping invalid observability seed" in record.message for record in caplog.records
    )


def test_finalize_skips_observability_when_disabled(tmp_path) -> None:
    policy = ObservabilityPolicy(audit_trail_generation=False)
    manifest = RunManifest("disabled-run", policy=policy)
    context = ObservabilityContext(run_id="disabled-run", policy=policy)
    manifest.attach_observability(context)
    manifest._data["prompt_versions"] = {"baseline": "v0"}
    manifest._data.setdefault("configuration", {}).setdefault("paths", {})[
        "metadata_dir"
    ] = str(tmp_path)
    manifest._data["configuration"].setdefault("seeds", {})["baseline"] = 1

    context.register_prompt_version("context-prompt", "v1")
    context.register_seed("context-seed", 2)

    result = manifest.finalize()

    assert result["observability"] == {}
    assert result["prompt_versions"] == {"baseline": "v0"}
    assert result["configuration"]["seeds"] == {"baseline": 1}
    assert all(entry["kind"] != "observability" for entry in result["artifacts"])
    assert not list(Path(tmp_path).glob("*.observability.json"))


def test_collect_prompt_versions_prefers_manifest() -> None:
    manifest = RunManifest("run")
    manifest._observability = mock.Mock()
    registry = mock.Mock()
    payload = {"prompt-A": "v1"}
    fake_manifest = mock.Mock()
    fake_manifest.collect_prompt_versions.return_value = payload

    with mock.patch.object(manifest, "_ensure_observability_manifest", return_value=fake_manifest):
        manifest.collect_prompt_versions(registry)

    fake_manifest.collect_prompt_versions.assert_called_once_with(
        registry,
        prompt_keys=None,
    )
    manifest._observability.register_prompt_version.assert_called_once_with("prompt-A", "v1")
    assert manifest._data["prompt_versions"]["prompt-A"] == "v1"


def test_collect_prompt_versions_uses_registry_fallback() -> None:
    manifest = RunManifest("run")
    manifest._observability = mock.Mock()
    registry = mock.Mock()
    registry.active_version.side_effect = lambda key: {"prompt-A": "v1", "prompt-B": "v2"}[key]

    with mock.patch.object(manifest, "_ensure_observability_manifest", return_value=None), mock.patch.object(
        manifest,
        "_resolve_prompt_keys",
        return_value=["prompt-A", "prompt-B"],
    ):
        manifest.collect_prompt_versions(registry)

    registry.active_version.assert_any_call("prompt-A")
    registry.active_version.assert_any_call("prompt-B")
    assert manifest._observability.register_prompt_version.call_count == 2
    assert manifest._data["prompt_versions"] == {"prompt-A": "v1", "prompt-B": "v2"}
