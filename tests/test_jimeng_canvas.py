"""即梦画布适配层：三视图同步、i2i 引用与失败熔断。

全部通过替身（monkeypatch ``_run`` / ``node_resources``）驱动，不联网、不耗积分。
"""
from __future__ import annotations

import json

import pytest

from core import jimeng_canvas as jc


@pytest.fixture
def state_file(tmp_path, monkeypatch):
    """把画布状态重定向到临时文件，避免污染真实 data/ 目录。"""
    target = tmp_path / "jimeng_canvas.json"
    monkeypatch.setattr(jc, "_state_path", lambda: target)
    return target


@pytest.fixture(autouse=True)
def cli_present(monkeypatch, tmp_path):
    binary = tmp_path / "dreamina-canvas.exe"
    binary.write_bytes(b"")
    monkeypatch.setenv(jc._CLI_ENV, str(binary))


def _views():
    return {"front": b"front-bytes", "side": b"side-bytes", "back": b"back-bytes"}


def test_node_id_follows_server_format():
    for _ in range(20):
        node_id = jc._new_node_id()
        assert node_id.startswith("node_")
        suffix = node_id[5:]
        assert len(suffix) == 10
        # Crockford Base32 不含 i/l/o/u
        assert all(ch in jc._NODE_ID_ALPHABET for ch in suffix)


def test_ratio_mapping_covers_three_tiers():
    assert jc.ratio_for_size("768x1344") == "9:16"
    assert jc.ratio_for_size("1344x768") == "16:9"
    assert jc.ratio_for_size("1024x1024") == "1:1"
    # 未知档位回退竖屏（人物类占多数）
    assert jc.ratio_for_size("") == "9:16"


def test_i2i_block_round_trip(state_file):
    assert jc.i2i_usable() is True
    jc.note_i2i_blocked("resource_failed:20100")
    assert jc.i2i_usable() is False
    assert json.loads(state_file.read_text(encoding="utf-8"))["i2i_last_error"] == "resource_failed:20100"
    jc.clear_i2i_block()
    assert jc.i2i_usable() is True


def test_i2i_can_be_disabled_by_env(state_file, monkeypatch):
    monkeypatch.setenv("JIMENG_I2I_ENABLED", "false")
    assert jc.i2i_enabled() is False
    assert jc.i2i_usable() is False


def test_sync_uploads_once_then_reuses(state_file, monkeypatch):
    calls: list[list[str]] = []
    uploaded = {"n": 0}

    def fake_run(args, *, timeout):
        calls.append(list(args))
        if args[:2] == ["canvas", "ls"]:
            return {"ok": True, "data": {"items": [{"projectId": jc.load_project_id()}]}}
        if args[:2] == ["resource", "upload"]:
            uploaded["n"] += 1
            return {"ok": True, "data": {"resourceId": f"res-{uploaded['n']}"}}
        if args[:2] == ["node", "create"] and args[2] == "element":
            return {"ok": True, "data": {"node": {"nodeId": args[args.index("--node-id") + 1]}}}
        return {"ok": True, "data": {}}

    monkeypatch.setattr(jc, "_run", fake_run)

    first = jc.sync_persona_reference("p1", _views())
    assert first["ok"] is True
    assert sorted(first["changed"]) == ["back", "front", "side"]
    assert first["main_view"] == "front"
    assert uploaded["n"] == 3

    second = jc.sync_persona_reference("p1", _views())
    assert second["ok"] is True
    assert second["reused"] is True
    assert second["element_node_id"] == first["element_node_id"]
    # 内容未变 → 一次上传都不该发生
    assert uploaded["n"] == 3


def test_sync_only_reuploads_changed_view(state_file, monkeypatch):
    uploaded: list[str] = []

    def fake_run(args, *, timeout):
        if args[:2] == ["canvas", "ls"]:
            return {"ok": True, "data": {"items": [{"projectId": jc.load_project_id()}]}}
        if args[:2] == ["resource", "upload"]:
            name = args[args.index("--name") + 1]
            uploaded.append(name)
            return {"ok": True, "data": {"resourceId": f"res-{len(uploaded)}"}}
        if args[:2] == ["node", "create"]:
            return {"ok": True, "data": {"node": {"nodeId": args[args.index("--node-id") + 1]}}}
        if args[:2] == ["node", "edit"]:
            return {"ok": True, "data": {}}
        return {"ok": True, "data": {}}

    monkeypatch.setattr(jc, "_run", fake_run)
    original = jc.sync_persona_reference("p1", _views())
    uploaded.clear()

    changed_views = _views()
    changed_views["side"] = b"side-bytes-v2"
    result = jc.sync_persona_reference("p1", changed_views)

    assert result["changed"] == ["side"]
    assert uploaded == ["p1-side"]
    # 已经建过节点 → 复用同一 Element 节点更新，不再新建
    assert result["element_node_id"] == original["element_node_id"]


