"""Smoke test for B2 收尾 — persona_pacing + send_queue."""
import sys
sys.path.insert(0, '.')

from core.persona_pacing import compute_persona_interval

print('SendQueue imports OK')

# Quick functional check
for i in range(5):
    iv, style = compute_persona_interval(i, emotion_label='joy')
    print(f'seg {i}: {iv:.2f}s [{style}]')

print()
print('--- sad ---')
for i in range(5):
    iv, style = compute_persona_interval(i, emotion_label='sad')
    print(f'seg {i}: {iv:.2f}s [{style}]')

print()
print('--- neutral (balanced baseline) ---')
for i in range(5):
    iv, style = compute_persona_interval(i, emotion_label='neutral')
    print(f'seg {i}: {iv:.2f}s [{style}]')

print()
print('--- eruption (anxiety active) ---')
threshold = {"anxiety": {"active": True, "value": 100}}
for i in range(5):
    iv, style = compute_persona_interval(i, emotion_label='neutral', threshold=threshold, is_eruption=True)
    print(f'seg {i}: {iv:.2f}s [{style}]')
