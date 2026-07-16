"""Aerie · 云栖 v9.0 — Skill Loader (Block-4C R3.1).

Discovers skill directories under ``skills/local/`` and ``skills/data/``,
parses their ``SKILL.md`` YAML frontmatter, and registers each
``run.py`` callable as a tool in the central ``ToolRegistry``.

Security notes:
  - YAML is loaded with ``yaml.safe_load`` (no python/object constructors).
  - The skill path is resolved and verified to live under one of the
    two whitelisted base directories.
  - All shell-style arguments are passed to ``subprocess.run`` as
    list args with ``shell=False`` (per skill implementation).
  - Any failure (missing dir, bad frontmatter, ImportError) is logged
    at WARNING and skipped — the main pipeline is never broken by a
    misbehaving skill.
"""

from __future__ import annotations
import importlib.util
import logging
import sys
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_LOCAL_SKILLS_DIR = _PROJECT_ROOT / "skills" / "local"
_DATA_SKILLS_DIR = _PROJECT_ROOT / "skills" / "data"
_ALLOWED_BASES = (_LOCAL_SKILLS_DIR.resolve(), _DATA_SKILLS_DIR.resolve())


class SkillLoader:
    """Discovers + registers skills into a ToolRegistry.

    The registry is mutated in place via ``register(name, func, schema,
    provider_hint)``. Existing tools (the 3 default ones) are never
    overwritten — duplicate names are skipped.
    """

    def __init__(self, tool_registry: Any, router: Any) -> None:
        self.registry = tool_registry
        self.router = router
        # name -> {"path": Path, "hint": str, "read_only": bool, "desc": str, "kind": "local"|"data"}
        self.discovered: dict[str, dict] = {}
        self._registered: set[str] = set()

    # ── Public API ─────────────────────────────────────
    def discover(self) -> int:
        """Scan both skill roots and parse SKILL.md frontmatter."""
        count = 0
        for base, kind in (
            (_LOCAL_SKILLS_DIR, "local"),
            (_DATA_SKILLS_DIR, "data"),
        ):
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
                    if name in self.discovered:
                        # First write wins (local > data precedence).
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
            if not any(str(rp).startswith(str(b)) for b in _ALLOWED_BASES):
                logger.warning("skill %s: run.py outside allowed bases, skip", name)
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
