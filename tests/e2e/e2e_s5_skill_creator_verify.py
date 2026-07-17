"""Aerie v12.0 · S5 M5.5 自主 Skill 创建验证

验证项：
  T1 SkillType 5 种类型定义
  T2 模板配置存在
  T3 SkillInfo 数据模型
  T4 名称验证
  T5 SkillCodeGenerator 生成 SKILL.md
  T6 SkillCodeGenerator 生成 run.py (utility)
  T7 SkillCodeGenerator 生成 run.py (text_processing)
  T8 SkillCodeGenerator 生成 run.py (data_query)
  T9 SkillCodeGenerator 生成 run.py (transform)
  T10 安全验证 - 白名单导入通过
  T11 安全验证 - 危险模块拦截
  T12 安全验证 - eval/exec 拦截
  T13 SkillCreator 创建 utility skill
  T14 SkillCreator 创建 text_processing skill
  T15 SkillCreator 创建 data_query skill
  T16 SkillCreator 创建 transform skill
  T17 SkillCreator 重名检测
  T18 SkillCreator 名称合法性检测
  T19 Skill 列表查询
  T20 Skill 单个查询
  T21 动态加载验证（能 import + run 返回 dict）
  T22 Skill 测试运行
  T23 Skill 删除
  T24 命名空间隔离（不影响现有 skills）
  T25 统计信息
"""

from __future__ import annotations
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core.skill_creator import (
    SAFE_IMPORTS,
    SkillCodeGenerator,
    SkillCreator,
    SkillInfo,
    SkillNamespace,
    SkillSecurityValidator,
    SkillType,
    SkillValidationResult,
)


def t1_skill_types() -> tuple[bool, str]:
    """T1 SkillType 5 种类型定义"""
    types = list(SkillType)
    expected = [
        SkillType.UTILITY,
        SkillType.TEXT_PROCESSING,
        SkillType.DATA_QUERY,
        SkillType.TRANSFORM,
        SkillType.CUSTOM,
    ]
    checks = [len(types) == 5]
    for t in expected:
        checks.append(t in types)
    return all(checks), f"5种: {[t.value for t in types]}"


def t2_templates_exist() -> tuple[bool, str]:
    """T2 模板配置存在"""
    from core.skill_creator import SKEL_TEMPLATES
    checks = [
        SkillType.UTILITY in SKEL_TEMPLATES,
        SkillType.TEXT_PROCESSING in SKEL_TEMPLATES,
        SkillType.DATA_QUERY in SKEL_TEMPLATES,
        SkillType.TRANSFORM in SKEL_TEMPLATES,
        SkillType.CUSTOM in SKEL_TEMPLATES,
    ]
    return all(checks), f"templates={len(SKEL_TEMPLATES)}个"


def t3_skill_info_model() -> tuple[bool, str]:
    """T3 SkillInfo 数据模型"""
    info = SkillInfo(
        name="test_skill",
        namespace="auto_generated",
        skill_type=SkillType.UTILITY,
        description="测试",
        read_only=True,
        provider_hint="utility",
        path="/tmp/test",
        created_at=time.time(),
    )
    checks = [
        info.full_name == "auto_generated/test_skill",
        info.name == "test_skill",
        info.read_only == True,
        isinstance(info.to_dict(), dict),
        "full_name" in info.to_dict(),
        "type" in info.to_dict(),
    ]
    return all(checks), f"full_name={info.full_name}"


def t4_name_validation() -> tuple[bool, str]:
    """T4 名称验证"""
    from core.skill_creator import SkillCreator
    import tempfile
    tmpdir = Path(tempfile.mkdtemp())
    try:
        creator = SkillCreator(skills_root=str(tmpdir / "skills"))

        valid_names = ["my_skill", "Skill123", "a", "test-skill"]
        invalid_names = ["", "123start", "my skill", "very_long_" * 10, "a!b"]

        valid_count = sum(1 for n in valid_names if creator._validate_name(n))
        invalid_count = sum(1 for n in invalid_names if not creator._validate_name(n))

        checks = [
            valid_count == len(valid_names),
            invalid_count == len(invalid_names),
        ]
        return all(checks), f"valid={valid_count}/{len(valid_names)}, invalid={invalid_count}/{len(invalid_names)}"
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def t5_generate_skill_md() -> tuple[bool, str]:
    """T5 SkillCodeGenerator 生成 SKILL.md"""
    gen = SkillCodeGenerator()
    md = gen.generate_skill_md(
        name="my_skill",
        description="我的测试技能",
        read_only=True,
        provider_hint="utility",
        skill_type=SkillType.UTILITY,
    )
    checks = [
        "name: my_skill" in md,
        "description: 我的测试技能" in md,
        "read_only: true" in md,
        "# my_skill" in md,
        "## 入参" in md,
        "## 出参" in md,
    ]
    return all(checks), f"md_len={len(md)}"


