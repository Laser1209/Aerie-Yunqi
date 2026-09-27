"""测试 QQ thought/action 标签过滤功能"""
import sys
sys.path.insert(0, "e:\\Agent_reply")

from communication.qq_client import strip_channel_markers, strip_thought_action_tags
from core.model_output import strip_narration


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


def test_narration_fullwidth_parens():
    """全角括号描写应被剥除（回归：括号描写曾 100% 直达用户）"""
    text = "（看到消息愣了一下，忍不住咬了咬下唇）……傻瓜。"
    assert strip_narration(text) == "……傻瓜。"
    print("✅ 全角括号描写剥除测试通过")


def test_narration_inline():
    """句中的括号描写同样剥除，保留对话"""
    text = "而且——（手指在屏幕上敲了一下）你给我起的名字？"
    result = strip_narration(text)
    assert "手指在屏幕上敲了一下" not in result
    assert "你给我起的名字？" in result
    print("✅ 句内括号描写剥除测试通过")


def test_narration_keeps_halfwidth():
    """半角括号不剥，避免误伤英文括注与代码片段"""
    text = "see foo() (note: not narration)"
    assert strip_narration(text) == text
    print("✅ 半角括号不误伤测试通过")


def test_narration_pure_returns_empty():
    """整条都是描写时返回空串，由调用方决定兜底"""
    assert strip_narration("（只是心理活动）") == ""
    print("✅ 纯描写返回空串测试通过")


def test_channel_markers_stripped_at_line_start():
    """回归：模型模仿历史格式把 [桌面]/[QQ] 回显给用户，必须剥除"""
    text = "[桌面] 照片我存了\n[QQ] 晚点发你"
    result = strip_channel_markers(text)
    assert "照片我存了" in result
    assert "晚点发你" in result
    for marker in ("[桌面]", "[QQ]", "[本地]", "[系统]"):
        assert marker not in result
    print("✅ 行首通道标记剥除测试通过")


def test_channel_markers_keep_inline_brackets():
    """只剥行首标记，正文中正当出现的方括号内容不误伤"""
    text = "我看了[桌面]版的说明，还行"
    assert strip_channel_markers(text) == text
    print("✅ 正文方括号不误伤测试通过")


def test_channel_markers_collapse_blank_lines():
    """整行只有标记时，剥除后产生的多余空行应收敛为单空行"""
    text = "第一句\n[本地] \n\n\n第二句"
    result = strip_channel_markers(text)
    assert "\n\n\n" not in result
    assert "第一句" in result
    assert "第二句" in result
    print("✅ 多余空行收敛测试通过")


def test_channel_markers_empty_input():
    """空输入原样返回"""
    assert strip_channel_markers("") == ""
    assert strip_channel_markers(None) is None
    print("✅ 通道标记空输入测试通过")


if __name__ == "__main__":
    test_basic()
    test_multiline()
    test_no_tags()
    test_only_thought()
    test_case_insensitive()
    test_empty_input()
    test_multiple_tags()
    test_narration_fullwidth_parens()
    test_narration_inline()
    test_narration_keeps_halfwidth()
    test_narration_pure_returns_empty()
    test_channel_markers_stripped_at_line_start()
    test_channel_markers_keep_inline_brackets()
    test_channel_markers_collapse_blank_lines()
    test_channel_markers_empty_input()
    print()
    print("🎉 所有测试通过！")
