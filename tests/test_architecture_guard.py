"""P2-00 架构守护风险测试 — 守护器测试套件.

验证 tools/architecture_guard.py 的四大边界检查：
  RULE-001  单一主链（Pipeline/ContextBuilder 唯一性 + 组合根）
  RULE-002  跨库所有权（world_service ↔ core 隔离）
  RULE-003  World 副作用边界（world_service 无通信/IO 副作用）
  RULE-004  Renderer→Sidecar 直连检测（WARNING 级，架构债务）

测试策略：
  - 正向：当前代码树零 ERROR（硬不变量满足）。
  - 负向：注入临时违规文件 → 守护器必须报对应 ERROR（Red/Green）。
  - 排除：Spotlight/Android 路径样本必须被忽略。
"""
from __future__ import annotations

import shutil
import textwrap
from pathlib import Path

import pytest

from tools.architecture_guard import (
    ROOT,
    Violation,
    check_cross_ownership,
    check_renderer_sidecar_boundary,
    check_single_main_chain,
    check_world_side_effect_boundary,
    run_all_checks,
)

# ─── 正向：当前代码树硬不变量满足 ─────────────────────────────────────


class TestCurrentTreePasses:
    """当前代码树应通过所有硬不变量检查（ERROR 级零违规）。"""

    def test_rule001_single_main_chain_no_errors(self):
        violations = check_single_main_chain(ROOT)
        errors = [v for v in violations if v.severity == "ERROR"]
        assert errors == [], f"RULE-001 硬不变量违规: {[v.message for v in errors]}"

    def test_rule002_cross_ownership_no_errors(self):
        violations = check_cross_ownership(ROOT)
        errors = [v for v in violations if v.severity == "ERROR"]
        assert errors == [], f"RULE-002 硬不变量违规: {[v.message for v in errors]}"

    def test_rule003_world_side_effect_no_errors(self):
        violations = check_world_side_effect_boundary(ROOT)
        errors = [v for v in violations if v.severity == "ERROR"]
        assert errors == [], f"RULE-003 硬不变量违规: {[v.message for v in errors]}"

    def test_full_report_passes(self):
        """完整扫描：零 ERROR，exit code 等价 0。"""
        report = run_all_checks(ROOT)
        assert report.passed, f"守护器报错: {[v.message for v in report.errors]}"
        assert len(report.errors) == 0

    def test_rule004_reports_existing_warnings(self):
        """RULE-004 应检出既有 renderer-sidecar 直连债务（WARNING 级）。"""
        violations = check_renderer_sidecar_boundary(ROOT)
        # 当前代码树存在既有 sidecar 直连（chat.js 等），至少应有 warning
        assert len(violations) > 0, "RULE-004 应检出既有 renderer-sidecar 直连"
        assert all(v.severity == "WARNING" for v in violations)


# ─── 负向：注入违规文件 → 守护器必须报错 ──────────────────────────────


class TestNegativeInjection:
    """注入临时违规文件，验证守护器能精确检出。"""

    @pytest.fixture
    def temp_violation(self, tmp_path: Path):
        """创建临时项目根目录，复制最小结构供注入测试。"""
        # 复制 tools 目录（守护器本身）
        shutil.copytree(ROOT / "tools", tmp_path / "tools")
        # 创建最小 core 目录结构
        (tmp_path / "core").mkdir(parents=True)
        (tmp_path / "core" / "__init__.py").write_text("")
        (tmp_path / "core" / "pipeline.py").write_text("class Pipeline: pass\n")
        (tmp_path / "core" / "context_builder.py").write_text("class ContextBuilder: pass\n")
        (tmp_path / "core" / "companion.py").write_text(
            "from core.pipeline import Pipeline\n"
            "from core.context_builder import ContextBuilder\n"
            "class Companion:\n"
            "    def __init__(self):\n"
            "        self.pipeline = Pipeline()\n"
            "        self.context_builder = ContextBuilder()\n"
        )
        # 创建最小 world_service 目录
        (tmp_path / "world_service").mkdir(parents=True)
        (tmp_path / "world_service" / "__init__.py").write_text("")
        (tmp_path / "world_service" / "main.py").write_text("# clean\n")
        yield tmp_path
        # tmp_path 由 pytest 自动清理

    def test_rule001_detects_duplicate_pipeline(self, temp_violation: Path):
        """注入 pipeline_v2.py → RULE-001 必须报 ERROR。"""
        (temp_violation / "core" / "pipeline_v2.py").write_text("class Pipeline: pass\n")
        violations = check_single_main_chain(temp_violation)
        errors = [v for v in violations if v.severity == "ERROR"]
        assert any("pipeline_v2" in v.file for v in errors), "应检出 pipeline_v2.py 平行实现"

    def test_rule001_detects_duplicate_context_builder(self, temp_violation: Path):
        """注入 context_builder_v2.py → RULE-001 必须报 ERROR。"""
        (temp_violation / "core" / "context_builder_v2.py").write_text("class ContextBuilder: pass\n")
        violations = check_single_main_chain(temp_violation)
        errors = [v for v in violations if v.severity == "ERROR"]
        assert any("context_builder_v2" in v.file for v in errors), "应检出 context_builder_v2.py"

    def test_rule001_detects_pipeline_in_wrong_file(self, temp_violation: Path):
        """在非授权文件定义 Pipeline → RULE-001 必须报 ERROR。"""
        (temp_violation / "core" / "other.py").write_text("class Pipeline: pass\n")
        violations = check_single_main_chain(temp_violation)
        errors = [v for v in violations if v.severity == "ERROR"]
        assert any("other.py" in v.file for v in errors), "应检出非授权文件中的 Pipeline 定义"

    def test_rule002_detects_world_imports_core_database(self, temp_violation: Path):
        """world_service import core.database → RULE-002 必须报 ERROR。"""
        (temp_violation / "world_service" / "bad.py").write_text(
            "from core.database import Database\n"
        )
        violations = check_cross_ownership(temp_violation)
        errors = [v for v in violations if v.severity == "ERROR"]
        assert any("core.database" in v.message for v in errors), "应检出 world_service import core.database"

    def test_rule003_detects_world_imports_qq_client(self, temp_violation: Path):
        """world_service import qq_client → RULE-003 必须报 ERROR。"""
        (temp_violation / "world_service" / "bad.py").write_text(
            "from communication.qq_client import QQClient\n"
        )
        violations = check_world_side_effect_boundary(temp_violation)
        errors = [v for v in violations if v.severity == "ERROR"]
        assert any("qq_client" in v.message for v in errors), "应检出 world_service import qq_client"

    def test_rule003_detects_world_subprocess(self, temp_violation: Path):
        """world_service 调用 subprocess.run → RULE-003 必须报 ERROR。"""
        (temp_violation / "world_service" / "bad.py").write_text(
            "import subprocess\n"
            "subprocess.run(['ls'])\n"
        )
        violations = check_world_side_effect_boundary(temp_violation)
        errors = [v for v in violations if v.severity == "ERROR"]
        assert any("subprocess" in v.message for v in errors), "应检出 world_service subprocess 调用"

    def test_rule004_detects_hardcoded_sidecar_url(self, temp_violation: Path):
        """renderer JS 硬编码 sidecar URL → RULE-004 必须报 WARNING。"""
        renderer = temp_violation / "electron" / "src" / "renderer" / "js"
        renderer.mkdir(parents=True)
        (renderer / "bad.js").write_text(
            'const r = await fetch("http://127.0.0.1:7890/api/test");\n'
        )
        violations = check_renderer_sidecar_boundary(temp_violation)
        assert any("bad.js" in v.file for v in violations), "应检出 renderer 硬编码 sidecar URL"
        assert all(v.severity == "WARNING" for v in violations)


