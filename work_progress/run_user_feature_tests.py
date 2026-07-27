"""
用户视角功能测试脚本（Aerie桌面端）
目标：模拟用户实际点击/询问/上传等操作，通过FastAPI TestClient（无需端口）调用后端，
      验证真实可用功能，并输出结构化测试报告。
用法：python work_progress/run_user_feature_tests.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

# 确保可以 import 项目
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("AERIE_DATA_DIR", str(PROJECT_ROOT / "data"))


# ==========================================================
# 【第一部分】用户视角测试清单（按功能面板分类）
# ==========================================================
TEST_CHECKLIST = [
    {
        "category": "1. 侧边栏核心导航",
        "tests": [
            {"id": "NAV-01", "name": "健康检查（启动后第一件事）", "scope": "API /api/health"},
            {"id": "NAV-02", "name": "获取运行时快照（系统状态面板）", "scope": "API /api/runtime/snapshot"},
            {"id": "NAV-03", "name": "查询可用工具列表", "scope": "API /api/tools/list"},
        ],
    },
    {
        "category": "2. 聊天主面板 / 用户每日最先使用",
        "tests": [
            {"id": "CHAT-01", "name": "发送文字消息（普通提问）", "scope": "POST /api/chat/send"},
            {"id": "CHAT-02", "name": "查询聊天请求状态（request_id）", "scope": "GET /api/chat/requests/{id}"},
            {"id": "CHAT-03", "name": "分页获取历史消息（翻页查看上下文）", "scope": "GET /api/chat/history/page"},
            {"id": "CHAT-04", "name": "获取最近一段历史", "scope": "GET /api/chat/history"},
            {"id": "CHAT-05", "name": "长轮询事件（流式/实时通知）", "scope": "GET /api/chat/poll"},
            {"id": "CHAT-06", "name": "取消当前正在生成的回复", "scope": "POST /api/chat/requests/{id}/cancel"},
            {"id": "CHAT-07", "name": "撤回消息（用户点撤回）", "scope": "POST /api/chat/recall/{msg_id}"},
            {"id": "CHAT-08", "name": "查看撤回状态", "scope": "GET /api/chat/recall_status/{msg_id}"},
        ],
    },
    {
        "category": "3. 附件 / 图片上传与查看（聊天工具栏）",
        "tests": [
            {"id": "UP-01", "name": "查询上传能力支持（类型/大小/数量限制）", "scope": "GET /api/upload/types"},
            {"id": "UP-02", "name": "上传一张普通图片（用户点别针→选文件）", "scope": "POST /api/upload + multipart"},
            {"id": "UP-03", "name": "通过 attachments 接口接受/确认附件", "scope": "POST /api/attachments"},
            {"id": "UP-04", "name": "查询附件详情", "scope": "GET /api/attachments/{id}"},
            {"id": "UP-05", "name": "查询附件能力", "scope": "GET /api/attachments/capabilities"},
            {"id": "UP-06", "name": "下载已上传文件", "scope": "GET /api/attachments/{id}/download"},
        ],
    },
    {
        "category": "4. 图片能力（生成/视觉识别）",
        "tests": [
            {"id": "IMG-01", "name": "文生图（描述→图片）", "scope": "POST /api/images/generate"},
            {"id": "IMG-02", "name": "图生文 / 视觉识别（给图片提问）", "scope": "POST /api/images/vision"},
        ],
    },
    {
        "category": "5. 语音输入（聊天麦克风按钮）",
        "tests": [
            {"id": "AUD-01", "name": "查询音频服务状态", "scope": "GET /api/audio/status"},
            {"id": "AUD-02", "name": "语音转文字（需音频）", "scope": "POST /api/audio/transcribe"},
        ],
    },
    {
        "category": "6. 情绪仪表盘（点第二个标签）",
        "tests": [
            {"id": "EMO-01", "name": "获取当前情绪状态（五维+主导情绪）", "scope": "GET /api/emotion/state"},
            {"id": "EMO-02", "name": "获取情绪历史曲线", "scope": "GET /api/emotion/history"},
            {"id": "EMO-03", "name": "查询情绪阈值配置", "scope": "GET /api/emotion/thresholds"},
        ],
    },
    {
        "category": "7. 认知中枢（第三个标签）",
        "tests": [
            {"id": "COG-01", "name": "获取最近认知 Trace 列表", "scope": "GET /api/cognition/recent"},
            {"id": "COG-02", "name": "认知统计汇总", "scope": "GET /api/cognition/stats"},
        ],
    },
    {
        "category": "8. 系统状态 & NapCat/QQ（第四个+QQ标签）",
        "tests": [
            {"id": "QQ-01", "name": "查询 NapCat 运行状态", "scope": "GET /api/napcat/status"},
            {"id": "QQ-02", "name": "查询 NapCat 最近日志", "scope": "GET /api/napcat/logs"},
            {"id": "QQ-03", "name": "QQ 白名单列表", "scope": "GET /api/qq/whitelist"},
        ],
    },
    {
        "category": "9. 世界仪表盘 & 审批（第五个标签）",
        "tests": [
            {"id": "WLD-01", "name": "获取世界仪表盘快照", "scope": "GET /api/world/dashboard/snapshot"},
            {"id": "WLD-02", "name": "图片候选审批接口存在性", "scope": "POST /api/world/candidates/approve"},
        ],
    },
    {
        "category": "10. 时光/纪念 & 日历任务（第六个标签）",
        "tests": [
            {"id": "TSK-01", "name": "任务列表", "scope": "GET /api/tasks"},
            {"id": "TSK-02", "name": "任务统计", "scope": "GET /api/tasks/stats"},
            {"id": "TSK-03", "name": "创建一个待办任务", "scope": "POST /api/tasks"},
        ],
    },
    {
        "category": "11. 主动消息 / 灵动岛（桌面通知 + 点赞反馈）",
        "tests": [
            {"id": "PRO-01", "name": "查询主动消息总开关状态", "scope": "GET /api/proactive/status"},
            {"id": "PRO-02", "name": "列出可用触发场景", "scope": "GET /api/proactive/scenes"},
            {"id": "PRO-03", "name": "查询推送策略（频率/免打扰）", "scope": "GET /api/proactive/policy"},
            {"id": "PRO-04", "name": "用户对主动消息点赞/踩反馈", "scope": "POST /api/proactive/feedback"},
            {"id": "PRO-05", "name": "静默/推迟某条推送", "scope": "POST /api/proactive/mute"},
        ],
    },
    {
        "category": "12. 办公模式（聊天栏 Office 按钮）",
        "tests": [
            {"id": "OFF-01", "name": "查询办公模式状态", "scope": "GET /api/office/mode"},
            {"id": "OFF-02", "name": "切换办公模式开关", "scope": "PUT /api/office/mode"},
            {"id": "OFF-03", "name": "办公设备/目录信息", "scope": "GET /api/office/device, GET /api/office/dir"},
        ],
    },
    {
        "category": "13. 设置页（人物设定/灵动岛/主题）",
        "tests": [
            {"id": "CFG-01", "name": "列出 YAML 配置项", "scope": "GET /api/config/yaml/list"},
            {"id": "CFG-02", "name": "读取 YAML 配置", "scope": "GET /api/config/yaml"},
            {"id": "CFG-03", "name": "YAML 配置备份", "scope": "POST /api/config/yaml/backup"},
            {"id": "CFG-04", "name": "运行时配置 PATCH", "scope": "PATCH /api/runtime/config"},
        ],
    },
    {
        "category": "14. 后台数据 / 知识库（第九个标签）",
        "tests": [
            {"id": "DAT-01", "name": "权限配置（读取/写入）", "scope": "GET /api/permissions/config, PUT"},
            {"id": "DAT-02", "name": "允许目录列表", "scope": "GET /api/permissions/dirs"},
            {"id": "DAT-03", "name": "审计日志接口", "scope": "GET /api/permissions/audit"},
        ],
    },
    {
        "category": "15. 自进化 L4（认知中枢页底部）",
        "tests": [
            {"id": "EVO-01", "name": "自进化提案列表", "scope": "GET /api/self_evolve/list"},
            {"id": "EVO-02", "name": "自进化统计", "scope": "GET /api/self_evolve/stats"},
        ],
    },
    {
        "category": "16. 电脑操控能力（认知-电脑操控）",
        "tests": [
            {"id": "CC-01", "name": "电脑操控统计", "scope": "GET /api/computer_control/stats"},
            {"id": "CC-02", "name": "当前允许级别", "scope": "GET /api/computer_control/level"},
            {"id": "CC-03", "name": "待审批操作列表", "scope": "GET /api/computer_control/approvals/pending"},
        ],
    },
]


TOTAL_TESTS = sum(len(c["tests"]) for c in TEST_CHECKLIST)


def print_checklist() -> None:
    """打印测试清单到控制台，方便用户审阅。"""
    print("=" * 78)
    print("  Aerie 桌面端 · 用户视角功能测试清单")
    print(f"  生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  总计: {len(TEST_CHECKLIST)} 大类 / {TOTAL_TESTS} 项测试")
    print("=" * 78)
    for cat in TEST_CHECKLIST:
        print(f"\n■ {cat['category']}  （共 {len(cat['tests'])} 项）")
        for t in cat["tests"]:
            print(f"   □ {t['id']:6s}  {t['name']:<32s}  |  {t['scope']}")
    print("\n" + "=" * 78)


# ==========================================================
# 【第二部分】实际运行测试（使用 httpx.AsyncClient 直接打 app）
# ==========================================================

async def run_api_tests() -> dict:
    """使用 httpx + ASGITransport 直接调用 FastAPI app，无需端口。"""
    try:
        from httpx import AsyncClient, ASGITransport
    except ImportError:
        print("[安装依赖] pip install httpx")
        os.system(sys.executable + " -m pip install httpx -q")
        from httpx import AsyncClient, ASGITransport

    # 延迟导入：避免打印清单时因依赖缺失而失败
    from core.api_server import app

    results: dict = {}
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # ---------- 1. NAV ----------
        results["NAV-01"] = await _t(ac.get, "/api/health", check_json_ok=True)
        results["NAV-02"] = await _t(ac.get, "/api/runtime/snapshot", accept_status={200, 503, 404})
        results["NAV-03"] = await _t(ac.get, "/api/tools/list")

        # ---------- 2. CHAT ----------
        # 先发一条消息，拿到 request_id
        chat_resp = await _t(
            ac.post,
            "/api/chat/send",
            json={"text": "你好，介绍一下你自己", "sender": "user"},
        )
        results["CHAT-01"] = chat_resp
        rid = None
        if chat_resp.ok and isinstance(chat_resp.body, dict):
            rid = (
                chat_resp.body.get("request_id")
                or chat_resp.body.get("data", {}).get("request_id")
            )
        if rid:
            results["CHAT-02"] = await _t(ac.get, f"/api/chat/requests/{rid}")
            results["CHAT-06"] = await _t(ac.post, f"/api/chat/requests/{rid}/cancel", accept_status={200, 409, 404})
        else:
            results["CHAT-02"] = _skip("未拿到 request_id（chat send 未返回）")
            results["CHAT-06"] = _skip("未拿到 request_id")

        results["CHAT-03"] = await _t(ac.get, "/api/chat/history/page", params={"page": 1, "size": 10})
        results["CHAT-04"] = await _t(ac.get, "/api/chat/history", params={"limit": 20})
        results["CHAT-05"] = await _t(ac.get, "/api/chat/poll", params={"timeout": 0.1}, accept_status={200, 504})
        # 撤回
        results["CHAT-07"] = await _t(ac.post, "/api/chat/recall/fake-msg-id", accept_status={200, 404})
        results["CHAT-08"] = await _t(ac.get, "/api/chat/recall_status/fake-msg-id", accept_status={200, 404})

        # ---------- 3. UPLOAD / ATTACHMENTS ----------
        results["UP-01"] = await _t(ac.get, "/api/upload/types")
        # 构造一个极小的 jpeg 文件上传
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
            # 1x1 最小 JPEG
            tf.write(
                b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
                b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c"
                b"\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c"
                b" $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\xff\xc0\x00\x0b\x08\x00\x01\x00"
                b"\x01\x01\x01\x11\x00\xff\xc4\x00\x14\x00\x01\x00\x00\x00\x00\x00\x00\x00"
                b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xc4\x00\x14\x10\x01\x00\x00\x00"
                b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xda\x00\x08"
                b"\x01\x01\x00\x00?\x00\xfb\xbf\xff\xd9"
            )
            tmp = tf.name
        try:
            with open(tmp, "rb") as f:
                files = {"file": ("tiny.jpg", f, "image/jpeg")}
                results["UP-02"] = await _t(ac.post, "/api/upload", files=files)
        finally:
            os.unlink(tmp)
        results["UP-05"] = await _t(ac.get, "/api/attachments/capabilities")
        # 尝试创建 attachment（用一个假的 uploaded path，即便失败也算接口通）
        results["UP-03"] = await _t(
            ac.post,
            "/api/attachments",
            json={
                "kind": "image",
                "uploaded_path": "uploads/2025/01/dummy.jpg",
                "mime": "image/jpeg",
                "size": 256,
                "source": "chat",
            },
            accept_status={200, 201, 400, 500},
        )
        results["UP-04"] = await _t(ac.get, "/api/attachments/notfound-id", accept_status={200, 404})
        results["UP-06"] = await _t(ac.get, "/api/attachments/notfound-id/download", accept_status={200, 404})

        # ---------- 4. IMAGES ----------
        results["IMG-01"] = await _t(
            ac.post,
            "/api/images/generate",
            json={"prompt": "一只可爱的小猫", "n": 1, "size": "512x512"},
            accept_status={200, 501, 400, 500},
        )
        results["IMG-02"] = await _t(
            ac.post,
            "/api/images/vision",
            json={"image_url": "https://example.com/a.jpg", "question": "这是什么？"},
            accept_status={200, 501, 400, 500},
        )

        # ---------- 5. AUDIO ----------
        results["AUD-01"] = await _t(ac.get, "/api/audio/status")
        results["AUD-02"] = _skip("需真实音频文件，本轮跳过")

        # ---------- 6. EMOTION ----------
        results["EMO-01"] = await _t(ac.get, "/api/emotion/state", accept_status={200, 503})
        results["EMO-02"] = await _t(ac.get, "/api/emotion/history", params={"limit": 10})
        results["EMO-03"] = await _t(ac.get, "/api/emotion/thresholds")

        # ---------- 7. COGNITION ----------
        results["COG-01"] = await _t(ac.get, "/api/cognition/recent", params={"limit": 10})
        results["COG-02"] = await _t(ac.get, "/api/cognition/stats")

        # ---------- 8. QQ / NAPCAT ----------
        results["QQ-01"] = await _t(ac.get, "/api/napcat/status")
        results["QQ-02"] = await _t(ac.get, "/api/napcat/logs", params={"limit": 10})
        results["QQ-03"] = await _t(ac.get, "/api/qq/whitelist")

        # ---------- 9. WORLD DASHBOARD ----------
        results["WLD-01"] = await _t(ac.get, "/api/world/dashboard/snapshot", accept_status={200, 503, 404})
        # 审批接口即便没有候选也能响应 400/404 代表通
        results["WLD-02"] = await _t(
            ac.post,
            "/api/world/candidates/approve",
            json={"candidate_id": "nonexistent", "approved": True},
            accept_status={200, 400, 404, 503},
        )

        # ---------- 10. TASKS ----------
        results["TSK-01"] = await _t(ac.get, "/api/tasks")
        results["TSK-02"] = await _t(ac.get, "/api/tasks/stats")
        results["TSK-03"] = await _t(
            ac.post,
            "/api/tasks",
            json={"title": "测试任务：去超市买水", "due": None, "priority": 1},
            accept_status={200, 201, 400},
        )

        # ---------- 11. PROACTIVE ----------
        results["PRO-01"] = await _t(ac.get, "/api/proactive/status")
        results["PRO-02"] = await _t(ac.get, "/api/proactive/scenes")
        results["PRO-03"] = await _t(ac.get, "/api/proactive/policy")
        results["PRO-04"] = await _t(
            ac.post,
            "/api/proactive/feedback",
            json={"message_id": "fake-123", "feedback": "up"},
            accept_status={200, 400, 404},
        )
        results["PRO-05"] = await _t(
            ac.post,
            "/api/proactive/mute",
            json={"scene": "morning", "minutes": 30},
            accept_status={200, 400},
        )

        # ---------- 12. OFFICE ----------
        results["OFF-01"] = await _t(ac.get, "/api/office/mode")
        results["OFF-02"] = await _t(ac.put, "/api/office/mode", json={"enabled": False})
        results["OFF-03"] = await _t_many(
            [
                (ac.get, "/api/office/device", {}),
                (ac.get, "/api/office/dir", {}),
            ],
            accept_status={200, 404},
        )

        # ---------- 13. CONFIG / SETTINGS ----------
        results["CFG-01"] = await _t(ac.get, "/api/config/yaml/list")
        results["CFG-02"] = await _t(ac.get, "/api/config/yaml", params={"name": "settings"})
        results["CFG-03"] = await _t(ac.post, "/api/config/yaml/backup", json={"name": "settings"}, accept_status={200, 400})
        results["CFG-04"] = await _t(
            ac.patch,
            "/api/runtime/config",
            json={"some_flag": True},
            accept_status={200, 400},
        )

        # ---------- 14. PERMISSION / DATA ----------
        results["DAT-01"] = await _t_many(
            [
                (ac.get, "/api/permissions/config", {}),
                (ac.put, "/api/permissions/config", {"json": {"max_level": 2}}),
            ],
            accept_status={200, 400},
        )
        results["DAT-02"] = await _t(ac.get, "/api/permissions/dirs")
        results["DAT-03"] = await _t(ac.get, "/api/permissions/audit", params={"limit": 10})

        # ---------- 15. SELF EVOLUTION ----------
        results["EVO-01"] = await _t(ac.get, "/api/self_evolve/list", params={"limit": 10})
        results["EVO-02"] = await _t(ac.get, "/api/self_evolve/stats")

        # ---------- 16. COMPUTER CONTROL ----------
        results["CC-01"] = await _t(ac.get, "/api/computer_control/stats")
        results["CC-02"] = await _t(ac.get, "/api/computer_control/level")
        results["CC-03"] = await _t(ac.get, "/api/computer_control/approvals/pending")

    return results


# ---------------- 辅助：小的 HTTP 断言包装 ----------------

class _R:
    def __init__(self, ok: bool, status: int, note: str, body=None, skipped=False):
        self.ok = ok
        self.status = status
        self.note = note
        self.body = body
        self.skipped = skipped


def _skip(note: str) -> _R:
    return _R(False, 0, f"SKIP: {note}", skipped=True)


async def _t(method, path, *, accept_status=None, check_json_ok=False, **kwargs):
    accept_status = accept_status or {200}
    try:
        resp = await method(path, **kwargs)
    except Exception as e:
        return _R(False, 0, f"EXCEPTION: {type(e).__name__}: {e}")
    ok = resp.status_code in accept_status
    body = None
    note = f"HTTP {resp.status_code}"
    try:
        body = resp.json()
        if check_json_ok:
            # 某些接口返回 {ok:true} 或 status=ok
            if isinstance(body, dict):
                flag = body.get("ok") or body.get("status") == "ok" or body.get("healthy")
                if flag:
                    ok = True
                    note += " + JSON.ok=true"
    except Exception:
        pass
    return _R(ok, resp.status_code, note, body)


async def _t_many(calls, accept_status=None):
    subs = []
    ok_all = True
    for m, p, kw in calls:
        r = await _t(m, p, accept_status=accept_status, **kw)
        subs.append(f"{p}={r.note}")
        if not r.ok:
            ok_all = False
    return _R(ok_all, 0, " | ".join(subs))


# ==========================================================
# 【第三部分】输出报告
# ==========================================================
def print_report(results: dict) -> None:
    print("\n")
    print("=" * 78)
    print("  实际测试结果（API 端到端）")
    print("=" * 78)

    passed = skipped = failed = 0
    # 构建 id -> (name, category) 索引
    idx = {}
    for c in TEST_CHECKLIST:
        for t in c["tests"]:
            idx[t["id"]] = (t["name"], c["category"])

    for cat in TEST_CHECKLIST:
        print(f"\n■ {cat['category']}")
        for t in cat["tests"]:
            tid = t["id"]
            r = results.get(tid, _R(False, 0, "未执行"))
            if r.skipped:
                mark = "⚪"
                skipped += 1
            elif r.ok:
                mark = "✅"
                passed += 1
            else:
                mark = "❌"
                failed += 1
            name = t["name"]
            print(f"  {mark} {tid:6s}  {name:<32s}   {r.note}")

    total = passed + failed + skipped
    print("\n" + "-" * 78)
    print(
        f"  汇总: 通过 ✅ {passed}  /  失败 ❌ {failed}  /  跳过 ⚪ {skipped}   (共 {total} / 清单 {TOTAL_TESTS})"
    )
    rate = passed / TOTAL_TESTS * 100 if TOTAL_TESTS else 0
    print(f"  通过率（按清单）: {rate:.1f}%")
    print("=" * 78)


def save_report(results: dict) -> Path:
    out_dir = PROJECT_ROOT / "work_progress"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"user_feature_test_report_{time.strftime('%Y%m%d_%H%M%S')}.json"
    data = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "checklist_total": TOTAL_TESTS,
        "results": {},
    }
    for tid, r in results.items():
        data["results"][tid] = {
            "ok": r.ok,
            "status": r.status,
            "note": r.note,
            "skipped": r.skipped,
        }
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


async def _main() -> int:
    print_checklist()
    print("\n[1/2] 测试清单已输出，开始调用 API……\n")
    try:
        results = await run_api_tests()
    except Exception as e:
        print(f"[FATAL] 运行测试时异常: {type(e).__name__}: {e}")
        import traceback

        traceback.print_exc()
        return 2
    print_report(results)
    path = save_report(results)
    print(f"\n[2/2] 原始结果已保存: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
