"""Quick test for SendQueue batch interval calculation."""
import asyncio
import sys
import os
import logging

logging.basicConfig(level=logging.DEBUG, format='%(levelname)s: %(message)s')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from communication.send_queue import SendQueue
from communication.message import OutgoingReply
from communication.qq_client import strip_thought_action_tags
from config.persona_loader import get_message_batching_config


async def mock_sender(reply: OutgoingReply) -> bool:
    return True


async def main():
    cfg = get_message_batching_config()
    print("=== Message Batching Config ===")
    for k, v in cfg.items():
        print(f"  {k}: {v}")
    print()

    sq = SendQueue(sender=mock_sender)

    test_cases = [
        ("50 chars plain", "你好呀，今天过得怎么样？我这边天气很好，正在想着你在做什么呢。" * 1),
        ("150 chars plain", "你好呀，今天过得怎么样？我这边天气很好，正在想着你在做什么呢。" * 3),
        ("50 chars with tags", "<thought>他发了三条消息</thought>你好呀，今天过得怎么样？<action>看着屏幕微笑。</action>" + "我在想你。" * 5),
        ("empty after strip", "<thought>只是思考</thought><action>只是动作</action>"),
    ]

    print("=== Interval Calculation Test (emotion_label=None -> neutral balanced) ===")
    print()

    for name, content in test_cases:
        plain = strip_thought_action_tags(content)
        char_count = len(plain)

        interval, style = sq._compute_batch_interval(
            reply_content=content,
            emotion_label=None,
            threshold_summary={},
            is_eruption=False,
            batch_id="test-batch-001",
            sequence_index=1,
        )

        print(f"Test: {name}")
        print(f"  Content preview: {content[:60]}...")
        print(f"  Plain text ({char_count} chars): {plain[:60]}...")
        print(f"  Computed interval: {interval:.3f}s")
        print(f"  Style: {style}")
        print()

    print("=== Interval vs Char Count (proportionality check) ===")
    print()
    for n in [10, 25, 50, 75, 100, 150, 200, 300]:
        text = "你" * n
        interval, style = sq._compute_batch_interval(
            reply_content=text,
            emotion_label=None,
            threshold_summary={},
            is_eruption=False,
            batch_id=f"test-{n}",
            sequence_index=1,
        )
        print(f"  {n:>4} chars -> {interval:>6.3f}s  (style={style})")

    print()
    print("=== Emotion Factor Test (50 chars) ===")
    print()
    text50 = "你" * 50
    for emotion in [None, "joy", "neutral", "sad", "fear", "anger", "affection"]:
        interval, style = sq._compute_batch_interval(
            reply_content=text50,
            emotion_label=emotion,
            threshold_summary={},
            is_eruption=False,
            batch_id=f"emotion-{emotion}",
            sequence_index=1,
        )
        print(f"  emotion={emotion or 'None':<10} -> {interval:.3f}s  ({style})")


if __name__ == "__main__":
    asyncio.run(main())