# ─── 排除验证：Spotlight / Android 路径被忽略 ──────────────────────────


class TestExclusionBoundary:
    """验证 Spotlight / Android 路径不被扫描。"""

    def test_spotlight_py_files_ignored(self, tmp_path: Path):
        """Spotlight 目录下的 .py 文件不被扫描。"""
        # 创建 tools 目录（守护器）
        shutil.copytree(ROOT / "tools", tmp_path / "tools")
        # 在 Spotlight 目录下放置违规文件
        spotlight = tmp_path / "Spotlight" / "core"
        spotlight.mkdir(parents=True)
        (spotlight / "pipeline_v2.py").write_text("class Pipeline: pass\n")
        # 创建合法的 core 目录
        (tmp_path / "core").mkdir(parents=True)
        (tmp_path / "core" / "__init__.py").write_text("")
        (tmp_path / "core" / "pipeline.py").write_text("class Pipeline: pass\n")
        (tmp_path / "core" / "context_builder.py").write_text("class ContextBuilder: pass\n")
        (tmp_path / "core" / "companion.py").write_text(
            "class Companion:\n"
            "    def __init__(self):\n"
            "        self.pipeline = None\n"
            "        self.context_builder = None\n"
        )
        violations = check_single_main_chain(tmp_path)
        errors = [v for v in violations if v.severity == "ERROR"]
        # Spotlight 下的 pipeline_v2.py 不应被检出
        spot_violations = [v for v in errors if "Spotlight" in v.file]
        assert spot_violations == [], f"Spotlight 文件不应被扫描: {spot_violations}"

    def test_android_py_files_ignored(self, tmp_path: Path):
        """android-client 目录下的 .py 文件不被扫描。"""
        shutil.copytree(ROOT / "tools", tmp_path / "tools")
        # 在 android-client 下放置违规文件
        android = tmp_path / "android-client" / "world_service"
        android.mkdir(parents=True)
        (android / "bad.py").write_text("from core.database import Database\n")
        # 创建合法的 world_service 目录
        (tmp_path / "world_service").mkdir(parents=True)
        (tmp_path / "world_service" / "__init__.py").write_text("")
        (tmp_path / "world_service" / "main.py").write_text("# clean\n")
        violations = check_cross_ownership(tmp_path)
        errors = [v for v in violations if v.severity == "ERROR"]
        android_violations = [v for v in errors if "android-client" in v.file]
        assert android_violations == [], f"Android 文件不应被扫描: {android_violations}"


# ─── 守护器结构验证 ──────────────────────────────────────────────────


class TestGuardStructure:
    """验证守护器报告结构完整性。"""

    def test_report_has_all_rules(self):
        report = run_all_checks(ROOT)
        assert set(report.rules_checked) == {"RULE-001", "RULE-002", "RULE-003", "RULE-004"}

    def test_report_files_scanned_positive(self):
        report = run_all_checks(ROOT)
        assert report.files_scanned > 0, "应扫描到文件"

    def test_violations_have_required_fields(self):
        """每条违规应包含 rule_id, severity, file, line, message。"""
        report = run_all_checks(ROOT)
        for v in report.violations:
            assert v.rule_id in {"RULE-001", "RULE-002", "RULE-003", "RULE-004"}
            assert v.severity in {"ERROR", "WARNING"}
            assert isinstance(v.file, str) and v.file
            assert isinstance(v.line, int) and v.line >= 0
            assert isinstance(v.message, str) and v.message

    def test_to_dict_serializable(self):
        import json
        report = run_all_checks(ROOT)
        data = report.to_dict()
        # 验证可 JSON 序列化
        json.dumps(data, ensure_ascii=False)
        assert "passed" in data
        assert "violations" in data
        assert "errors" in data
        assert "warnings" in data
