"""技能管理器测试"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from tools.skill_manager import SkillManager, SkillInfo


@pytest.fixture
def skill_manager():
    tmpdir = tempfile.mkdtemp()
    mgr = SkillManager(skills_dir=str(Path(tmpdir) / "skills"))
    yield mgr
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


class TestSkillManager:
    """技能管理器测试"""

    def test_search_market_finds_excel(self, skill_manager):
        """搜索 'excel' 找到 excel_analysis"""
        results = skill_manager.search_market("excel")
        assert len(results) >= 1
        names = [r.name for r in results]
        assert "excel_analysis" in names

    def test_search_market_finds_pdf(self, skill_manager):
        """搜索 'pdf' 找到 pdf_toolkit"""
        results = skill_manager.search_market("pdf")
        assert len(results) >= 1
        names = [r.name for r in results]
        assert "pdf_toolkit" in names

    def test_search_market_no_match(self, skill_manager):
        """搜索不存在的技能返回空"""
        results = skill_manager.search_market("xyz_nonexistent")
        assert len(results) == 0

    def test_search_market_has_tools(self, skill_manager):
        """搜索结果包含工具定义"""
        results = skill_manager.search_market("excel")
        assert len(results) > 0
        skill = results[0]
        assert len(skill.tools) > 0
        assert skill.tools[0]["name"]

    def test_installed_skills_empty_initially(self, skill_manager):
        """初始已安装列表为空"""
        assert skill_manager.installed_skills == []

    @pytest.mark.asyncio
    async def test_install_skill(self, skill_manager):
        """安装技能"""
        info = SkillInfo(
            name="test_skill",
            version="1.0.0",
            description="测试技能",
            source="github.com/opencloud-companion/skills",
            size_mb=1,
            tools=[],
            dependencies=[],
            is_trusted=True,
        )
        success, msg = await skill_manager.install(info)
        assert success
        assert "test_skill" in skill_manager.installed_skills

    @pytest.mark.asyncio
    async def test_install_duplicate_skill(self, skill_manager):
        """重复安装返回失败"""
        info = SkillInfo(
            name="dup_skill",
            version="1.0.0",
            description="重复技能",
            source="github.com/opencloud-companion/skills",
            is_trusted=True,
        )
        success, _ = await skill_manager.install(info)
        assert success
        success2, msg = await skill_manager.install(info)
        assert not success2

    def test_approve_skill(self, skill_manager):
        """手动批准技能安装"""
        assert skill_manager.approve("nonexistent") is False
