"""Aerie · 云栖 v0.1.0-beta.1 — Skill Loader (Block-4C R3.1).

Discovers skill directories under ``skills/local/``, ``skills/cloud/`` and
``skills/data/``, parses their ``SKILL.md`` YAML frontmatter, and registers
each ``run.py`` callable as a tool in the central ``ToolRegistry``.

Root priority (``_SKILL_ROOTS`` order, first write wins on name collision):
  ``local`` > ``cloud`` > ``data``
  - local: 本机专用能力（最高优先，可覆盖同名通用能力）
  - cloud: 通用能力包（scaffold 生成，元数据显式声明 read_only）
  - data : 历史遗留桶（当前 5 个 skill 均 read_only=true），兜底最低优先

Security notes:
  - YAML is loaded with ``yaml.safe_load`` (no python/object constructors).
  - The skill path is resolved and verified to live under one of the
    whitelisted base directories (all three roots above).
  - All shell-style arguments are passed to ``subprocess.run`` as
    list args with ``shell=False`` (per skill implementation).
  - Any failure (missing dir, bad frontmatter, ImportError) is logged
    at WARNING and skipped — the main pipeline is never broken by a
    misbehaving skill.
"""

from __future__ import annotations
import importlib.util
import logging
import os
import sys
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_LOCAL_SKILLS_DIR = _PROJECT_ROOT / "skills" / "local"
_CLOUD_SKILLS_DIR = _PROJECT_ROOT / "skills" / "cloud"
_DATA_SKILLS_DIR = _PROJECT_ROOT / "skills" / "data"

# 扫描顺序即优先级：同名 skill 先扫到的胜出（local > cloud > data）。
# 缺失的根目录会被直接跳过（skills/data 与 skills/cloud 都可能不存在）。
_SKILL_ROOTS: tuple[tuple[Path, str], ...] = (
    (_LOCAL_SKILLS_DIR, "local"),
    (_CLOUD_SKILLS_DIR, "cloud"),
    (_DATA_SKILLS_DIR, "data"),
)
_ALLOWED_BASES = tuple(base.resolve() for base, _kind in _SKILL_ROOTS)


def _unsatisfied_requirement(meta: dict[str, Any]) -> str:
    """SKILL.md 声明的可用性前提是否满足；不满足返回原因，满足返回空串。

    两个可选声明（未声明 = 照常暴露，保持既有行为）：

    * ``requires_module``：底层 Python 模块必须可导入（本地模型 / 后端）；
    * ``requires_env``：环境变量必须非空（云端服务凭证）。

    为什么要有这道闸：2026-09-29 真机里，模型在"要看图"时反复调 ``txt2img``
    （``local_txt2img`` 未安装）与 ``byted-seedream``（``SEEDREAM_KEY`` 未设），
    每次都必然失败，还顺带把失败文案播给用户（§十四 #63）。**不可用的能力
    不该出现在模型可见的工具清单里**。
    """
    module = str(meta.get("requires_module") or "").strip()
    if module:
        try:
            found = importlib.util.find_spec(module) is not None
        except (ImportError, ValueError):
            found = False
        if not found:
            return f"missing module: {module}"
    env_name = str(meta.get("requires_env") or "").strip()
    if env_name and not str(os.environ.get(env_name) or "").strip():
        return f"missing env: {env_name}"
    return ""


