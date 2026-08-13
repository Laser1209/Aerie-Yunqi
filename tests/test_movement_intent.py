"""Tests for core.movement_intent — 对话移动意图识别（确定性规则）。"""
import unittest

from core.movement_intent import detect_move_intent


class MovementIntentTest(unittest.TestCase):
    def test_positive_cases(self):
        cases = {
            "你去沙发上坐会吧": "living",
            "到阳台拍张照给我": "balcony",
            "走去厨房看看": "kitchen",
            "回到卧室休息吧": "master_bedroom",
            "过来客厅陪我": "living",
            "躺到床上": "master_bedroom",
            "上二楼工作室帮我拿东西": "studio",
            "去窗前站着": "balcony",
            "你回主卧睡觉吧": "master_bedroom",
            "来阳台": "balcony",
            "去沙发": "living",
            "去洗手间洗个手": "guest_bath",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                intent = detect_move_intent(text)
                self.assertIsNotNone(intent, f"should detect intent in {text!r}")
                self.assertEqual(intent["zone"], expected)

    def test_negative_cases(self):
        # 无移动指令 / 询问类 / 用户自称移动，均不应触发。
        negatives = [
            "我今天去哪了",
            "你今天去哪儿了",
            "你到哪儿了",
            "我去做饭了",
            "明天一起去公园吧",
            "这家店在哪儿",
            "",
            None,
            123,
        ]
        for text in negatives:
            with self.subTest(text=text):
                self.assertIsNone(detect_move_intent(text))

    def test_query_not_move(self):
        # 询问位置不算移动指令
        self.assertIsNone(detect_move_intent("你现在在哪里"))
        self.assertIsNone(detect_move_intent("你刚才去哪了"))


if __name__ == "__main__":
    unittest.main()
