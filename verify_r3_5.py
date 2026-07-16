"""R3.5 临时验证：brain 多 provider 入口 + safe_shell 白名单。"""
import sys
sys.path.insert(0, ".")

from core.brain import Brain

b = Brain()
print("--- ai_options ---")
opts = b.get_ai_options()
for o in opts:
    print(f"  {o.get('id'):16s} {o.get('label', ''):20s} model={o.get('model', '')}")
print(f"count: {len(opts)}")

print("\n--- generate_image stub ---")
print(b.generate_image("a girl in red"))

print("\n--- speak_text stub ---")
print(b.speak_text("嗨"))

print("\n--- see_image stub ---")
print(b.see_image("/tmp/x.png", "什么颜色？"))

print("\n--- safe_shell: whitelisted 'dir' ---")
r = b.safe_shell("dir", ["."])
print(f"returncode={r.get('returncode')}, stdout[:80]={r.get('stdout', '')[:80]!r}")

print("\n--- safe_shell: blocked 'rm' ---")
print(b.safe_shell("rm", ["-rf", "/"]))

print("\n--- safe_shell: empty command ---")
print(b.safe_shell("", []))

print("\n--- 旧 chat() / generate_push() 还在吗？ ---")
print(f"  chat: {hasattr(b, 'chat')}")
print(f"  generate_push: {hasattr(b, 'generate_push')}")
print(f"  compose_brief: {hasattr(b, 'compose_brief')}")