class SkillLoader:
    """Discovers + registers skills into a ToolRegistry.

    The registry is mutated in place via ``register(name, func, schema,
    provider_hint)``. 既有工具（内置工具、其它来源）**绝不覆盖**：注册前先查
    ``registry.get(name)``，同名则跳过并记 WARNING。
    """

    def __init__(self, tool_registry: Any, router: Any) -> None:
        self.registry = tool_registry
        self.router = router
        # name -> {"path": Path, "hint": str, "read_only": bool, "desc": str, "kind": "local"|"cloud"|"data"}
        self.discovered: dict[str, dict] = {}
        self._registered: set[str] = set()

    # ── Public API ─────────────────────────────────────
    def discover(self) -> int:
        """Scan all skill roots (priority order) and parse SKILL.md frontmatter.

        幂等：每次调用先清空 ``self.discovered``，重复调用返回同一结果。
        """
        # 重新发现：先清空，否则第二次调用会因子典非空而全部走 first-write-wins 返回 0
        self.discovered.clear()
        count = 0
        for base, kind in _SKILL_ROOTS:
            if not base.exists():
                continue
            try:
                for entry in sorted(base.iterdir()):
                    if not entry.is_dir():
                        continue
                    skill_md = entry / "SKILL.md"
                    if not skill_md.exists():
                        continue
                    meta = self._parse_frontmatter(skill_md)
                    if not meta or not meta.get("name"):
                        logger.warning("skill %s: missing name in frontmatter", entry)
                        continue
                    name = str(meta["name"]).strip()
                    # 可用性闸门放在同名遮蔽判定**之前**：否则一个跑不了的
                    # local skill 会先把名字占住，把真正可用的同名 cloud skill 挡掉。
                    missing = _unsatisfied_requirement(meta)
                    if missing:
                        logger.info("skill %s 未注册：%s", name, missing)
                        continue
                    if name in self.discovered:
                        # First write wins (local > cloud > data precedence).
                        logger.debug(
                            "skill %s in %s shadowed by %s",
                            name, kind, self.discovered[name]["kind"],
                        )
                        continue
                    self.discovered[name] = {
                        "path": entry,
                        "kind": kind,
                        "hint": str(meta.get("provider_hint", "text") or "text"),
                        "read_only": bool(meta.get("read_only", kind == "data")),
                        "desc": str(meta.get("description", "") or ""),
                    }
                    count += 1
            except Exception as e:
                logger.warning("skill discovery error in %s: %s", base, e)
        return count

    def register_all(self) -> int:
        """For each discovered skill, dynamic-import run.py and register.

        Idempotent: re-running on the same SkillLoader is a no-op for
        already-registered skills.
        """
        n = 0
        for name, meta in self.discovered.items():
            if name in self._registered:
                continue
            run_py = meta["path"] / "run.py"
            if not run_py.exists():
                logger.debug("skill %s: no run.py, skip register", name)
                continue
            # Path-traversal guard: confirm the run.py is under an
            # allowed base directory.
            try:
                rp = run_py.resolve()
            except Exception:
                continue
            # 真正的目录包含判定（is_relative_to 按路径分量比较）；不能用字符串
            # 前缀匹配——`skills/cloud-evil` 会被误判成在 `skills/cloud` 之内，
            # 让 junction/软链指向的越界 skill 执行成功。
            if not any(rp.is_relative_to(b) for b in _ALLOWED_BASES):
                logger.warning("skill %s: run.py outside allowed bases, skip", name)
                continue
            # 冲突检查：已存在的工具（内置工具 / 其它来源）绝不覆盖。
            # companion 先 register_all_tools() 再 skill_loader.register_all()，
            # 若此处不拦截，cloud 的 scaffold 桩技能会顶掉同名的真实内置工具。
            try:
                existing = self.registry.get(name)
            except AttributeError:
                existing = None
            if existing is not None:
                logger.warning(
                    "skill %s: 工具名已被注册表占用，跳过注册（不覆盖既有工具）", name
                )
                continue
            try:
                spec = importlib.util.spec_from_file_location(f"skill_{name}", run_py)
                if spec is None or spec.loader is None:
                    continue
                mod = importlib.util.module_from_spec(spec)
                # Ensure relative path resolution works inside the skill.
                sys.modules[spec.name] = mod
                spec.loader.exec_module(mod)
                func = getattr(mod, "run", None)
                if not callable(func):
                    logger.debug("skill %s: no run() function, skip", name)
                    continue
                self.registry.register(
                    name=name,
                    func=func,
                    schema={
                        "type": "function",
                        "function": {
                            "name": name,
                            "description": meta["desc"] or f"Skill: {name}",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "args": {
                                        "type": "object",
                                        "description": "Free-form args for the skill",
                                    },
                                },
                                "required": [],
                            },
                        },
                    },
                    provider_hint=meta["hint"],
                )
                self._registered.add(name)
                n += 1
            except Exception as e:
                logger.warning("skill %s register failed: %s", name, e)
        return n

    def call(self, name: str, args: dict | None = None) -> dict:
        """Call a skill by name. Always re-imports run.py so dev
        iteration works without backend restart.
        """
        meta = self.discovered.get(name)
        if not meta:
            return {"error": f"skill '{name}' not found"}
        run_py = meta["path"] / "run.py"
        if not run_py.exists():
            return {"error": f"run.py missing for skill '{name}'"}
        try:
            spec = importlib.util.spec_from_file_location(f"skill_runtime_{name}", run_py)
            if spec is None or spec.loader is None:
                return {"error": "spec load failed"}
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            result = mod.run(args or {})
            return result if isinstance(result, dict) else {"value": result}
        except Exception as e:
            logger.exception("skill %s call failed", name)
            return {"error": str(e)}

    # ── Internal ───────────────────────────────────────
    @staticmethod
    def _parse_frontmatter(skill_md: Path) -> dict | None:
        """Parse YAML frontmatter delimited by ``---`` at the top of the file."""
        try:
            text = skill_md.read_text(encoding="utf-8")
        except Exception:
            return None
        if not text.startswith("---"):
            return None
        end = text.find("\n---", 3)
        if end < 0:
            return None
        block = text[3:end].strip()
        try:
            data = yaml.safe_load(block)  # safe_load: no python/object tags
        except yaml.YAMLError as e:
            logger.warning("frontmatter parse failed %s: %s", skill_md, e)
            return None
        if not isinstance(data, dict):
            return None
        return data
