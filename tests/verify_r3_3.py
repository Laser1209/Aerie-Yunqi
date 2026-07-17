"""R3.3 临时验证：确认 skill_loader 能 discover + register 17 个 skill。"""
import sys
sys.path.insert(0, ".")

from core.skill_loader import SkillLoader
from core.skill_router import SkillRouter
from core.tool_registry import ToolRegistry

reg = ToolRegistry()
router = SkillRouter({"ai_options": [{"id": "main_llm", "model": "deepseek-chat"}]})
loader = SkillLoader(reg, router)
n_disc = loader.discover()
print(f"discovered: {n_disc}")
n_reg = loader.register_all()
print(f"registered: {n_reg}")
print("---")
for name, t in sorted(reg._tools.items()):
    print(f"  {name:24s} provider_hint={t['provider_hint']:18s} func={t['func'].__module__}")
print("---")
print(f"schema count: {len(reg.get_openai_schema())}")

# 调用一个 stub 验证
print("\n--- stub call test (tts, missing local_tts) ---")
result = loader.call("tts", {"text": "hello"})
print(result)
