"""Aerie v12.0 · 自主 Skill 创建器

功能：
  - 模板化生成 Skill（SKILL.md + run.py）
  - 自动注册到命名空间（auto_generated 目录隔离）
  - 命名空间隔离（不会污染现有 skills）
  - 加载验证（导入 + 基本调用测试）
  - Skill 元数据管理（列表/查询/删除）
  - 安全沙箱（白名单导入、只读标记）

Skill 模板类型：
  - utility: 通用工具型
  - text_processing: 文本处理型
  - data_query: 数据查询型
  - transform: 格式转换型
"""

from __future__ import annotations
import os
import re
import sys
import json
import time
import shutil
import logging
from pathlib import Path
from enum import Enum
from typing import Any, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class SkillType(str, Enum):
    """Skill 类型"""
    UTILITY = "utility"           # 通用工具
    TEXT_PROCESSING = "text_processing"  # 文本处理
    DATA_QUERY = "data_query"     # 数据查询
    TRANSFORM = "transform"       # 格式转换
    CUSTOM = "custom"             # 自定义


class SkillNamespace(str, Enum):
    """命名空间"""
    AUTO_GENERATED = "auto_generated"  # AI 自动生成（隔离区）
    USER = "user"                      # 用户创建


# Skill 类型 → 模板
SKEL_TEMPLATES = {
    SkillType.UTILITY: {
        "description_template": "{name}工具 Skill",
        "default_read_only": True,
        "default_provider_hint": "utility",
    },
    SkillType.TEXT_PROCESSING: {
        "description_template": "文本处理 - {name}",
        "default_read_only": True,
        "default_provider_hint": "text",
    },
    SkillType.DATA_QUERY: {
        "description_template": "数据查询 - {name}",
        "default_read_only": True,
        "default_provider_hint": "data",
    },
    SkillType.TRANSFORM: {
        "description_template": "格式转换 - {name}",
        "default_read_only": True,
        "default_provider_hint": "transform",
    },
    SkillType.CUSTOM: {
        "description_template": "{name}",
        "default_read_only": False,
        "default_provider_hint": "custom",
    },
}


# 安全白名单：允许在 run.py 中导入的模块
SAFE_IMPORTS = {
    "re", "json", "math", "time", "datetime", "hashlib",
    "collections", "itertools", "functools", "pathlib",
    "typing", "dataclasses", "enum", "string",
    "base64", "urllib.parse",
    "logging", "__future__",
}


@dataclass
class SkillInfo:
    """Skill 信息"""
    name: str
    namespace: str
    skill_type: SkillType
    description: str
    read_only: bool
    provider_hint: str
    path: str
    created_at: float
    version: str = "1.0.0"
    author: str = "aie_auto"
    tags: list[str] = field(default_factory=list)

    @property
    def full_name(self) -> str:
        return f"{self.namespace}/{self.name}"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "namespace": self.namespace,
            "full_name": self.full_name,
            "type": self.skill_type.value,
            "description": self.description,
            "read_only": self.read_only,
            "provider_hint": self.provider_hint,
            "path": self.path,
            "created_at": self.created_at,
            "version": self.version,
            "author": self.author,
            "tags": self.tags,
        }


@dataclass
class SkillValidationResult:
    """Skill 验证结果"""
    passed: bool
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "issues": self.issues,
            "warnings": self.warnings,
            "details": self.details,
        }