def test_clear_persona_reference_drops_record(state_file, monkeypatch):
    monkeypatch.setattr(jc, "_run", lambda args, *, timeout: {"ok": True, "data": {"items": [{"projectId": jc.load_project_id()}]}})
    # 手工写入参考记录，模拟已同步
    state = jc._load_state()
    state.setdefault("references", {})["p1"] = {"element_node_id": "node_aaaa", "views": {}}
    jc._save_state(state)
    assert jc.persona_reference("p1") is not None
    jc.clear_persona_reference("p1")
    assert jc.persona_reference("p1") is None


def _stub_generate_run(*, resource_status: str, resource_error: str = ""):
    def fake_run(args, *, timeout):
        if args[:3] == ["node", "create", "image"]:
            return {"ok": True, "data": {"node": {"nodeId": args[args.index("--node-id") + 1]}}}
        if args[:2] == ["operation", "wait"]:
            return {"ok": True, "data": {"state": "success"}}
        return {"ok": True, "data": {}}

    def fake_resources(*, project_id, node_id, timeout=60):
        return [{
            "resourceId": "res-out",
            "type": "image",
            "status": resource_status,
            "submitId": "sub-1",
            "errorCode": resource_error,
        }]

    return fake_run, fake_resources


def test_generate_surfaces_failed_resource_code(state_file, monkeypatch):
    """失败资源必须如实上报 errorCode —— 熔断全靠它。"""
    fake_run, fake_resources = _stub_generate_run(resource_status="failed", resource_error="20100")
    monkeypatch.setattr(jc, "_run", fake_run)
    monkeypatch.setattr(jc, "node_resources", fake_resources)

    result = jc.generate_image(
        prompt="测试", project_id="p", credit_ceiling=16, reference_node_id="node_ref",
    )
    assert result["status"] == "failed"
    assert result["error_code"] == "resource_failed:20100"


def test_generate_reports_ok_only_for_successful_resource(state_file, monkeypatch):
    fake_run, fake_resources = _stub_generate_run(resource_status="success")
    monkeypatch.setattr(jc, "_run", fake_run)
    monkeypatch.setattr(jc, "node_resources", fake_resources)

    result = jc.generate_image(prompt="测试", project_id="p", credit_ceiling=16)
    assert result["status"] == "ok"
    assert result["resource_id"] == "res-out"


def test_generate_maps_credit_ceiling_rejection_without_charging(state_file, monkeypatch):
    def fake_run(args, *, timeout):
        return {
            "ok": False,
            "error_code": "cli.generation_credit_ceiling_too_low",
            "detail": "ceiling below estimate",
        }

    monkeypatch.setattr(jc, "_run", fake_run)
    result = jc.generate_image(prompt="测试", project_id="p", credit_ceiling=0)
    assert result["status"] == "credit_exceeded"


def test_generate_uses_title_for_i2i(state_file, monkeypatch):
    """i2i 必须带 --title，否则 CLI 以 CLI_INPUT_REQUIRED 拒绝。"""
    seen: list[list[str]] = []
    fake_run, fake_resources = _stub_generate_run(resource_status="success")

    def spy(args, *, timeout):
        seen.append(list(args))
        return fake_run(args, timeout=timeout)

    monkeypatch.setattr(jc, "_run", spy)
    monkeypatch.setattr(jc, "node_resources", fake_resources)

    jc.generate_image(
        prompt="窗边自拍", project_id="p", credit_ceiling=16, reference_node_id="node_ref",
    )
    create_args = seen[0]
    assert "--title" in create_args
    assert "--mode" in create_args and create_args[create_args.index("--mode") + 1] == "i2i"
    assert "--ref" in create_args and create_args[create_args.index("--ref") + 1] == "node:node_ref"
    # 提交与等待必须分开：--run --wait 组合在 i2i 下会被服务端拒绝
    assert "--wait" not in create_args


