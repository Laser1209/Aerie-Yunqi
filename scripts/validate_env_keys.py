"""Validate .env file structure for the 5 user-supplied AI provider keys."""
import re
from pathlib import Path

env_path = Path('e:/Agent_reply/.env')
content = env_path.read_text(encoding='utf-8')
lines = content.splitlines()

required_keys = {
    'DEEPSEEK_API_KEY':    ('deep',        '2daa6'),
    'MINIMAX_API_KEY':     ('minimax',     '1iE'),
    'BIGMODEL_API_KEY':    ('bigmodel',    'FTOQ'),
    'SILICONFLOW_API_KEY': ('siliconflow', 'snpo'),
    'OPENAI_API_KEY':      ('gpt',         'BuX'),
}

parsed = {}
for line in lines:
    s = line.strip()
    if not s or s.startswith('#') or '=' not in s:
        continue
    k, v = s.split('=', 1)
    k, v = k.strip(), v.strip()
    if re.match(r'^[A-Z][A-Z0-9_]*$', k) and not (v.startswith('your_') and v.endswith('_here')):
        parsed[k] = v

print('=== .env Structural Validation (round 2) ===')
print()
all_ok = True
for env_key, (label, expected_tail) in required_keys.items():
    val = parsed.get(env_key, '')
    if not val:
        print(f'[{label:12s}] {env_key:22s} MISSING')
        all_ok = False
        continue
    if ' ' in val or '\t' in val:
        print(f'[{label:12s}] {env_key:22s} CONTAINS WHITESPACE')
        all_ok = False
        continue
    if not val.endswith(expected_tail):
        print(f'[{label:12s}] {env_key:22s} TAIL MISMATCH (expected ends with: {expected_tail})')
        all_ok = False
        continue
    masked = val[:6] + '*' * (len(val) - 10) + val[-4:]
    print(f'[{label:12s}] {env_key:22s} OK   len={len(val):3d}  -> {masked}')

print()
print('OVERALL:', 'PASS' if all_ok else 'FAIL')
print()
print('--- All provider keys present (8 total) ---')
for k in ['DASHSCOPE_API_KEY', 'DEEPSEEK_API_KEY', 'GEMINI_API_KEY',
          'MINIMAX_API_KEY', 'BIGMODEL_API_KEY', 'SILICONFLOW_API_KEY', 'OPENAI_API_KEY']:
    v = parsed.get(k, '<missing>')
    if v == '<missing>':
        print(f'  {k:22s} MISSING')
    elif v.startswith('your_') and v.endswith('_here'):
        print(f'  {k:22s} placeholder (not yet filled)')
    else:
        masked = v[:6] + '*' * (len(v) - 10) + v[-4:]
        print(f'  {k:22s} {masked}  (len={len(v)})')