class SkillCodeGenerator:
    """Skill 代码生成器"""

    def generate_skill_md(self, name: str, description: str,
                          read_only: bool, provider_hint: str,
                          skill_type: SkillType,
                          version: str = "1.0.0",
                          author: str = "aie_auto",
                          tags: Optional[list[str]] = None) -> str:
        """生成 SKILL.md 内容"""
        tags_str = ", ".join(tags) if tags else skill_type.value
        return f"""---
name: {name}
description: {description}
provider_hint: {provider_hint}
read_only: {str(read_only).lower()}
version: {version}
author: {author}
tags: [{tags_str}]
created_at: {time.strftime('%Y-%m-%d')}
---

# {name}

{description}

## 入参

- `input`: 主要输入参数
- 其余键透传至 run() 函数

## 出参

- 成功：`{{"status": "ok", "result": ...}}`
- 失败：`{{"status": "error", "error": "..."}}`

## 安全

- read_only = `{str(read_only).lower()}`
- 仅使用标准库白名单模块
- 不访问外部网络
- 不修改系统状态

## 示例

```python
result = run({{"input": "value"}})
```
"""

    def generate_run_py(self, name: str, description: str,
                        skill_type: SkillType,
                        read_only: bool = True,
                        custom_code: Optional[str] = None) -> str:
        """生成 run.py 内容"""

        if custom_code:
            return self._wrap_custom_code(name, description, custom_code, read_only)

        # 根据类型生成模板代码
        if skill_type == SkillType.UTILITY:
            code = self._utility_template(name)
        elif skill_type == SkillType.TEXT_PROCESSING:
            code = self._text_processing_template(name)
        elif skill_type == SkillType.DATA_QUERY:
            code = self._data_query_template(name)
        elif skill_type == SkillType.TRANSFORM:
            code = self._transform_template(name)
        else:
            code = self._custom_template(name)

        return code

    def _wrap_custom_code(self, name: str, description: str,
                          code: str, read_only: bool) -> str:
        """包装自定义代码"""
        return f'''"""{name} skill — {description}.

Auto-generated by Aerie Skill Creator.
"""
from __future__ import annotations
import logging
logger = logging.getLogger(__name__)

PROVIDER_HINT = "custom"
READ_ONLY = {str(read_only).lower()}


{code}


def run(args: dict) -> dict:
    """Skill entry point."""
    args = args or {{}}
    try:
        return _execute(args)
    except Exception as e:
        logger.error(f"Skill {name} error: {{e}}")
        return {{"status": "error", "error": str(e)}}


def _execute(args: dict) -> dict:
    """Main logic."""
    input_val = args.get("input", args.get("text", ""))
    result = process(input_val, args)
    return {{"status": "ok", "result": result}}
'''

    def _utility_template(self, name: str) -> str:
        return f'''"""{name} skill — 通用工具.

Auto-generated by Aerie Skill Creator.
"""
from __future__ import annotations
import logging
import hashlib
import time
logger = logging.getLogger(__name__)

PROVIDER_HINT = "utility"
READ_ONLY = True


def run(args: dict) -> dict:
    """Skill entry point."""
    args = args or {{}}
    action = args.get("action", "info")

    try:
        if action == "hash":
            text = str(args.get("input", ""))
            algo = args.get("algorithm", "md5")
            h = hashlib.new(algo)
            h.update(text.encode("utf-8"))
            return {{"status": "ok", "result": h.hexdigest(), "algorithm": algo}}

        elif action == "timestamp":
            fmt = args.get("format", "%Y-%m-%d %H:%M:%S")
            ts = args.get("timestamp", time.time())
            return {{"status": "ok", "result": time.strftime(fmt, time.localtime(ts))}}

        elif action == "info":
            return {{"status": "ok", "result": {{"name": "{name}", "type": "utility", "actions": ["hash", "timestamp", "info"]}}}}

        else:
            return {{"status": "error", "error": f"unknown action: {{action}}"}}

    except Exception as e:
        logger.error(f"Skill {name} error: {{e}}")
        return {{"status": "error", "error": str(e)}}
'''

    def _text_processing_template(self, name: str) -> str:
        return f'''"""{name} skill — 文本处理.

Auto-generated by Aerie Skill Creator.
"""
from __future__ import annotations
import logging
import re
logger = logging.getLogger(__name__)

PROVIDER_HINT = "text"
READ_ONLY = True


def run(args: dict) -> dict:
    """Skill entry point."""
    args = args or {{}}
    text = args.get("input", args.get("text", ""))
    action = args.get("action", "count")

    try:
        if action == "count":
            return {{"status": "ok", "result": {{
                "chars": len(text),
                "words": len(text.split()),
                "lines": len(text.splitlines()),
            }}}}

        elif action == "reverse":
            return {{"status": "ok", "result": text[::-1]}}

        elif action == "upper":
            return {{"status": "ok", "result": text.upper()}}

        elif action == "lower":
            return {{"status": "ok", "result": text.lower()}}

        elif action == "strip":
            return {{"status": "ok", "result": text.strip()}}

        elif action == "word_count":
            return {{"status": "ok", "result": len(text.split())}}

        elif action == "replace":
            old = args.get("old", "")
            new = args.get("new", "")
            return {{"status": "ok", "result": text.replace(old, new)}}

        elif action == "find_all":
            pattern = args.get("pattern", "")
            matches = re.findall(pattern, text)
            return {{"status": "ok", "result": matches, "count": len(matches)}}

        else:
            return {{"status": "error", "error": f"unknown action: {{action}}"}}

    except Exception as e:
        logger.error(f"Skill {name} error: {{e}}")
        return {{"status": "error", "error": str(e)}}
'''

    def _data_query_template(self, name: str) -> str:
        return f'''"""{name} skill — 数据查询.

Auto-generated by Aerie Skill Creator.
"""
from __future__ import annotations
import logging
import json
logger = logging.getLogger(__name__)

PROVIDER_HINT = "data"
READ_ONLY = True


def run(args: dict) -> dict:
    """Skill entry point."""
    args = args or {{}}
    action = args.get("action", "query")
    data = args.get("data", [])
    query = args.get("query", "")

    try:
        if action == "query":
            results = []
            for item in data:
                if isinstance(item, dict):
                    item_str = json.dumps(item, ensure_ascii=False)
                else:
                    item_str = str(item)
                if query.lower() in item_str.lower():
                    results.append(item)
            return {{"status": "ok", "result": results, "count": len(results)}}

        elif action == "filter":
            key = args.get("key", "")
            value = args.get("value", "")
            results = []
            for item in data:
                if isinstance(item, dict) and item.get(key) == value:
                    results.append(item)
            return {{"status": "ok", "result": results, "count": len(results)}}

        elif action == "sort":
            key = args.get("key", "")
            reverse = args.get("reverse", False)
            if key and data and isinstance(data[0], dict):
                sorted_data = sorted(data, key=lambda x: x.get(key, ""), reverse=reverse)
            else:
                sorted_data = sorted(data, reverse=reverse)
            return {{"status": "ok", "result": sorted_data}}

        elif action == "stats":
            if data and isinstance(data[0], (int, float)):
                nums = [x for x in data if isinstance(x, (int, float))]
                return {{"status": "ok", "result": {{
                    "count": len(nums),
                    "sum": sum(nums),
                    "avg": sum(nums) / len(nums) if nums else 0,
                    "min": min(nums) if nums else 0,
                    "max": max(nums) if nums else 0,
                }}}}
            else:
                return {{"status": "ok", "result": {{"count": len(data)}}}}

        else:
            return {{"status": "error", "error": f"unknown action: {{action}}"}}

    except Exception as e:
        logger.error(f"Skill {name} error: {{e}}")
        return {{"status": "error", "error": str(e)}}
'''

    def _transform_template(self, name: str) -> str:
        return f'''"""{name} skill — 格式转换.

Auto-generated by Aerie Skill Creator.
"""
from __future__ import annotations
import logging
import json
import base64
logger = logging.getLogger(__name__)

PROVIDER_HINT = "transform"
READ_ONLY = True


def run(args: dict) -> dict:
    """Skill entry point."""
    args = args or {{}}
    data = args.get("input", args.get("data", ""))
    fmt = args.get("format", "json")
    direction = args.get("direction", "encode")  # encode / decode

    try:
        if fmt == "json":
            if direction == "encode":
                return {{"status": "ok", "result": json.dumps(data, ensure_ascii=False, indent=2)}}
            else:
                if isinstance(data, str):
                    return {{"status": "ok", "result": json.loads(data)}}
                else:
                    return {{"status": "error", "error": "decode 时 input 必须是字符串"}}

        elif fmt == "base64":
            if direction == "encode":
                encoded = base64.b64encode(str(data).encode("utf-8")).decode("utf-8")
                return {{"status": "ok", "result": encoded}}
            else:
                if isinstance(data, str):
                    decoded = base64.b64decode(data).decode("utf-8")
                    return {{"status": "ok", "result": decoded}}
                else:
                    return {{"status": "error", "error": "decode 时 input 必须是字符串"}}

        elif fmt == "list":
            if direction == "encode":
                if isinstance(data, str):
                    sep = args.get("separator", ",")
                    return {{"status": "ok", "result": data.split(sep)}}
                else:
                    return {{"status": "error", "error": "input 必须是字符串"}}
            else:
                if isinstance(data, list):
                    sep = args.get("separator", ", ")
                    return {{"status": "ok", "result": sep.join(str(x) for x in data)}}
                else:
                    return {{"status": "error", "error": "decode 时 input 必须是列表"}}

        else:
            return {{"status": "error", "error": f"unsupported format: {{fmt}}"}}

    except Exception as e:
        logger.error(f"Skill {name} error: {{e}}")
        return {{"status": "error", "error": str(e)}}
'''

    def _custom_template(self, name: str) -> str:
        return f'''"""{name} skill — 自定义.

Auto-generated by Aerie Skill Creator.
"""
from __future__ import annotations
import logging
logger = logging.getLogger(__name__)

PROVIDER_HINT = "custom"
READ_ONLY = False


def run(args: dict) -> dict:
    """Skill entry point."""
    args = args or {{}}
    try:
        result = process(args)
        return {{"status": "ok", "result": result}}
    except Exception as e:
        logger.error(f"Skill {name} error: {{e}}")
        return {{"status": "error", "error": str(e)}}


def process(args: dict) -> dict:
    """Custom processing logic.

    Replace this function with your own implementation.
    """
    return {{
        "message": "Custom skill template - implement your logic here",
        "input_keys": list(args.keys()),
    }}
'''


