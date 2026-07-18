"""测试 QQ thought/action 标签过滤功能"""
import sys
sys.path.insert(0, "e:\\Agent_reply")

from communication.qq_client import strip_thought_action_tags


def test_basic():
    """基础测试：只输出纯对话文本"""
    text = "你好呀～<thought>今天他好像心情不错，得温柔点回应</thought><action>指尖轻敲屏幕，嘴角上扬</action>我也想你了"
    result = strip_thought_action_tags(text)
    assert "你好呀～" in result
    assert "我也想你了" in result
    assert "<thought>" not in result
    assert "<action>" not in result
    assert "今天他好像心情不错" not in result
    assert "指尖轻敲屏幕" not in result
    print("✅ 基础测试通过")


def test_multiline():
    """跨行标签测试"""
    text = """开头说点啥呢
<thought>
他今天工作累不累啊
要不要关心一下
</thought>
今天工作辛苦啦～
<action>
伸了个懒腰
把手机贴在胸口
</action>
早点休息哦"""
    result = strip_thought_action_tags(text)
    assert "开头说点啥呢" in result
    assert "今天工作辛苦啦～" in result
    assert "早点休息哦" in result
    assert "<thought>" not in result
    assert "<action>" not in result
    assert "他今天工作累不累啊" not in result
    assert "伸了个懒腰" not in result
    print("✅ 跨行标签测试通过")


def test_no_tags():
    """没有标签的纯文本应该原样返回"""
    text = "这就是一段普通的对话，没有任何标签。"
    result = strip_thought_action_tags(text)
    assert result == text
    print("✅ 无标签纯文本测试通过")


def test_only_thought():
    """只有 thought 标签"""
    text = "<thought>全是心理活动</thought>"
    result = strip_thought_action_tags(text)
    assert result == ""
    print("✅ 纯 thought 标签测试通过")


def test_case_insensitive():
    """大小写不敏感"""
    text = "你好<THOUGHT>大写标签</Thought><ACTION>大写动作</action>再见"
    result = strip_thought_action_tags(text)
    assert "你好" in result
    assert "再见" in result
    assert "大写标签" not in result
    assert "大写动作" not in result
    print("✅ 大小写不敏感测试通过")


def test_empty_input():
    """空输入处理"""
    assert strip_thought_action_tags("") == ""
    assert strip_thought_action_tags(None) is None
    print("✅ 空输入测试通过")


def test_multiple_tags():
    """多个同类标签"""
    text = "开头<action>动作一</action>中间<action>动作二</action>结尾"
    result = strip_thought_action_tags(text)
    assert "开头" in result
    assert "中间" in result
    assert "结尾" in result
    assert "动作一" not in result
    assert "动作二" not in result
    print("✅ 多个同类标签测试通过")


if __name__ == "__main__":
    test_basic()
    test_multiline()
    test_no_tags()
    test_only_thought()
    test_case_insensitive()
    test_empty_input()
    test_multiple_tags()
    print()
    print("🎉 所有测试通过！")
