"""P1-A.5 — 角色配置版本化 PersonaConfig.

将六类输入合并为版本化 PersonaConfig：
    identity_facts → visual_identity → background → speaking_style →
    active_rules → current_state

每次保存记录 revision（首次保存 revision=1，后续递增）；
新 revision 保存后旧 revision 引用失效，用于使旧生成候选失效。

与 P0 VisualIntentRouter 接口兼容：to_metadata_dict() 产出
persona_config 字典，visual_identity 子结构含 visual_identity_revision
与 selfie_reference_asset_id。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_SIX_CATEGORY_ORDER: tuple[str, ...] = (
    "identity_facts",
    "visual_identity",
    "background",
    "speaking_style",
    "active_rules",
    "current_state",
)


@dataclass
class VisualIdentity:
    """视觉身份子结构。

    visual_identity_revision 独立于 PersonaConfig.revision，专门追踪
    视觉资产变更，供 P0 VisualIntentRouter 冻结身份版本。
    """

    visual_identity_revision: int = 1
    selfie_reference_asset_id: str = ""
    couple_reference_asset_id: str = ""
    avatar_asset_id: str = ""
    asset_review: str = ""

    def to_metadata_dict(self) -> dict[str, Any]:
        """产出 P0 VisualIntentRouter 可消费的 visual_identity 字典。"""
        return {
            "visual_identity_revision": self.visual_identity_revision,
            "selfie_reference_asset_id": self.selfie_reference_asset_id,
            "couple_reference_asset_id": self.couple_reference_asset_id,
            "avatar_asset_id": self.avatar_asset_id,
            "asset_review": self.asset_review,
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_metadata_dict()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VisualIdentity":
        return cls(
            visual_identity_revision=int(data.get("visual_identity_revision", 1) or 1),
            selfie_reference_asset_id=str(data.get("selfie_reference_asset_id", "")),
            couple_reference_asset_id=str(data.get("couple_reference_asset_id", "")),
            avatar_asset_id=str(data.get("avatar_asset_id", "")),
            asset_review=str(data.get("asset_review", "")),
        )


@dataclass
class PersonaConfig:
    """版本化角色配置，合并六类输入。

    revision 在首次 save 时置为 1，此后每次 save 递增。
    新 revision 保存后，is_revision_valid(旧 revision) 返回 False，
    用于使旧生成候选失效。
    """

    id: str
    identity_facts: dict[str, Any] = field(default_factory=dict)
    visual_identity: VisualIdentity = field(default_factory=VisualIdentity)
    background: dict[str, Any] = field(default_factory=dict)
    speaking_style: dict[str, Any] = field(default_factory=dict)
    active_rules: dict[str, Any] = field(default_factory=dict)
    current_state: dict[str, Any] = field(default_factory=dict)
    revision: int = 0
    _persist_path: Path | None = field(default=None, repr=False, compare=False)

    # ── 保存 / 加载 ────────────────────────────────────

    def save(self, persist_path: Path | None = None) -> int:
        """持久化并递增 revision。

        首次保存（revision == 0）→ revision=1；后续每次保存 → revision+1。
        persist_path 未提供时复用上一次保存路径。
        """
        path = persist_path or self._persist_path
        if path is None:
            raise ValueError("save 需要提供 persist_path")
        path = Path(path)

        if self.revision == 0:
            self.revision = 1
        else:
            self.revision += 1

        path.parent.mkdir(parents=True, exist_ok=True)
        _write_json_atomic(path, self.to_dict())
        self._persist_path = path
        return self.revision

    @classmethod
    def load(cls, persist_path: Path | str) -> "PersonaConfig":
        """从 JSON 文件重新加载 PersonaConfig。"""
        path = Path(persist_path)
        with open(path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        return cls.from_dict(data, persist_path=path)

    # ── revision 校验 ──────────────────────────────────

    def is_revision_valid(self, revision: int) -> bool:
        """判断给定 revision 是否仍为当前有效 revision。

        新 revision 保存后，旧 revision 返回 False，使旧生成候选失效。
        从未保存（revision == 0）时任何 revision 均无效。
        """
        return self.revision > 0 and revision == self.revision

    # ── 六类输入按顺序输出 ─────────────────────────────

    def to_prompt_sequence(self) -> list[tuple[str, Any]]:
        """按固定顺序输出六类输入，供 Prompt 注入。

        顺序：identity_facts → visual_identity → background →
        speaking_style → active_rules → current_state。
        """
        return [
            ("identity_facts", dict(self.identity_facts)),
            ("visual_identity", self.visual_identity.to_metadata_dict()),
            ("background", dict(self.background)),
            ("speaking_style", dict(self.speaking_style)),
            ("active_rules", dict(self.active_rules)),
            ("current_state", dict(self.current_state)),
        ]

    # ── P0 VisualIntentRouter 兼容 ─────────────────────

    def to_metadata_dict(self) -> dict[str, Any]:
        """产出 P0 VisualIntentRouter 可消费的 persona_config 字典。"""
        return {
            "id": self.id,
            "revision": self.revision,
            "identity_facts": dict(self.identity_facts),
            "visual_identity": self.visual_identity.to_metadata_dict(),
            "background": dict(self.background),
            "speaking_style": dict(self.speaking_style),
            "active_rules": dict(self.active_rules),
            "current_state": dict(self.current_state),
        }

    # ── 序列化 ─────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "revision": self.revision,
            "identity_facts": dict(self.identity_facts),
            "visual_identity": self.visual_identity.to_dict(),
            "background": dict(self.background),
            "speaking_style": dict(self.speaking_style),
            "active_rules": dict(self.active_rules),
            "current_state": dict(self.current_state),
        }

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        *,
        persist_path: Path | None = None,
    ) -> "PersonaConfig":
        return cls(
            id=str(data.get("id", "")),
            identity_facts=dict(data.get("identity_facts", {})),
            visual_identity=VisualIdentity.from_dict(
                data.get("visual_identity", {}) or {}
            ),
            background=dict(data.get("background", {})),
            speaking_style=dict(data.get("speaking_style", {})),
            active_rules=dict(data.get("active_rules", {})),
            current_state=dict(data.get("current_state", {})),
            revision=int(data.get("revision", 0) or 0),
            _persist_path=persist_path,
        )


def _write_json_atomic(target: Path, data: dict[str, Any]) -> None:
    """原子写入 JSON，与 persona_manager 风格一致。"""
    temp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        with open(temp, "w", encoding="utf-8") as fp:
            json.dump(data, fp, ensure_ascii=False, indent=2)
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(temp, target)
    except Exception:
        try:
            temp.unlink()
        except OSError:
            pass
        raise