class SkillSecurityValidator:
    """Skill 安全验证器"""

    def __init__(self, safe_imports: Optional[set[str]] = None):
        self.safe_imports = safe_imports or SAFE_IMPORTS

    def validate(self, code: str, read_only: bool = True) -> SkillValidationResult:
        """验证 Skill 代码安全性"""
        issues = []
        warnings = []

        # 检查导入
        imports = self._extract_imports(code)
        unsafe_imports = []
        for imp in imports:
            top_module = imp.split(".")[0]
            if top_module not in self.safe_imports:
                unsafe_imports.append(imp)

        if unsafe_imports:
            issues.append(f"使用了非白名单模块: {', '.join(unsafe_imports)}")

        # 检查危险操作
        dangerous_patterns = [
            (r"eval\s*\(", "使用了 eval()"),
            (r"exec\s*\(", "使用了 exec()"),
            (r"__import__\s*\(", "使用了 __import__()"),
            (r"subprocess\.", "调用了 subprocess"),
            (r"os\.system\s*\(", "调用了 os.system()"),
            (r"os\.popen\s*\(", "调用了 os.popen()"),
            (r"open\s*\(", "文件操作 open()"),
            (r"socket\.", "网络操作 socket"),
            (r"requests\.", "网络请求 requests"),
            (r"urllib\.request", "网络请求 urllib.request"),
            (r"rmtree\s*\(", "删除目录 shutil.rmtree"),
            (r"remove\s*\(", "删除文件 os.remove"),
            (r"unlink\s*\(", "删除文件 os.unlink"),
        ]

        for pattern, desc in dangerous_patterns:
            if re.search(pattern, code):
                if read_only:
                    issues.append(f"read_only 模式下不允许: {desc}")
                else:
                    warnings.append(f"注意: {desc}")

        # 检查是否有 run 函数
        if not re.search(r"def\s+run\s*\(\s*args\s*:\s*dict\s*\)", code):
            warnings.append("未找到标准 run(args: dict) 函数签名")

        passed = len(issues) == 0
        return SkillValidationResult(
            passed=passed,
            issues=issues,
            warnings=warnings,
            details={"imports": imports, "unsafe_imports": unsafe_imports},
        )

    def _extract_imports(self, code: str) -> list[str]:
        """提取代码中的 import"""
        imports = []
        # import xxx
        for match in re.finditer(r"^\s*import\s+([a-zA-Z0-9_.]+)", code, re.MULTILINE):
            imports.append(match.group(1))
        # from xxx import yyy
        for match in re.finditer(r"^\s*from\s+([a-zA-Z0-9_.]+)\s+import", code, re.MULTILINE):
            imports.append(match.group(1))
        return imports