# ── provider 降级：i2i 被拒时不烧第二遍、但仍要出图 ────────────────────────


@pytest.fixture
def provider(monkeypatch, state_file):
    """装配一个 provider，隔离掉画布与下载的真实副作用。"""
    from core.image_service import JimengCanvasImageGenerationProvider

    monkeypatch.setattr(jc, "load_project_id", lambda: "proj-1")
    monkeypatch.setattr(jc, "ensure_canvas", lambda pid, **kw: {"ok": True, "project_id": pid})
    monkeypatch.setattr(jc, "persona_reference", lambda pid: {"element_node_id": "node_ref"})
    monkeypatch.setattr(
        jc, "download_resource",
        lambda rid, *, project_id, output, timeout=180: {
            "status": "ok", "path": output, "image_bytes": b"png-bytes",
        },
    )
    return JimengCanvasImageGenerationProvider()


def _stub_generate(monkeypatch, outcomes):
    """按调用顺序返回预设结果，并记录每次的 reference_node_id。"""
    calls: list[str] = []

    def fake_generate(**kwargs):
        calls.append(str(kwargs.get("reference_node_id") or ""))
        return outcomes[min(len(calls) - 1, len(outcomes) - 1)]

    monkeypatch.setattr(jc, "generate_image", fake_generate)
    return calls


def test_provider_falls_back_to_txt2img_and_blocks_i2i(provider, monkeypatch):
    calls = _stub_generate(monkeypatch, [
        {"status": "failed", "error_code": "resource_failed:20100"},
        {"status": "ok", "resource_id": "res-1", "node_id": "node_out"},
    ])
    result = provider.generate(
        prompt="窗边自拍", request_id="r1", owner_id="master", metadata={"size": "768x1344"},
    )

    assert result.status == "ok"
    assert calls == ["node_ref", ""]           # 先试 i2i，失败后降级 t2i
    assert result.metadata["mode"] == "t2i"
    # 失败即熔断，但三视图参考本身要保留，账号恢复后还能用
    assert jc.i2i_usable() is False
    assert jc.persona_reference("p")["element_node_id"] == "node_ref"


def test_provider_skips_i2i_while_blocked(provider, monkeypatch):
    jc.note_i2i_blocked("resource_failed:20100")
    calls = _stub_generate(monkeypatch, [{"status": "ok", "resource_id": "res-2", "node_id": "n"}])

    result = provider.generate(
        prompt="窗边自拍", request_id="r2", owner_id="master", metadata={},
    )
    assert result.status == "ok"
    assert calls == [""]                        # 熔断期内直接文生图，一次 i2i 都不试
    assert result.metadata["mode"] == "t2i"


def test_provider_uses_i2i_when_healthy(provider, monkeypatch):
    calls = _stub_generate(monkeypatch, [{"status": "ok", "resource_id": "res-3", "node_id": "n"}])
    result = provider.generate(
        prompt="窗边自拍", request_id="r3", owner_id="master", metadata={},
    )
    assert calls == ["node_ref"]
    assert result.metadata["mode"] == "i2i"


def test_provider_does_not_retry_on_credit_exceeded(provider, monkeypatch):
    """额度未授权不该降级重试——重试同样过不了闸门，只是白跑。"""
    calls = _stub_generate(monkeypatch, [{"status": "credit_exceeded", "error_code": "x"}])
    result = provider.generate(
        prompt="窗边自拍", request_id="r4", owner_id="master", metadata={},
    )
    assert result.status == "credit_exceeded"
    assert calls == ["node_ref"]
    assert jc.i2i_usable() is True               # 不是 i2i 的错，不该熔断


def test_provider_without_views_goes_txt2img(provider, monkeypatch):
    monkeypatch.setattr(jc, "persona_reference", lambda pid: None)
    calls = _stub_generate(monkeypatch, [{"status": "ok", "resource_id": "res-4", "node_id": "n"}])
    result = provider.generate(
        prompt="窗边自拍", request_id="r5", owner_id="master", metadata={},
    )
    assert calls == [""]                        # 没三视图 → 降级外貌描写
    assert result.metadata["mode"] == "t2i"
