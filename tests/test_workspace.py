"""工作区管理器 + 路径提取 + 人格化翻译层的单元测试。

纯 mock / 临时目录,不触碰真实 D 盘目录、不调真实 LLM、不触发 os.startfile。
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from core.computer_control import (
    AccessPolicy,
    ControlAction,
    ControlMode,
    PolicyEntryType,
)
from core.pipeline import _extract_paths
from core.work_persona import PersonaTranslator
from core.workspace import WorkspaceManager, _TEMP_ROOTS_FILE


class _FakeLLM:
    """按预设文本回复的假 LLM。"""

    def __init__(self, text: str, *, boom: bool = False):
        self._text = text
        self._boom = boom
        self.prompt_seen: str | None = None

    async def chat(self, messages, **kwargs):
        if self._boom:
            raise RuntimeError("llm boom")
        self.prompt_seen = str(messages[0]["content"])
        return type("R", (), {"text": self._text})()


@pytest.fixture
def ws(tmp_path, monkeypatch):
    # 隔离持久化文件,避免测试污染真实 data/workspace_roots.json
    monkeypatch.setattr("core.workspace._TEMP_ROOTS_FILE", tmp_path / "workspace_roots.json")
    return WorkspaceManager(preset_roots=[str(tmp_path / "root_a"), str(tmp_path / "root_b")])


@pytest.fixture
def root_a(tmp_path):
    d = tmp_path / "root_a"
    d.mkdir(parents=True, exist_ok=True)
    (d / "doc.pdf").write_bytes(b"pdf-bytes")
    from PIL import Image

    img = Image.new("RGB", (64, 64), (200, 120, 80))
    img.save(d / "pic.png", format="PNG")
    (d / "sub").mkdir(exist_ok=True)
    (d / "sub" / "inner.txt").write_text("hello")
    return d


# --------------------------------------------------------------------- 路径提取


@pytest.mark.parametrize(
    "text,expected",
    [
        ("帮我整理 D:\\T08171634 文件夹", ["D:\\T08171634"]),
        ("把 E:\\Downloads 里的文件归类", ["E:\\Downloads"]),
        ("整理 D:\\T08171634,顺便删重复", ["D:\\T08171634"]),
        ("今天好累呀", []),
        ("", []),
        ("把 D:\\A 和 E:\\B 都整理一下", ["D:\\A", "E:\\B"]),
    ],
)
def test_extract_paths(text, expected):
    assert _extract_paths(text) == expected


def test_extract_paths_dedup():
    assert _extract_paths("整理 D:\\X 再整理 D:\\X") == ["D:\\X"]


# --------------------------------------------------------------------- 工作区根目录


def test_roots_from_preset(ws, tmp_path):
    roots = ws.roots()
    assert len(roots) == 2
    assert str(tmp_path / "root_a") in roots


def test_add_temp_root(ws, tmp_path):
    assert ws.add_temp_root(str(tmp_path / "temp_x")) is True
    assert ws.add_temp_root(str(tmp_path / "temp_x")) is False  # 去重
    assert str(tmp_path / "temp_x") in ws.roots()


def test_remove_temp_root(ws, tmp_path):
    # 自定义目录可移除
    ws.add_temp_root(str(tmp_path / "temp_x"))
    assert ws.remove_temp_root(str(tmp_path / "temp_x")) is True
    assert str(tmp_path / "temp_x") not in ws.roots()
    # 预设根不可移除
    assert ws.remove_temp_root(str(tmp_path / "root_a")) is False
    assert str(tmp_path / "root_a") in ws.roots()
    # 未注册的目录移除返回 False
    assert ws.remove_temp_root(str(tmp_path / "nope")) is False


def test_roots_info_source(ws, tmp_path):
    ws.add_temp_root(str(tmp_path / "temp_x"))
    info = ws.roots_info()
    by_path = {r["path"]: r["source"] for r in info}
    assert by_path[str(tmp_path / "root_a")] == "preset"
    assert by_path[str(tmp_path / "temp_x")] == "custom"


def test_temp_roots_persist_across_reload(tmp_path, monkeypatch):
    """自定义目录持久化:重建实例后仍保留;预设根不持久化(来自配置)。"""
    monkeypatch.setattr("core.workspace._TEMP_ROOTS_FILE", tmp_path / "ws.json")
    ws1 = WorkspaceManager(preset_roots=[str(tmp_path / "root_a")])
    ws1.add_temp_root(str(tmp_path / "temp_x"))

    ws2 = WorkspaceManager(preset_roots=[str(tmp_path / "root_a")])
    assert str(tmp_path / "temp_x") in ws2.roots()  # 自定义目录重启后保留
    assert len(ws2.roots()) == 2


def test_remove_persists_across_reload(tmp_path, monkeypatch):
    monkeypatch.setattr("core.workspace._TEMP_ROOTS_FILE", tmp_path / "ws.json")
    ws1 = WorkspaceManager(preset_roots=[])
    ws1.add_temp_root(str(tmp_path / "temp_x"))
    ws1.remove_temp_root(str(tmp_path / "temp_x"))

    ws2 = WorkspaceManager(preset_roots=[])
    assert str(tmp_path / "temp_x") not in ws2.roots()  # 移除也持久化


# --------------------------------------------------------------------- 激活工作区


def test_active_root_defaults_to_first(ws, tmp_path):
    assert ws.active_root() == str(tmp_path / "root_a")


def test_set_active_root(ws, tmp_path):
    ws.add_temp_root(str(tmp_path / "temp_x"))
    assert ws.set_active_root(str(tmp_path / "temp_x")) == str(tmp_path / "temp_x")
    assert ws.active_root() == str(tmp_path / "temp_x")


def test_set_active_root_rejects_unregistered(ws, tmp_path):
    before = ws.active_root()
    ws.set_active_root(str(tmp_path / "not_registered"))
    assert ws.active_root() == before  # 拒绝后保持原值


def test_active_root_falls_back_when_removed(ws, tmp_path):
    ws.add_temp_root(str(tmp_path / "temp_x"))
    ws.set_active_root(str(tmp_path / "temp_x"))
    ws.remove_temp_root(str(tmp_path / "temp_x"))
    assert ws.active_root() == str(tmp_path / "root_a")  # 回退首个根


def test_active_root_persists_across_reload(tmp_path, monkeypatch):
    monkeypatch.setattr("core.workspace._TEMP_ROOTS_FILE", tmp_path / "ws.json")
    ws1 = WorkspaceManager(preset_roots=[str(tmp_path / "root_a"), str(tmp_path / "root_b")])
    ws1.set_active_root(str(tmp_path / "root_b"))

    ws2 = WorkspaceManager(preset_roots=[str(tmp_path / "root_a"), str(tmp_path / "root_b")])
    assert ws2.active_root() == str(tmp_path / "root_b")  # 重启后保留激活状态


def test_resolve_within(root_a, ws, tmp_path):
    # 绝对路径在工作区内 → 放行
    resolved = ws.resolve_within(str(root_a / "doc.pdf"))
    assert resolved is not None and resolved.name == "doc.pdf"
    # 工作区外的绝对路径 → 拒绝
    outside = tmp_path / "outside" / "evil.txt"
    outside.parent.mkdir(exist_ok=True)
    outside.write_text("x")
    assert ws.resolve_within(str(outside)) is None
    # 根目录本身放行
    assert ws.resolve_within(str(root_a)) is not None


# --------------------------------------------------------------------- 文件树


def test_tree(root_a, ws):
    tree = ws.tree(str(root_a))
    names = {e["name"] for e in tree["entries"]}
    assert "doc.pdf" in names
    assert "pic.png" in names
    assert "sub" in names
    sub = next(e for e in tree["entries"] if e["name"] == "sub")
    assert sub["is_dir"] is True
    pdf = next(e for e in tree["entries"] if e["name"] == "doc.pdf")
    assert pdf["is_image"] is False
    png = next(e for e in tree["entries"] if e["name"] == "pic.png")
    assert png["is_image"] is True


def test_tree_outside_rejected(ws, tmp_path):
    with pytest.raises(ValueError):
        ws.tree(str(tmp_path))  # tmp_path 不在 root_a/root_b 内


# --------------------------------------------------------------------- 缩略图


def test_thumbnail_png(root_a, ws):
    data = ws.thumbnail(str(root_a / "pic.png"), size=64)
    assert data is not None
    assert data[:8] == b"\x89PNG\r\n\x1a\n"


def test_thumbnail_non_image(root_a, ws):
    assert ws.thumbnail(str(root_a / "doc.pdf")) is None
    assert ws.thumbnail(str(root_a / "missing.png")) is None


# --------------------------------------------------------------------- 打开


def test_open_rejects_outside(ws, tmp_path):
    outside = tmp_path / "outside"
    ok, _ = ws.open_path(str(outside))
    assert ok is False  # 越界拒绝,不触发 os.startfile


# --------------------------------------------------------------------- 操作日志


def test_activities_order(ws):
    ws.add_activity(kind="scan", detail="扫描完成")
    ws.add_activity(kind="execute", detail="移动 3 个文件")
    rows = ws.activities()
    assert len(rows) == 2
    assert rows[0]["detail"] == "移动 3 个文件"  # 倒序:最新在前


def test_activities_clear(ws):
    ws.add_activity(kind="scan", detail="x")
    ws.clear_activities()
    assert ws.activities() == []


# --------------------------------------------------------------------- 人格化翻译


@pytest.mark.asyncio
async def test_persona_translate_success():
    fake = _FakeLLM("整理好啦,都归位了～")
    t = PersonaTranslator(fake)
    out = await t.translate("✗ file_organize: 没有需要整理的文件")
    assert out == "整理好啦,都归位了～"
    assert fake.prompt_seen is not None
    assert "伊塔" in fake.prompt_seen


@pytest.mark.asyncio
async def test_persona_translate_fallback_on_error():
    t = PersonaTranslator(_FakeLLM("", boom=True))
    mechanical = "✗ file_organize: 没有需要整理的文件"
    out = await t.translate(mechanical)
    assert out == mechanical  # 失败降级原样返回


@pytest.mark.asyncio
async def test_persona_translate_empty():
    t = PersonaTranslator(_FakeLLM("忽略我"))
    assert await t.translate("") == ""
    assert await t.translate("(无执行结果)") == "(无执行结果)"  # 占位符跳过


# --------------------------------------------------------------------- 权限联动(v0.4.2)
# decide_write 与电脑操控共用同一 AccessPolicy(四级模式 + 黑白名单),仅拦写操作


def _policy(mode: ControlMode = ControlMode.MANUAL) -> AccessPolicy:
    """构造不落盘的 AccessPolicy(persist=False,避免污染 settings.yaml)。"""
    return AccessPolicy(mode=mode, persist=False)


def test_decide_write_no_policy_defaults_allow(ws):
    # 未注入 policy → 兼容旧行为,默认放行
    verdict, reason = ws.decide_write(r"D:\T08171634")
    assert verdict == "allow"


def test_decide_write_manual_approves(ws):
    ws.bind_access_policy(_policy(ControlMode.MANUAL))
    verdict, reason = ws.decide_write(r"D:\T08171634")
    assert verdict == "approve"


def test_decide_write_auto_approves_medium_risk(ws):
    # FILE_WRITE 映射 MEDIUM → AUTO 模式需审批
    ws.bind_access_policy(_policy(ControlMode.AUTO))
    verdict, reason = ws.decide_write(r"D:\T08171634")
    assert verdict == "approve"


def test_decide_write_full_allows(ws):
    ws.bind_access_policy(_policy(ControlMode.FULL))
    verdict, reason = ws.decide_write(r"D:\T08171634")
    assert verdict == "allow"


def test_decide_write_custom_default_intercepts(ws):
    # CUSTOM 无规则:默认拦截(走审批弹窗)
    ws.bind_access_policy(_policy(ControlMode.CUSTOM))
    verdict, reason = ws.decide_write(r"D:\T08171634")
    assert verdict == "approve"


def test_decide_write_custom_block_rule(ws):
    p = _policy(ControlMode.CUSTOM)
    p.set_custom_rule(ControlAction.FILE_WRITE.value, "block")
    ws.bind_access_policy(p)
    verdict, reason = ws.decide_write(r"D:\T08171634")
    assert verdict == "block"


def test_decide_write_custom_allow_rule(ws):
    p = _policy(ControlMode.CUSTOM)
    p.set_custom_rule(ControlAction.FILE_WRITE.value, "allow")
    ws.bind_access_policy(p)
    verdict, reason = ws.decide_write(r"D:\T08171634")
    assert verdict == "allow"


def test_decide_write_whitelist_overrides_mode(ws):
    # 白名单命中直接放行,MANUAL 也放行
    p = _policy(ControlMode.MANUAL)
    p.add_whitelist(PolicyEntryType.ACTION.value, ControlAction.FILE_WRITE.value, "工作区写操作")
    ws.bind_access_policy(p)
    verdict, reason = ws.decide_write(r"D:\T08171634")
    assert verdict == "allow"


def test_decide_write_blacklist_blocks_even_full(ws):
    # 黑名单硬闸:FULL 模式下仍拦截
    p = _policy(ControlMode.FULL)
    p.add_blacklist(PolicyEntryType.ACTION.value, ControlAction.FILE_WRITE.value, "禁止文件写操作")
    ws.bind_access_policy(p)
    verdict, reason = ws.decide_write(r"D:\T08171634")
    assert verdict == "block"


# --------------------------------------------------------------------- 执行器写门控(v0.4.2)


class _StubWorkspace:
    """极简工作区桩:只提供 decide_write / add_activity,不触碰真实文件系统。"""

    def __init__(self, verdict: str = "allow", reason: str = ""):
        self._verdict = verdict
        self._reason = reason
        self.activities: list[str] = []

    def decide_write(self, detail: str = "") -> tuple[str, str]:
        return self._verdict, self._reason

    def add_activity(self, kind: str, preset: str, detail: str) -> None:
        self.activities.append(detail)


def _file_protocol() -> dict:
    return {
        "protocol_version": 1,
        "task_type": "file_organize",
        "persona_id": "ita",
        "session_id": "s1",
        "goal": "整理文件",
        "plan": {"source_dir": r"D:\T08171634"},
    }


def _make_executor(ws):
    from core.work_protocol import WorkProtocolExecutor

    return WorkProtocolExecutor(
        computer=MagicMock(),
        file_organizer=MagicMock(),
        doc_writer=MagicMock(),
        workspace=ws,
    )


@pytest.mark.asyncio
async def test_executor_file_blocked_by_permission():
    ws = _StubWorkspace(verdict="block", reason="命中用户黑名单")
    ex = _make_executor(ws)
    results = await ex.execute(_file_protocol())
    assert results[0]["status"] == "denied"
    assert "权限拦截" in results[0]["detail"]
    ex._file_organizer.preview_organize.assert_not_called()  # 未触达文件管线


@pytest.mark.asyncio
async def test_executor_file_approve_records_activity_and_proceeds():
    ws = _StubWorkspace(verdict="approve", reason="手动审批模式：需用户确认")
    ex = _make_executor(ws)
    ex._file_organizer.execute_organize.return_value = (True, "整理完成", "undo-1")
    results = await ex.execute(_file_protocol())
    assert results[0]["status"] == "ok"
    assert ws.activities  # 审批记录已写入工作区活动日志
    assert ex._file_organizer.preview_organize.called