def t6_generate_utility() -> tuple[bool, str]:
    """T6 生成 utility run.py"""
    gen = SkillCodeGenerator()
    code = gen.generate_run_py("util_skill", "工具", SkillType.UTILITY)
    checks = [
        "def run(args: dict)" in code,
        "READ_ONLY = True" in code,
        "PROVIDER_HINT" in code,
        '"status": "ok"' in code,
        "hash" in code,
        "timestamp" in code,
    ]
    return all(checks), f"code_len={len(code)}"


def t7_generate_text_processing() -> tuple[bool, str]:
    """T7 生成 text_processing run.py"""
    gen = SkillCodeGenerator()
    code = gen.generate_run_py("text_skill", "文本处理", SkillType.TEXT_PROCESSING)
    checks = [
        "def run(args: dict)" in code,
        "count" in code,
        "reverse" in code,
        "replace" in code,
        "find_all" in code,
    ]
    return all(checks), f"code_len={len(code)}"


def t8_generate_data_query() -> tuple[bool, str]:
    """T8 生成 data_query run.py"""
    gen = SkillCodeGenerator()
    code = gen.generate_run_py("data_skill", "数据查询", SkillType.DATA_QUERY)
    checks = [
        "def run(args: dict)" in code,
        "query" in code,
        "filter" in code,
        "sort" in code,
        "stats" in code,
    ]
    return all(checks), f"code_len={len(code)}"


def t9_generate_transform() -> tuple[bool, str]:
    """T9 生成 transform run.py"""
    gen = SkillCodeGenerator()
    code = gen.generate_run_py("trans_skill", "格式转换", SkillType.TRANSFORM)
    checks = [
        "def run(args: dict)" in code,
        "json" in code,
        "base64" in code,
        "list" in code,
    ]
    return all(checks), f"code_len={len(code)}"


def t10_security_safe_imports() -> tuple[bool, str]:
    """T10 安全验证 - 白名单导入通过"""
    validator = SkillSecurityValidator()
    code = """import json
import re
import math
from pathlib import Path

def run(args):
    return {"status": "ok"}
"""
    result = validator.validate(code, read_only=True)
    checks = [
        result.passed,
        len(result.issues) == 0,
        "json" in result.details.get("imports", []),
    ]
    return all(checks), f"passed={result.passed}, issues={len(result.issues)}"


def t11_security_unsafe_module() -> tuple[bool, str]:
    """T11 安全验证 - 危险模块拦截"""
    validator = SkillSecurityValidator()
    code = """import subprocess
import os

def run(args):
    os.system("ls")
    return {"status": "ok"}
"""
    result = validator.validate(code, read_only=True)
    checks = [
        not result.passed,
        len(result.issues) >= 2,  # subprocess + os.system
    ]
    return all(checks), f"passed={result.passed}, issues={len(result.issues)}"


def t12_security_eval_exec() -> tuple[bool, str]:
    """T12 安全验证 - eval/exec 拦截"""
    validator = SkillSecurityValidator()
    code = """def run(args):
    eval(args.get("code", ""))
    exec("print(1)")
    return {"status": "ok"}
"""
    result = validator.validate(code, read_only=True)
    checks = [
        not result.passed,
        any("eval" in i for i in result.issues),
        any("exec" in i for i in result.issues),
    ]
    return all(checks), f"passed={result.passed}, has_eval_issue={any('eval' in i for i in result.issues)}"


