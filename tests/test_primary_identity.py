from __future__ import annotations

import json


def test_primary_identity_precedence_and_invalid_values(tmp_path):
    from core.primary_identity import PrimaryIdentityResolver

    local_path = tmp_path / "runtime_config.json"
    local_path.write_text(
        json.dumps({
            "schema_version": 1,
            "revision": 3,
            "values": {"primary_user_id": 30003},
        }),
        encoding="utf-8",
    )
    resolver = PrimaryIdentityResolver(local_config_path=local_path)

    selected = resolver.resolve(
        environ={
            "AERIE_PRIMARY_USER_ID": "10001",
            "SELF_QQ": "20002",
        },
        settings={"qq": {"self_qq": 40004}},
    )
    assert selected.user_id == 10001
    assert selected.source == "env:AERIE_PRIMARY_USER_ID"

    selected = resolver.resolve(
        environ={"AERIE_PRIMARY_USER_ID": "0", "SELF_QQ": "20002"},
        settings={"qq": {"self_qq": 40004}},
    )
    assert selected.user_id == 20002
    assert selected.source == "env:SELF_QQ"


def test_primary_identity_reads_runtime_service_before_local_file(tmp_path):
    from core.primary_identity import PrimaryIdentityResolver

    class RuntimeConfig:
        def get_effective(self, key):
            assert key == "primary_user_id"
            return {"effectiveValue": "22222", "source": "local"}

    local_path = tmp_path / "runtime_config.json"
    local_path.write_text(
        json.dumps({
            "schema_version": 1,
            "revision": 1,
            "values": {"primary_user_id": 33333},
        }),
        encoding="utf-8",
    )
    selected = PrimaryIdentityResolver(
        runtime_config_service=RuntimeConfig(),
        local_config_path=local_path,
    ).resolve(environ={}, settings={"qq": {"self_qq": 44444}})

    assert selected.user_id == 22222
    assert selected.source == "runtime_config:local"


def test_primary_identity_requires_versioned_local_config_and_never_returns_zero(tmp_path):
    from core.primary_identity import PrimaryIdentityResolver

    local_path = tmp_path / "runtime_config.json"
    local_path.write_text(
        json.dumps({"values": {"primary_user_id": 33333}}),
        encoding="utf-8",
    )
    resolver = PrimaryIdentityResolver(local_config_path=local_path)

    assert resolver.resolve(
        environ={},
        settings={"qq": {"self_qq": "44444"}},
    ).user_id == 44444
    assert resolver.resolve(
        environ={},
        settings={"qq": {"self_qq": 0}},
    ) is None


def test_primary_identity_can_read_snapshot_shape():
    from core.primary_identity import PrimaryIdentityResolver

    class RuntimeConfig:
        def snapshot(self):
            return {
                "revision": 9,
                "values": {
                    "primary_user_id": {
                        "effective_value": "55555",
                        "source": "persisted",
                    },
                },
            }

    selected = PrimaryIdentityResolver(
        runtime_config_service=RuntimeConfig(),
    ).resolve(environ={}, settings={})

    assert selected.user_id == 55555
    assert selected.source == "runtime_config:persisted"

