from datetime import datetime, timezone

from core.entitlements import EntitlementStore


def test_free_plan_and_usage_limit(tmp_path):
    store = EntitlementStore(tmp_path / "entitlement.json")
    snap = store.snapshot(datetime(2026, 9, 2, tzinfo=timezone.utc))
    assert snap["plan"] == "free"
    assert snap["limits"]["cloud_calls_month"] == 100
    assert "local_chat" in snap["features"]
    assert snap["pricing"]["monthly_software_cents"] == 0
    assert store.check(cloud_calls=100, now=datetime(2026, 9, 2, tzinfo=timezone.utc))["allowed"]
    assert not store.check(cloud_calls=101, now=datetime(2026, 9, 2, tzinfo=timezone.utc))["allowed"]


def test_trial_is_idempotent_and_metered(tmp_path):
    store = EntitlementStore(tmp_path / "entitlement.json")
    now = datetime(2026, 9, 2, tzinfo=timezone.utc)
    first = store.activate_trial(now=now)
    second = store.activate_trial(now=now)
    assert first["plan"] == second["plan"] == "trial"
    assert first["trial_ends_at"] == second["trial_ends_at"]
    store.record_usage(cloud_calls=2, cloud_tokens=50, now=now)
    usage = store.snapshot(now)["usage"]
    assert usage == {"cloud_calls": 2, "cloud_tokens": 50}


def test_default_path_uses_runtime_data_dir_when_env_is_empty(tmp_path, monkeypatch):
    monkeypatch.delenv("AERIE_ENTITLEMENT_PATH", raising=False)
    monkeypatch.setenv("AERIE_DATA_DIR", str(tmp_path / "runtime-data"))
    store = EntitlementStore()
    assert store.path == tmp_path / "runtime-data" / "entitlement.json"
