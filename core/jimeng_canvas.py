"""即梦（Dreamina）画布 CLI 适配层 —— 用本地 ``dreamina-canvas`` 出图。

为什么需要它：gpt-image 中转（mysubapi）忽略 ``size`` 参数、只出横图，也没有
可用的图生图端点，于是「竖屏自拍」和「同一个人」这两个诉求都做不到。即梦的
seedream 系列同时支持 ``--ratio 9:16`` 与 i2i（``--ref node:<id>``），正好补上。

**积分闸门**：每次生成都带 ``--credit-ceiling``。报价超过上限时 CLI 会在运行前
停下、不扣分，我们把 ``credit_exceeded`` 如实上报，由调用方决定是否提高上限 ——
绝不在没有额度授权的情况下静默花钱。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import shutil
import subprocess
import tempfile
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from core.paths import data_dir

logger = logging.getLogger(__name__)

_CLI_ENV = "DREAMINA_CANVAS_BIN"
_CLI_FALLBACK = Path.home() / "bin" / "dreamina-canvas.exe"
_DEFAULT_MODEL = "seedream_5.0_pro"
_DEFAULT_CREDIT_CEILING = 16
_DEFAULT_TIMEOUT_SEC = 600

# 我们的像素档 → 即梦的 --ratio 取值。
_RATIO_BY_SIZE = {
    "768x1344": "9:16",
    "1344x768": "16:9",
    "1024x1024": "1:1",
}


def cli_path() -> str | None:
    """定位 dreamina-canvas 可执行文件；找不到返回 None。"""
    configured = (os.getenv(_CLI_ENV) or "").strip()
    if configured and Path(configured).exists():
        return configured
    found = shutil.which("dreamina-canvas")
    if found:
        return found
    if _CLI_FALLBACK.exists():
        return str(_CLI_FALLBACK)
    return None


def available() -> bool:
    return cli_path() is not None


def ratio_for_size(image_size: str) -> str:
    """像素档 → 即梦横竖比；未知档位回退竖屏（人物类占多数）。"""
    return _RATIO_BY_SIZE.get(str(image_size or "").strip(), "9:16")


# 服务端要求 node_id = "node_" + 10 位小写 Crockford Base32（不含 i/l/o/u）。
_NODE_ID_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"


def _new_node_id() -> str:
    return "node_" + "".join(secrets.choice(_NODE_ID_ALPHABET) for _ in range(10))


def _run(args: list[str], *, timeout: int) -> dict[str, Any]:
    """执行 CLI 并解析 JSON 输出。任何失败都归一成 ``{ok: False, ...}``。"""
    binary = cli_path()
    if binary is None:
        return {"ok": False, "error_code": "cli_not_found", "detail": "未找到 dreamina-canvas 可执行文件"}
    cmd = [binary, "--format", "json", "--non-interactive", *args]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error_code": "cli_timeout", "detail": f"CLI 超时（{timeout}s）"}
    except OSError as exc:
        return {"ok": False, "error_code": "cli_spawn_failed", "detail": str(exc)[:200]}

    payload: dict[str, Any] = {}
    out_text = (proc.stdout or "").strip()
    err_text = (proc.stderr or "").strip()
    # 失败时 CLI 把 JSON 写在 stderr（成功时在 stdout），两边都要试。
    for text in (out_text, err_text):
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            payload = parsed
            break
    if proc.returncode != 0 or payload.get("ok") is False:
        err = payload.get("error")
        validation = err.get("validation") if isinstance(err, dict) else None
        detail = ""
        if isinstance(validation, dict):
            detail = str(validation.get("detail") or "")
            reason = str(validation.get("reasonCode") or "")
            field = str(validation.get("fieldPath") or "")
            if reason or field:
                detail = f"[{reason} @{field}] {detail}".strip()
        if not detail and isinstance(err, dict):
            detail = str(err.get("message") or err.get("code") or "")
        if not detail:
            detail = (err_text or out_text or "").strip()[:300]
        return {
            "ok": False,
            "error_code": str(err.get("code") if isinstance(err, dict) else "cli_failed") or "cli_failed",
            "detail": detail[:400],
            "raw": payload,
            "exit_code": proc.returncode,
        }
    return {"ok": True, "data": payload.get("data") or {}, "meta": payload.get("meta") or {}}


def ensure_canvas(project_id: str, *, name: str = "Aerie") -> dict[str, Any]:
    """确保画布存在并复用。``project_id`` 由调用方持久化，重试复用同一值。"""
    listing = _run(["canvas", "ls"], timeout=60)
    if listing.get("ok"):
        for item in (listing.get("data") or {}).get("items") or []:
            if str(item.get("projectId") or "") == project_id:
                return {"ok": True, "project_id": project_id, "created": False}
    created = _run(
        ["canvas", "create", name, "--project-id", project_id],
        timeout=120,
    )
    if not created.get("ok"):
        return created
    return {"ok": True, "project_id": project_id, "created": True}


def list_image_models() -> list[dict[str, Any]]:
    """当前账号可用的图像模型与可填 flag（供设置页做下拉）。"""
    result = _run(["model", "list", "--type", "image"], timeout=60)
    if not result.get("ok"):
        return []
    items = (result.get("data") or {}).get("items") or []
    return [
        {"model": str(m.get("model") or ""), "modes": [str(x.get("name") or "") for x in (m.get("modes") or [])]}
        for m in items
        if isinstance(m, dict)
    ]


def node_resources(*, project_id: str, node_id: str, timeout: int = 60) -> list[dict[str, Any]]:
    """读取节点的产物素材列表（resourceId / type / status / creditsAmount）。

    ``node create --run`` 的响应本身不带产物，产物只在节点视图里 —— 所以
    生成后必须回读一次节点，不能凭 create 的返回值直接当资源 id 用
    （2026-09-28 实测：只看 create 响应会拿到空 resourceId）。
    """
    result = _run(
        ["node", "show", "--project-id", project_id, "--node-id", node_id],
        timeout=timeout,
    )
    if not result.get("ok"):
        return []
    found: list[dict[str, Any]] = []
    for entry in (result.get("data") or {}).get("nodes") or []:
        node = (entry or {}).get("node") or {}
        for res in node.get("resources") or []:
            if isinstance(res, dict):
                found.append(res)
    return found


def generate_image(
    *,
    prompt: str,
    project_id: str,
    image_size: str = "",
    model: str = "",
    resolution: str = "",
    credit_ceiling: int,
    reference_node_id: str = "",
    node_id: str = "",
    submit_id: str = "",
    timeout: int = _DEFAULT_TIMEOUT_SEC,
) -> dict[str, Any]:
    """生成一张图并等待终态。

    ``credit_ceiling`` 是本次授权的积分上限。报价超过它时 CLI 会在运行前停下并
    返回 ``credit_exceeded``，**不扣分** —— 调用方据此如实向用户报告，而不是
    抬高上限偷偷花钱。

    返回 ``{status, node_id, submit_id, resource_id, image_bytes, detail}``。
    """
    prompt = str(prompt or "").strip()
    if not prompt:
        return {"status": "failed", "error_code": "empty_prompt", "detail": "提示词为空"}
    if not available():
        return {"status": "unavailable", "error_code": "cli_not_found", "detail": "本机未安装 dreamina-canvas"}

    node_id = node_id or _new_node_id()
    mode = "i2i" if reference_node_id else "t2i"
    # i2i 必须显式给标题：t2i 会自动拿 prompt 当标题，i2i 不会（prompt 在 i2i 里
    # 是可选参数），漏了会以 CLI_INPUT_REQUIRED @title 被拒（2026-09-28 实测）。
    title = prompt[:40] or "Aerie 生活照"

    args = [
        "node", "create", "image",
        "--project-id", project_id,
        "--node-id", node_id,
        "--mode", mode,
        "--model", model or _DEFAULT_MODEL,
        "--prompt", prompt,
        "--title", title,
        "--ratio", ratio_for_size(image_size),
        "--credit-ceiling", str(int(credit_ceiling)),
        "--run",
    ]
    if submit_id:
        args += ["--submit-id", submit_id]
    if resolution:
        args += ["--resolution", resolution]
    if reference_node_id:
        args += ["--ref", f"node:{reference_node_id}"]

    # 不能用 `--run --wait`：i2i 下这个组合会被服务端以 ``service.7``（状态冲突）
    # 拒绝（2026-09-28 实测，t2i 同样写法却正常）。改为提交后用 operation wait
    # 独立等待，两条路径都能走通。
    result = _run(args, timeout=timeout + 60)
    if not result.get("ok"):
        error_code = str(result.get("error_code") or "cli_failed")
        return {
            "status": "credit_exceeded" if error_code.endswith("credit_ceiling_too_low") else "failed",
            "error_code": error_code,
            "detail": str(result.get("detail") or ""),
            "node_id": node_id,
        }

    data = result.get("data") or {}
    resolved_node_id = str((data.get("node") or {}).get("nodeId") or data.get("nodeId") or node_id)
    if not await_submit_id(resolved_node_id, project_id=project_id, timeout=timeout):
        # 没有 submitId 就拿不到终态，不能把"提交成功"当"出图成功"。
        return {
            "status": "failed",
            "error_code": "missing_submit_id",
            "node_id": resolved_node_id,
        }

    for res in node_resources(project_id=project_id, node_id=resolved_node_id):
        if str(res.get("type") or "image") != "image":
            continue
        status = str(res.get("status") or "")
        if status == "success" and res.get("resourceId"):
            return {
                "status": "ok",
                "node_id": resolved_node_id,
                "submit_id": str(res.get("submitId") or ""),
                "resource_id": str(res["resourceId"]),
            }
        if status == "failed":
            # 失败也扣费，且 errorCode 是唯一的失败依据——原样带出去，
            # 让上层能据此熔断（例如 i2i 的 20100）。
            service_code = str(res.get("errorCode") or "")
            return {
                "status": "failed",
                "error_code": f"resource_failed:{service_code}" if service_code else "resource_failed",
                "node_id": resolved_node_id,
                "submit_id": str(res.get("submitId") or ""),
            }
    return {"status": "failed", "error_code": "no_resource", "node_id": resolved_node_id}


def await_submit_id(node_id: str, *, project_id: str, timeout: int = _DEFAULT_TIMEOUT_SEC) -> str:
    """等节点产出 submitId 并等到操作进入终态，返回 submitId（无则空串）。

    提交与等待拆成两步是必须的（见 ``generate_image`` 的说明）；``operation wait``
    要求显式 submitId，而 ``node create --run`` 的响应体不一定带，得回读节点。
    """
    submit_id = ""
    deadline = time.monotonic() + max(30, timeout)
    while not submit_id and time.monotonic() < deadline:
        for res in node_resources(project_id=project_id, node_id=node_id):
            if res.get("submitId"):
                submit_id = str(res["submitId"])
                break
        if submit_id:
            break
        time.sleep(3)
    if not submit_id:
        return ""
    _run(
        ["operation", "wait", submit_id, "--project-id", project_id, "--timeout", f"{int(timeout)}s"],
        timeout=timeout + 60,
    )
    return submit_id


def download_resource(resource_id: str, *, project_id: str, output: str, timeout: int = 180) -> dict[str, Any]:
    """把画布素材下载到本地路径。"""
    if not resource_id:
        return {"status": "failed", "error_code": "missing_resource_id"}
    result = _run(
        ["resource", "download", resource_id, "--project-id", project_id, "-o", output],
        timeout=timeout,
    )
    if not result.get("ok"):
        return {"status": "failed", "detail": result.get("detail", ""), "error_code": result.get("error_code", "")}
    path = Path(output)
    if not path.exists() or not path.is_file():
        return {"status": "failed", "error_code": "download_missing_file", "detail": f"{output} 未生成"}
    return {"status": "ok", "path": str(path), "image_bytes": path.read_bytes()}


# ── 画布身份与人物参考持久化 ───────────────────────────────────────────────
# 画布 UUID 只生成一次并落盘：提交失败重试时必须复用同一值，否则会在服务端
# 留下一堆孤立的空画布。
#
# ``references`` 记录每个人设的三视图在画布上的落点（Element 节点 + 各视角资源
# UUID + 内容 sha256）。sha256 用于判断"这张图换过了没"，没换就不重传 —— 三视图
# 单张可达 8MB，每次生图都传一遍既慢又浪费。

_STATE_FILE = "jimeng_canvas.json"

# 主素材优先用正面：正面最利于锁脸。其余视角作辅助素材。
VIEW_ORDER = ("front", "side", "back")


def _state_path() -> Path:
    return data_dir() / _STATE_FILE


def _load_state() -> dict[str, Any]:
    path = _state_path()
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, json.JSONDecodeError):
        logger.debug("jimeng canvas state unreadable, starting fresh", exc_info=True)
    return {}


def _save_state(state: dict[str, Any]) -> None:
    path = _state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    except OSError:
        logger.warning("jimeng canvas state write failed", exc_info=True)


def load_project_id() -> str:
    """读取已持久化的画布 UUID；不存在则生成并写入。"""
    state = _load_state()
    existing = str(state.get("project_id") or "").strip()
    if existing:
        return existing
    created = str(uuid.uuid4())
    state["project_id"] = created
    _save_state(state)
    return created


def persona_reference(persona_id: str) -> dict[str, Any] | None:
    """取该人设已同步到画布的人物参考；未同步过返回 None。"""
    refs = _load_state().get("references")
    if not isinstance(refs, dict):
        return None
    entry = refs.get(str(persona_id or "").strip())
    if not isinstance(entry, dict):
        return None
    return dict(entry) if entry.get("element_node_id") else None


def clear_persona_reference(persona_id: str) -> None:
    """清掉同步记录，让后续生图回落到纯文字外貌描写。

    只清本地记录，不动画布上已有的 Element 节点——那个节点没有副作用，
    留着也方便排查；下次同步会重新建一个。
    """
    state = _load_state()
    refs = state.get("references")
    if not isinstance(refs, dict):
        return
    if refs.pop(str(persona_id or "").strip(), None) is not None:
        _save_state(state)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def upload_resource(
    file_path: str | Path,
    *,
    project_id: str,
    name: str = "",
    resource_id: str = "",
    timeout: int = 300,
) -> dict[str, Any]:
    """上传本地图片并登记为画布资源，返回 ``{ok, resource_id, detail}``。"""
    path = Path(file_path)
    if not path.exists():
        return {"ok": False, "error_code": "file_not_found", "detail": str(file_path)}
    args = ["resource", "upload", "--project-id", project_id, "--file", str(path)]
    if name:
        args += ["--name", name]
    if resource_id:
        args += ["--resource-id", resource_id]
    result = _run(args, timeout=timeout)
    if not result.get("ok"):
        return {"ok": False, "error_code": result.get("error_code", ""), "detail": result.get("detail", "")}
    return {"ok": True, "resource_id": str((result.get("data") or {}).get("resourceId") or "")}


def create_element_node(
    *,
    project_id: str,
    main_resource_id: str,
    auxiliary_resource_ids: tuple[str, ...] = (),
    node_id: str = "",
    title: str = "",
    description: str = "",
    timeout: int = 120,
) -> dict[str, Any]:
    """新建一个 Element 节点承载人物参考，返回 ``{ok, node_id, detail}``。"""
    if not main_resource_id:
        return {"ok": False, "error_code": "missing_main_resource"}
    node_id = node_id or _new_node_id()
    args = [
        "node", "create", "element",
        "--project-id", project_id,
        "--node-id", node_id,
        "--main", main_resource_id,
    ]
    for ref in auxiliary_resource_ids:
        if ref:
            args += ["--auxiliary", ref]
    if title:
        args += ["--title", title]
    if description:
        args += ["--description", description]
    result = _run(args, timeout=timeout)
    if not result.get("ok"):
        return {"ok": False, "error_code": result.get("error_code", ""), "detail": result.get("detail", ""), "node_id": node_id}
    created = (result.get("data") or {}).get("node") or {}
    return {"ok": True, "node_id": str(created.get("nodeId") or node_id)}


def edit_element_node(
    *,
    project_id: str,
    node_id: str,
    main_resource_id: str,
    auxiliary_resource_ids: tuple[str, ...] = (),
    title: str = "",
    description: str = "",
    timeout: int = 120,
) -> dict[str, Any]:
    """更新已有 Element 节点的素材绑定。

    必须用 ``node edit``：对已存在的 node_id 再发 ``node create``，服务端会以
    ``service.7``（状态冲突）拒绝（2026-09-28 实测）。
    """
    if not node_id:
        return {"ok": False, "error_code": "missing_node_id"}
    args = [
        "node", "edit", "element",
        "--project-id", project_id,
        "--node-id", node_id,
    ]
    if main_resource_id:
        args += ["--main", main_resource_id]
    if auxiliary_resource_ids:
        for ref in auxiliary_resource_ids:
            if ref:
                args += ["--auxiliary", ref]
    else:
        args.append("--clear-auxiliary")
    if title:
        args += ["--title", title]
    if description:
        args += ["--description", description]
    result = _run(args, timeout=timeout)
    if not result.get("ok"):
        return {"ok": False, "error_code": result.get("error_code", ""), "detail": result.get("detail", ""), "node_id": node_id}
    return {"ok": True, "node_id": node_id}


def sync_persona_reference(
    persona_id: str,
    views: dict[str, bytes],
    *,
    title: str = "",
) -> dict[str, Any]:
    """把三视图同步到即梦画布，返回可直接供 i2i 引用的 Element 节点。

    只上传内容变过的视角（按 sha256 比对）；三视图没变且节点已在，就直接复用，
    不产生任何网络写操作。返回 ``{ok, element_node_id, changed, reason}``。
    """
    persona_id = str(persona_id or "").strip()
    if not persona_id:
        return {"ok": False, "reason": "missing_persona_id"}
    usable = {v: b for v, b in (views or {}).items() if v in VIEW_ORDER and b}
    if not usable:
        return {"ok": False, "reason": "no_views"}
    if not available():
        return {"ok": False, "reason": "cli_not_found"}

    project_id = load_project_id()
    canvas = ensure_canvas(project_id)
    if not canvas.get("ok"):
        return {"ok": False, "reason": "canvas_unavailable", "detail": canvas.get("detail", "")}

    state = _load_state()
    refs = state.setdefault("references", {})
    entry = refs.get(persona_id) if isinstance(refs.get(persona_id), dict) else {}
    stored_views: dict[str, Any] = dict(entry.get("views") or {})

    changed: list[str] = []
    resolved: dict[str, dict[str, Any]] = {}
    temp_dir = Path(tempfile.gettempdir()) / "jimeng_refs"
    for view in VIEW_ORDER:
        data = usable.get(view)
        if not data:
            continue
        digest = _sha256(data)
        previous = stored_views.get(view) or {}
        if previous.get("sha256") == digest and previous.get("resource_id"):
            resolved[view] = {
                "resource_id": str(previous["resource_id"]),
                "sha256": digest,
            }
            continue
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_file = temp_dir / f"{persona_id}_{view}.png"
        try:
            temp_file.write_bytes(data)
        except OSError:
            logger.warning("jimeng reference temp write failed: %s", view, exc_info=True)
            continue
        uploaded = upload_resource(
            temp_file,
            project_id=project_id,
            name=f"{persona_id}-{view}",
        )
        if not uploaded.get("ok") or not uploaded.get("resource_id"):
            logger.warning(
                "jimeng reference upload failed view=%s code=%s",
                view, uploaded.get("error_code"), exc_info=False,
            )
            continue
        resolved[view] = {"resource_id": uploaded["resource_id"], "sha256": digest}
        changed.append(view)

    if not resolved:
        return {"ok": False, "reason": "upload_failed"}

    # 主素材优先正面；只有侧/背时退而用第一个可用的，不因为没有正面就整个放弃。
    main_view = next((v for v in VIEW_ORDER if v in resolved), "")
    main_resource = str(resolved[main_view]["resource_id"])
    auxiliaries = tuple(
        str(resolved[v]["resource_id"]) for v in VIEW_ORDER if v in resolved and v != main_view
    )

    element_node_id = str(entry.get("element_node_id") or "")
    if element_node_id and not changed:
        return {"ok": True, "element_node_id": element_node_id, "changed": [], "reused": True}

    node_title = title or f"{persona_id} 人物参考"
    description = "三视图人物参考（" + "/".join(
        {"front": "正", "side": "侧", "back": "背"}[v] for v in VIEW_ORDER if v in resolved
    ) + "），用于锁脸"

    if element_node_id:
        written = edit_element_node(
            project_id=project_id,
            node_id=element_node_id,
            main_resource_id=main_resource,
            auxiliary_resource_ids=auxiliaries,
            title=node_title,
            description=description,
        )
        if not written.get("ok"):
            # 节点可能已在服务端被删：退回新建，不让同步整体失败。
            logger.info("jimeng element edit failed, recreating: %s", written.get("detail"))
            element_node_id = ""
    if not element_node_id:
        written = create_element_node(
            project_id=project_id,
            main_resource_id=main_resource,
            auxiliary_resource_ids=auxiliaries,
            title=node_title,
            description=description,
        )
        if not written.get("ok"):
            return {"ok": False, "reason": "element_write_failed", "detail": written.get("detail", "")}
        element_node_id = str(written.get("node_id") or "")

    refs[persona_id] = {
        "element_node_id": element_node_id,
        "views": {v: resolved[v] for v in VIEW_ORDER if v in resolved},
        "main_view": main_view,
        "synced_at": _now_iso(),
    }
    _save_state(state)
    return {
        "ok": True,
        "element_node_id": element_node_id,
        "changed": changed,
        "main_view": main_view,
    }


def credit_ceiling() -> int:
    """单张图的积分授权上限。报价超限时 CLI 会在运行前停下、不扣分。"""
    raw = (os.getenv("JIMENG_CREDIT_CEILING") or "").strip()
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_CREDIT_CEILING
    return value if value > 0 else _DEFAULT_CREDIT_CEILING


# ── i2i 熔断 ───────────────────────────────────────────────────────────────
# 图生图失败**照样扣积分**（2026-09-28 实测：errorCode 20100 仍计 8 积分）。
# 当前账号跑 seedream_5.0_pro 的 i2i 稳定被拒，而 t2i 正常，所以不能每张图都
# 先试一次 i2i —— 那是纯烧钱。失败后写一个熔断窗口，窗口内直接走 t2i。

_I2I_BLOCK_HOURS_DEFAULT = 24


def i2i_enabled() -> bool:
    """总开关：设 ``JIMENG_I2I_ENABLED=false`` 可彻底不尝试图生图。"""
    raw = (os.getenv("JIMENG_I2I_ENABLED") or "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    return True


def _i2i_block_hours() -> float:
    raw = (os.getenv("JIMENG_I2I_BLOCK_HOURS") or "").strip()
    try:
        value = float(raw)
    except ValueError:
        return float(_I2I_BLOCK_HOURS_DEFAULT)
    return value


def i2i_usable() -> bool:
    """当前是否值得尝试图生图（关掉开关或处于熔断窗口内 → False）。"""
    if not i2i_enabled():
        return False
    state = _load_state()
    until = str(state.get("i2i_blocked_until") or "").strip()
    if not until:
        return True
    try:
        return datetime.fromisoformat(until) <= datetime.now()
    except ValueError:
        return True


def note_i2i_blocked(error_code: str) -> None:
    """记录一次 i2i 失败并开启熔断窗口。"""
    hours = _i2i_block_hours()
    state = _load_state()
    state["i2i_last_error"] = str(error_code or "")[:120]
    if hours > 0:
        state["i2i_blocked_until"] = (
            datetime.now() + timedelta(hours=hours)
        ).isoformat(timespec="seconds")
        logger.info("jimeng i2i blocked for %sh after %s", hours, error_code)
    _save_state(state)


def clear_i2i_block() -> None:
    state = _load_state()
    if state.pop("i2i_blocked_until", None) is not None:
        _save_state(state)


def default_model() -> str:
    return (os.getenv("JIMENG_IMAGE_MODEL") or "").strip() or _DEFAULT_MODEL


def default_resolution() -> str:
    """即梦分辨率档（1K / 1.5K / 2K 视模型而定）；留空则交给 CLI 默认。"""
    return (os.getenv("JIMENG_IMAGE_RESOLUTION") or "").strip()