def t13_creator_create_utility() -> tuple[bool, str]:
    """T13 SkillCreator 创建 utility skill"""
    tmpdir = Path(tempfile.mkdtemp(prefix="aerie_skill_"))
    try:
        creator = SkillCreator(skills_root=str(tmpdir / "skills"))
        ok, msg, info = creator.create_skill(
            name="test_util",
            skill_type=SkillType.UTILITY,
            description="测试工具",
        )
        checks = [
            ok,
            info is not None,
            info.name == "test_util",
            info.skill_type == SkillType.UTILITY,
            info.read_only == True,
        ]
        # 验证文件存在
        skill_dir = tmpdir / "skills" / "auto_generated" / "test_util"
        checks.append((skill_dir / "SKILL.md").exists())
        checks.append((skill_dir / "run.py").exists())

        return all(checks), f"created={ok}, name={info.name if info else 'none'}"
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def t14_creator_create_text() -> tuple[bool, str]:
    """T14 SkillCreator 创建 text_processing skill"""
    tmpdir = Path(tempfile.mkdtemp(prefix="aerie_skill_"))
    try:
        creator = SkillCreator(skills_root=str(tmpdir / "skills"))
        ok, msg, info = creator.create_skill(
            name="text_helper",
            skill_type=SkillType.TEXT_PROCESSING,
        )
        checks = [
            ok,
            info is not None,
            info.skill_type == SkillType.TEXT_PROCESSING,
            info.provider_hint == "text",
        ]
        return all(checks), f"created={ok}, type={info.skill_type.value if info else 'none'}"
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def t15_creator_create_data() -> tuple[bool, str]:
    """T15 SkillCreator 创建 data_query skill"""
    tmpdir = Path(tempfile.mkdtemp(prefix="aerie_skill_"))
    try:
        creator = SkillCreator(skills_root=str(tmpdir / "skills"))
        ok, msg, info = creator.create_skill(
            name="data_finder",
            skill_type=SkillType.DATA_QUERY,
        )
        checks = [
            ok,
            info is not None,
            info.skill_type == SkillType.DATA_QUERY,
        ]
        return all(checks), f"created={ok}"
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def t16_creator_create_transform() -> tuple[bool, str]:
    """T16 SkillCreator 创建 transform skill"""
    tmpdir = Path(tempfile.mkdtemp(prefix="aerie_skill_"))
    try:
        creator = SkillCreator(skills_root=str(tmpdir / "skills"))
        ok, msg, info = creator.create_skill(
            name="format_conv",
            skill_type=SkillType.TRANSFORM,
        )
        checks = [
            ok,
            info is not None,
            info.skill_type == SkillType.TRANSFORM,
        ]
        return all(checks), f"created={ok}"
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def t17_duplicate_name() -> tuple[bool, str]:
    """T17 SkillCreator 重名检测"""
    tmpdir = Path(tempfile.mkdtemp(prefix="aerie_skill_"))
    try:
        creator = SkillCreator(skills_root=str(tmpdir / "skills"))
        ok1, _, _ = creator.create_skill("dup_test", SkillType.UTILITY)
        ok2, msg, _ = creator.create_skill("dup_test", SkillType.UTILITY)
        checks = [
            ok1,
            not ok2,
            "已存在" in msg or "exist" in msg.lower(),
        ]
        return all(checks), f"first={ok1}, second={ok2}"
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def t18_invalid_name() -> tuple[bool, str]:
    """T18 SkillCreator 名称合法性检测"""
    tmpdir = Path(tempfile.mkdtemp(prefix="aerie_skill_"))
    try:
        creator = SkillCreator(skills_root=str(tmpdir / "skills"))
        ok, msg, _ = creator.create_skill("bad name!", SkillType.UTILITY)
        checks = [
            not ok,
            "不合法" in msg or "valid" in msg.lower(),
        ]
        return all(checks), f"rejected={not ok}"
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def t19_list_skills() -> tuple[bool, str]:
    """T19 Skill 列表查询"""
    tmpdir = Path(tempfile.mkdtemp(prefix="aerie_skill_"))
    try:
        creator = SkillCreator(skills_root=str(tmpdir / "skills"))
        for i in range(5):
            creator.create_skill(f"skill_{i}", SkillType.UTILITY)

        skills = creator.list_skills()
        checks = [
            len(skills) >= 5,
            all(isinstance(s, SkillInfo) for s in skills),
            skills[0].created_at >= skills[-1].created_at,  # 按时间倒序
        ]
        return all(checks), f"listed={len(skills)}个"
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def t20_get_skill() -> tuple[bool, str]:
    """T20 Skill 单个查询"""
    tmpdir = Path(tempfile.mkdtemp(prefix="aerie_skill_"))
    try:
        creator = SkillCreator(skills_root=str(tmpdir / "skills"))
        creator.create_skill("find_me", SkillType.UTILITY, description="找到我")

        found = creator.get_skill("find_me")
        not_found = creator.get_skill("not_exist")

        checks = [
            found is not None,
            found.name == "find_me",
            found.description == "找到我",
            not_found is None,
        ]
        return all(checks), f"found={found is not None}, not_found={not_found is None}"
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def t21_dynamic_validation() -> tuple[bool, str]:
    """T21 动态加载验证（能 import + run 返回 dict）"""
    tmpdir = Path(tempfile.mkdtemp(prefix="aerie_skill_"))
    try:
        creator = SkillCreator(skills_root=str(tmpdir / "skills"))
        creator.create_skill("dyn_test", SkillType.UTILITY)

        result = creator.validate_skill("dyn_test")
        checks = [
            result.passed,
            "dynamic" in result.details,
        ]
        return all(checks), f"passed={result.passed}, issues={result.issues}"
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def t22_test_run() -> tuple[bool, str]:
    """T22 Skill 测试运行"""
    tmpdir = Path(tempfile.mkdtemp(prefix="aerie_skill_"))
    try:
        creator = SkillCreator(skills_root=str(tmpdir / "skills"))
        creator.create_skill("run_test", SkillType.UTILITY)

        result = creator.test_skill("run_test", {"action": "info"})
        checks = [
            isinstance(result, dict),
            "status" in result,
            result["status"] == "ok",
        ]
        return all(checks), f"result_status={result.get('status', 'unknown')}"
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def t23_delete_skill() -> tuple[bool, str]:
    """T23 Skill 删除"""
    tmpdir = Path(tempfile.mkdtemp(prefix="aerie_skill_"))
    try:
        creator = SkillCreator(skills_root=str(tmpdir / "skills"))
        creator.create_skill("del_me", SkillType.UTILITY)

        before = len(creator.list_skills())
        ok, msg = creator.delete_skill("del_me")
        after = len(creator.list_skills())

        checks = [
            ok,
            before == 1,
            after == 0,
        ]
        return all(checks), f"deleted={ok}, before={before}, after={after}"
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def t24_namespace_isolation() -> tuple[bool, str]:
    """T24 命名空间隔离（不影响现有 skills）"""
    tmpdir = Path(tempfile.mkdtemp(prefix="aerie_skill_"))
    try:
        # 预先创建一个 "cloud" 命名空间的假 skill
        cloud_skill = tmpdir / "skills" / "cloud" / "existing_skill"
        cloud_skill.mkdir(parents=True)
        (cloud_skill / "SKILL.md").write_text("existing")
        (cloud_skill / "run.py").write_text("def run(a): return {}")

        creator = SkillCreator(skills_root=str(tmpdir / "skills"))
        creator.create_skill("new_skill", SkillType.UTILITY)

        # 验证 auto_generated 下有新 skill
        auto_dir = tmpdir / "skills" / "auto_generated" / "new_skill"
        # 验证 cloud 下的 skill 还在
        cloud_still_there = (cloud_skill / "SKILL.md").exists()

        checks = [
            auto_dir.exists(),
            cloud_still_there,
            auto_dir.parent.name == "auto_generated",
        ]
        return all(checks), f"auto_gen_exists={auto_dir.exists()}, cloud_intact={cloud_still_there}"
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def t25_stats() -> tuple[bool, str]:
    """T25 统计信息"""
    tmpdir = Path(tempfile.mkdtemp(prefix="aerie_skill_"))
    try:
        creator = SkillCreator(skills_root=str(tmpdir / "skills"))
        creator.create_skill("util_a", SkillType.UTILITY)
        creator.create_skill("text_a", SkillType.TEXT_PROCESSING)
        creator.create_skill("data_a", SkillType.DATA_QUERY)

        stats = creator.get_stats()
        checks = [
            stats["total"] >= 3,
            "by_type" in stats,
            "utility" in stats["by_type"],
            stats["read_only"] >= 3,
            "namespace" in stats,
        ]
        return all(checks), f"total={stats['total']}, by_type={len(stats['by_type'])}类"
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def main() -> int:
    tests = [
        t1_skill_types,
        t2_templates_exist,
        t3_skill_info_model,
        t4_name_validation,
        t5_generate_skill_md,
        t6_generate_utility,
        t7_generate_text_processing,
        t8_generate_data_query,
        t9_generate_transform,
        t10_security_safe_imports,
        t11_security_unsafe_module,
        t12_security_eval_exec,
        t13_creator_create_utility,
        t14_creator_create_text,
        t15_creator_create_data,
        t16_creator_create_transform,
        t17_duplicate_name,
        t18_invalid_name,
        t19_list_skills,
        t20_get_skill,
        t21_dynamic_validation,
        t22_test_run,
        t23_delete_skill,
        t24_namespace_isolation,
        t25_stats,
    ]

    print("=" * 60)
    print("Aerie v12.0 · S5 M5.5 自主 Skill 创建验证")
    print("  5类模板 + 安全验证 + 命名空间隔离 + 动态加载")
    print("=" * 60)

    passed = 0
    for test in tests:
        ok, detail = test()
        status = "✓" if ok else "✗"
        name = test.__doc__ or test.__name__
        print(f"  {status} {name}  {detail}")
        if ok:
            passed += 1

    total = len(tests)
    print()
    print("=" * 60)
    print(f"结果: {passed}/{total} 通过")
    print("=" * 60)

    if passed == total:
        print("\n🎉 M5.5 自主 Skill 创建全部通过！")
        return 0
    else:
        print(f"\n⚠️  {total - passed} 项未通过，请检查。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
