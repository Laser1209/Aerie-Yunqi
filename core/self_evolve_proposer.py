"""Aerie · 云栖 — L4 Self-Evolution Proposer (LLM 生成 file_changes).

在 L0 能力缺口检测命中后，调用代码模型（AERIE_WS_CODE_MODEL，多 Key 轮询）
把缺口转成具体的代码修改提案（file_changes），交给 L4 ViabilityGate 四道
闸门审查后应用/审批。

安全设计：
  - 生成物严格受 JSON Schema 校验（相对路径、动作枚举、内容非空）；
  - 任何结构校验失败都返回 None，绝不向闸门传递未校验的内容；
  - 与主对话模型隔离，只走代码模型 + 独立 Key 池。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 允许的动作枚举
_ACTIONS = ("create", "modify", "delete")
# 禁止的路径特征（绝对路径 / 盘符 / 越权 / 反斜杠 / 隐藏文件）
_BAD_PATH_PATTERNS = (r"^/", r"^[A-Za-z]:", r"\.\.", r"\\", r"^\.")
_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)
# test_command 白名单前缀（L4 Gate3 以 shell=True 执行，必须收紧）
_TEST_CMD_PREFIXES = ("pytest", "python -m pytest", "python3 -m pytest", "python -m unittest")
# 禁止出现在 test_command 中的 shell 元字符
_TEST_CMD_FORBIDDEN = set(";&|`$<>()*?[]{}!\"'~")


def _sanitize_test_command(cmd: str) -> str:
    """净化 Gate3 测试命令：只放行白名单前缀、无 shell 元字符的命令。

    不合规 → 返回空串（Gate3 将跳过测试，不阻塞；绝不执行任意命令）。
    """
    if not cmd or not isinstance(cmd, str):
        return ""
    cmd = cmd.strip()
    if len(cmd) > 300:
        return ""
    lowered = cmd.lower()
    if not any(lowered.startswith(p) for p in _TEST_CMD_PREFIXES):
        return ""
    if any(c in _TEST_CMD_FORBIDDEN for c in cmd):
        return ""
    return cmd


class SelfEvolveProposer:
    """用代码模型把能力缺口生成具体 file_changes 提案。"""

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        keys: Optional[list[str]] = None,
    ) -> None:
        self._base_url = (base_url or os.getenv("AERIE_WS_BASE_URL", "")).strip()
        self._model = (model or os.getenv("AERIE_WS_CODE_MODEL", "kimi-k2.7-code")).strip()
        if keys:
            from core.key_rotator import KeyRotator
            self._rotator = KeyRotator(keys)
        else:
            from core.key_rotator import KeyRotator
            self._rotator = KeyRotator.from_env("AERIE_WS_KEYS", "AERIE_WS_API_KEY")

    @property
    def available(self) -> bool:
        """需要 base_url + 至少一个 Key + 模型名。"""
        return bool(self._base_url and self._rotator.size and self._model)

    @property
    def model(self) -> str:
        return self._model

    @staticmethod
    def _client_for(key: str, base_url: str):
        from openai import AsyncOpenAI
        return AsyncOpenAI(api_key=key, base_url=base_url)

    @staticmethod
    def _system_prompt() -> str:
        return (
            "你是 Aerie 系统的代码自进化引擎。你的唯一任务：根据给定的能力缺口描述，"
            "产出精确、最小化的 Python 代码修改提案，让系统获得缺失的能力。\n"
            "硬性约束：\n"
            "1. 只输出一个 JSON 对象，不要任何解释性文字、不要 markdown 代码块标记。\n"
            "2. JSON 结构：{\"file_changes\": [{...}], \"test_command\": \"...\"}。\n"
            "   每个 file_changes 元素：{\"path\": \"相对仓库根目录的路径\", "
            "\"action\": \"create|modify|delete\", \"new_content\": \"该文件的完整新内容(create/modify 必填)\", "
            "\"diff\": \"可选，变更说明摘要\"}。\n"
            "3. path 必须是相对路径（如 skills/foo.py、scripts/bar.py）；禁止绝对路径、禁止 ../、禁止盘符。\n"
            "4. core/ 下的修改视为高风险；除非缺口确实必须改核心模块，否则优先选 skills/、scripts/、tests/、"
            "plugins/、memory/layers/ 等外围目录。\n"
            "5. test_command 必须是可直接执行的验证命令（如 pytest tests/test_x.py -q），没有则给空字符串。\n"
            "6. 严禁引入 os.system、subprocess、eval、exec 等危险调用，除非缺口本身必须要求且你明确在 diff 中标注。\n"
            "7. new_content 必须是完整可运行的代码，不要留 TODO/占位符。\n"
        )

    @staticmethod
    def _user_prompt(ctx: dict) -> str:
        lines = [
            "请根据以下能力缺口生成代码修改提案：",
            f"用户消息: {str(ctx.get('user_message') or '')[:500]}",
            f"模型思考: {str(ctx.get('thought') or '')[:500]}",
            f"失败的既有工具: {ctx.get('failed_tool') or '无'}",
        ]
        tool_desc = str(ctx.get("tool_desc") or "").strip()
        if tool_desc:
            lines.append(f"失败工具说明: {tool_desc[:500]}")
        related = ctx.get("related_files") or {}
        if related:
            lines.append("相关文件内容（供你理解现状，不必全部修改）:")
            for fp, content in list(related.items())[:5]:
                lines.append(f"--- {fp} ---")
                lines.append(str(content)[:2000])
        lines.append("现在只输出 JSON。")
        return "\n".join(lines)

    @staticmethod
    def _validate_path(path: Any) -> bool:
        if not isinstance(path, str) or not path:
            return False
        p = path.strip().replace("\\", "/")
        for pat in _BAD_PATH_PATTERNS:
            if re.search(pat, p):
                return False
        return bool(p) and not p.endswith("/")

    def _validate_file_changes(self, file_changes: Any) -> list[dict]:
        """严格校验生成物；任何一条不合法即丢弃该条。"""
        if not isinstance(file_changes, list) or not file_changes:
            return []
        out: list[dict] = []
        for fc in file_changes:
            if not isinstance(fc, dict):
                continue
            path = str(fc.get("path") or "").strip()
            action = str(fc.get("action") or "").strip()
            if action not in _ACTIONS or not self._validate_path(path):
                continue
            if action in ("create", "modify"):
                content = fc.get("new_content")
                if not isinstance(content, str) or not content.strip():
                    continue
                out.append({
                    "path": path,
                    "action": action,
                    "new_content": content,
                    "diff": str(fc.get("diff") or ""),
                })
            else:
                out.append({"path": path, "action": "delete", "new_content": "", "diff": ""})
        return out

    @staticmethod
    def _extract_json(raw: str) -> Optional[dict]:
        """容错解析：剥代码块标记，裁剪到最外层 { }。"""
        raw = raw.strip()
        m = _JSON_BLOCK_RE.search(raw)
        if m:
            raw = m.group(1).strip()
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            data = json.loads(raw[start:end + 1])
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    async def propose(self, ctx: dict, timeout: float = 60.0) -> Optional[dict]:
        """生成提案。失败/校验不过 → None（绝不抛异常到主链路）。

        ctx 建议字段：user_message / thought / failed_tool / tool_desc /
        related_files（{相对路径: 内容}，可省略）。
        """
        if not self.available:
            logger.warning("self_evolve_proposer unavailable (base_url/keys/model missing)")
            return None
        system = self._system_prompt()
        user = self._user_prompt(ctx)
        last_err = ""
        for _ in range(max(1, self._rotator.size)):
            key = self._rotator.next()
            if not key:
                continue
            try:
                client = self._client_for(key, self._base_url)
                resp = await asyncio.wait_for(
                    client.chat.completions.create(
                        model=self._model,
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        temperature=0.2,
                    ),
                    timeout=timeout,
                )
                raw = (resp.choices[0].message.content or "").strip()
                data = self._extract_json(raw)
                if not data:
                    logger.warning("proposer key ...%s returned non-JSON", key[-6:])
                    continue
                file_changes = self._validate_file_changes(data.get("file_changes"))
                if not file_changes:
                    logger.warning("proposer key ...%s produced invalid file_changes", key[-6:])
                    continue
                logger.info(
                    "proposer succeeded with key ...%s: %d file_changes",
                    key[-6:], len(file_changes),
                )
                return {
                    "file_changes": file_changes,
                    "test_command": _sanitize_test_command(
                        str(data.get("test_command") or "")
                    ),
                }
            except Exception as e:
                last_err = str(e)
                logger.warning("proposer key ...%s failed: %s", key[-6:], e)
                continue
        if last_err:
            logger.warning("proposer all keys failed: %s", last_err)
        return None