class SkillCreator:
    """Skill 创建器（主入口）

    模板化生成、自动注册、命名空间隔离、加载验证。
    """

    def __init__(
        self,
        skills_root: str = "skills",
        auto_gen_namespace: str = "auto_generated",
    ):
        self.skills_root = Path(skills_root)
        self.auto_gen_namespace = auto_gen_namespace
        self.generator = SkillCodeGenerator()
        self.validator = SkillSecurityValidator()

        # 确保自动生成目录存在
        self._auto_gen_dir = self.skills_root / auto_gen_namespace
        self._auto_gen_dir.mkdir(parents=True, exist_ok=True)

        # 注册表文件
        self._registry_file = self._auto_gen_dir / "_registry.json"
        self._registry: dict[str, dict] = {}
        self._load_registry()

    def _load_registry(self) -> None:
        """加载注册表"""
        if self._registry_file.exists():
            try:
                self._registry = json.loads(self._registry_file.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"加载 Skill 注册表失败: {e}")
                self._registry = {}

    def _save_registry(self) -> None:
        """保存注册表"""
        self._registry_file.write_text(
            json.dumps(self._registry, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def create_skill(
        self,
        name: str,
        skill_type: SkillType = SkillType.UTILITY,
        description: str = "",
        read_only: Optional[bool] = None,
        provider_hint: str = "",
        custom_code: Optional[str] = None,
        tags: Optional[list[str]] = None,
        version: str = "1.0.0",
    ) -> tuple[bool, str, Optional[SkillInfo]]:
        """创建一个新的 Skill

        Returns:
            (是否成功, 消息, SkillInfo)
        """
        # 名称校验
        if not self._validate_name(name):
            return False, f"Skill 名称不合法: {name}（仅允许字母数字下划线）", None

        # 检查重名
        if name in self._registry:
            return False, f"Skill 已存在: {name}", None

        # 默认值
        template_info = SKEL_TEMPLATES.get(skill_type, SKEL_TEMPLATES[SkillType.CUSTOM])
        if read_only is None:
            read_only = template_info["default_read_only"]
        if not description:
            description = template_info["description_template"].format(name=name)
        if not provider_hint:
            provider_hint = template_info["default_provider_hint"]

        # 生成代码
        skill_md = self.generator.generate_skill_md(
            name=name,
            description=description,
            read_only=read_only,
            provider_hint=provider_hint,
            skill_type=skill_type,
            version=version,
            tags=tags or [skill_type.value],
        )

        run_py = self.generator.generate_run_py(
            name=name,
            description=description,
            skill_type=skill_type,
            read_only=read_only,
            custom_code=custom_code,
        )

        # 安全验证
        if custom_code:
            validation = self.validator.validate(run_py, read_only=read_only)
            if not validation.passed:
                return False, f"安全验证失败: {'; '.join(validation.issues)}", None

        # 创建目录和文件
        skill_dir = self._auto_gen_dir / name
        skill_dir.mkdir(parents=True, exist_ok=True)

        (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")
        (skill_dir / "run.py").write_text(run_py, encoding="utf-8")

        # 注册
        info = SkillInfo(
            name=name,
            namespace=self.auto_gen_namespace,
            skill_type=skill_type,
            description=description,
            read_only=read_only,
            provider_hint=provider_hint,
            path=str(skill_dir),
            created_at=time.time(),
            version=version,
            tags=tags or [skill_type.value],
        )

        self._registry[name] = info.to_dict()
        self._save_registry()

        return True, f"Skill 创建成功: {name}", info

    def validate_skill(self, name: str) -> SkillValidationResult:
        """验证已存在的 Skill"""
        skill_dir = self._auto_gen_dir / name
        run_py_path = skill_dir / "run.py"

        if not run_py_path.exists():
            return SkillValidationResult(
                passed=False,
                issues=[f"run.py 不存在: {name}"],
            )

        code = run_py_path.read_text(encoding="utf-8")
        read_only = self._registry.get(name, {}).get("read_only", True)

        static_result = self.validator.validate(code, read_only=read_only)

        # 动态加载测试
        dynamic_result = self._dynamic_validate(skill_dir)
        if not dynamic_result.passed:
            static_result.issues.extend(dynamic_result.issues)
            static_result.passed = False

        static_result.details["dynamic"] = dynamic_result.details
        return static_result

    def _dynamic_validate(self, skill_dir: Path) -> SkillValidationResult:
        """动态加载验证"""
        run_py = skill_dir / "run.py"
        if not run_py.exists():
            return SkillValidationResult(passed=False, issues=["run.py 不存在"])

        try:
            # 添加临时路径
            skill_path = str(skill_dir)
            if skill_path not in sys.path:
                sys.path.insert(0, skill_path)

            import importlib.util
            spec = importlib.util.spec_from_file_location("skill_run", run_py)
            if spec is None or spec.loader is None:
                return SkillValidationResult(passed=False, issues=["无法创建模块 spec"])

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # 检查是否有 run 函数
            if not hasattr(module, "run"):
                return SkillValidationResult(passed=False, issues=["缺少 run() 函数"])

            # 测试基本调用
            result = module.run({"action": "info"})
            if not isinstance(result, dict):
                return SkillValidationResult(
                    passed=False,
                    issues=["run() 返回值不是 dict"],
                )

            return SkillValidationResult(
                passed=True,
                details={"run_result_type": type(result).__name__},
            )

        except Exception as e:
            return SkillValidationResult(
                passed=False,
                issues=[f"动态加载失败: {e}"],
            )

    def list_skills(self) -> list[SkillInfo]:
        """列出所有自动生成的 Skill"""
        skills = []
        for name, data in self._registry.items():
            try:
                skills.append(SkillInfo(
                    name=data["name"],
                    namespace=data["namespace"],
                    skill_type=SkillType(data.get("type", "custom")),
                    description=data.get("description", ""),
                    read_only=data.get("read_only", True),
                    provider_hint=data.get("provider_hint", ""),
                    path=data.get("path", ""),
                    created_at=data.get("created_at", 0),
                    version=data.get("version", "1.0.0"),
                    tags=data.get("tags", []),
                ))
            except Exception:
                continue
        return sorted(skills, key=lambda s: s.created_at, reverse=True)

    def get_skill(self, name: str) -> Optional[SkillInfo]:
        """获取单个 Skill 信息"""
        if name not in self._registry:
            return None
        data = self._registry[name]
        return SkillInfo(
            name=data["name"],
            namespace=data["namespace"],
            skill_type=SkillType(data.get("type", "custom")),
            description=data.get("description", ""),
            read_only=data.get("read_only", True),
            provider_hint=data.get("provider_hint", ""),
            path=data.get("path", ""),
            created_at=data.get("created_at", 0),
            version=data.get("version", "1.0.0"),
            tags=data.get("tags", []),
        )

    def delete_skill(self, name: str) -> tuple[bool, str]:
        """删除 Skill"""
        if name not in self._registry:
            return False, f"Skill 不存在: {name}"

        skill_dir = self._auto_gen_dir / name
        if skill_dir.exists():
            shutil.rmtree(skill_dir)

        del self._registry[name]
        self._save_registry()

        return True, f"Skill 已删除: {name}"

    def test_skill(self, name: str, args: Optional[dict] = None) -> dict:
        """测试运行 Skill"""
        skill_dir = self._auto_gen_dir / name
        run_py = skill_dir / "run.py"

        if not run_py.exists():
            return {"status": "error", "error": f"Skill 不存在: {name}"}

        try:
            skill_path = str(skill_dir)
            if skill_path not in sys.path:
                sys.path.insert(0, skill_path)

            import importlib.util
            spec = importlib.util.spec_from_file_location(f"skill_{name}", run_py)
            if spec is None or spec.loader is None:
                return {"status": "error", "error": "无法加载模块"}

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            if not hasattr(module, "run"):
                return {"status": "error", "error": "缺少 run() 函数"}

            result = module.run(args or {})
            return result

        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _validate_name(self, name: str) -> bool:
        """验证 Skill 名称"""
        if not name or len(name) > 50:
            return False
        return bool(re.match(r"^[a-zA-Z][a-zA-Z0-9_-]*$", name))

    def get_stats(self) -> dict:
        """获取统计信息"""
        skills = self.list_skills()
        by_type: dict[str, int] = {}
        for s in skills:
            t = s.skill_type.value
            by_type[t] = by_type.get(t, 0) + 1

        read_only_count = sum(1 for s in skills if s.read_only)

        return {
            "total": len(skills),
            "by_type": by_type,
            "read_only": read_only_count,
            "writable": len(skills) - read_only_count,
            "namespace": self.auto_gen_namespace,
        }
