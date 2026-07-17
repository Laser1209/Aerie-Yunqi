"""
Aerie v12.0 · S6 M6.2 Cognition Panel v2 验证
  5 个 Tab + 4 个能力面板 + 样式完整性
"""

import sys
from pathlib import Path


def main():
    passed = 0
    failed = 0
    issues = []

    def check(name, cond, detail=""):
        nonlocal passed, failed
        if cond:
            passed += 1
            print(f"  ✓ {name}  {detail}")
        else:
            failed += 1
            print(f"  ✗ {name}  {detail}")
            issues.append(name)

    base = Path(__file__).parent / "electron" / "src" / "renderer"
    html_path = base / "index.html"
    css_path = base / "styles" / "cognition-panel.css"
    js_path = base / "js" / "cognition-panel.js"

    print("=" * 60)
    print("Aerie v12.0 · S6 M6.2 Cognition Panel v2 验证")
    print("  5 Tab + 4 能力面板 + 样式/交互完整性")
    print("=" * 60)

    # ===== 文件存在 =====
    print()
    check("T1 HTML 存在", html_path.exists())
    check("T2 CSS 存在", css_path.exists())
    check("T3 JS 存在", js_path.exists())

    # ===== HTML 结构验证 =====
    print()
    html = html_path.read_text(encoding="utf-8")

    check("T4 5 个 Tab 按钮", html.count("data-cog-tab=") == 5)
    check("T5 brain Tab 存在", 'data-cog-tab="brain"' in html)
    check("T6 self-evolve Tab 存在", 'data-cog-tab="self-evolve"' in html)
    check("T7 computer Tab 存在", 'data-cog-tab="computer"' in html)
    check("T8 files Tab 存在", 'data-cog-tab="files"' in html)
    check("T9 docs Tab 存在", 'data-cog-tab="docs"' in html)

    check("T10 5 个 Tab Pane", html.count('class="cog-tab-pane') == 5)
    check("T11 brain pane", 'id="cog-pane-brain"' in html)
    check("T12 self-evolve pane", 'id="cog-pane-self-evolve"' in html)
    check("T13 computer pane", 'id="cog-pane-computer"' in html)
    check("T14 files pane", 'id="cog-pane-files"' in html)
    check("T15 docs pane", 'id="cog-pane-docs"' in html)

    # 自进化面板元素
    check("T16 自进化 Hero 统计", "cog-se-total" in html and "cog-se-applied" in html and "cog-se-rolled" in html)
    check("T17 生存闸门 4 个", html.count("cog-gate-card") == 4)
    check("T18 自进化列表", 'id="cog-se-list"' in html)
    check("T19 审计日志", 'id="cog-se-journal"' in html)

    # 电脑操控面板元素
    check("T20 电脑操控 Hero", "cog-cc-level" in html and "cog-cc-today" in html and "cog-cc-blocked" in html)
    check("T21 3 档权限", html.count("cog-cc-level") >= 4)  # 3 档 + hero
    check("T22 操作日志", 'id="cog-cc-log"' in html)
    check("T23 危险黑名单", 'id="cog-cc-blacklist"' in html)

    # 文件整理面板元素
    check("T24 文件整理 Hero", "cog-fo-organized" in html and "cog-fo-undoable" in html and "cog-fo-saved" in html)
    check("T25 4 个快速整理", html.count("cog-fo-quick-item") == 4)
    check("T26 整理历史", 'id="cog-fo-history"' in html)
    check("T27 撤销日志", 'id="cog-fo-undo"' in html)

    # 文档写作面板元素
    check("T28 文档写作 Hero", "cog-dw-count" in html and "cog-dw-templates" in html and "cog-dw-formats" in html)
    check("T29 5 个模板", html.count("cog-dw-tpl\"") == 5 or html.count("cog-dw-tpl") >= 5)
    check("T30 4 种导出格式", html.count("cog-dw-fmt\"") == 4 or html.count("cog-dw-fmt") >= 4)
    check("T31 文档列表", 'id="cog-dw-list"' in html)

    # 原有大脑中枢保留
    check("T32 9 阶段时间轴保留", 'id="cog-timeline"' in html)
    check("T33 决策赛马保留", 'id="cog-decision-race"' in html)
    check("T34 实时 stream 保留", 'id="cog-stream"' in html)
    check("T35 历史 trace 保留", 'id="cog-list"' in html)

    # ===== CSS 验证 =====
    print()
    css = css_path.read_text(encoding="utf-8")

    check("T36 Tab 导航样式", ".cog-tabs" in css)
    check("T37 Tab 按钮样式", ".cog-tab" in css)
    check("T38 Tab active 状态", ".cog-tab.active" in css)
    check("T39 Tab 内容容器", ".cog-tab-content" in css)
    check("T40 Tab 显隐", ".cog-tab-pane" in css and "display: none" in css)
    check("T41 Tab 淡入动画", "cogFadeIn" in css)

    check("T42 v2 Hero 样式", ".cog-v2-hero" in css)
    check("T43 v2 Stat 样式", ".cog-v2-stat" in css)

    check("T44 闸门卡片样式", ".cog-gates-grid" in css and ".cog-gate-card" in css)
    check("T45 闸门状态样式", "cog-gate-status--pass" in css)
    check("T46 自进化列表项", ".cog-se-item" in css)
    check("T47 自进化徽章", ".cog-se-item-badge" in css)

    check("T48 权限档位样式", ".cog-cc-levels" in css)
    check("T49 操作日志项", ".cog-cc-item" in css)
    check("T50 危险标签样式", ".cog-tag" in css)

    check("T51 快速整理样式", ".cog-fo-quick" in css and ".cog-fo-quick-item" in css)
    check("T52 整理记录项", ".cog-fo-item" in css)

    check("T53 文档模板样式", ".cog-dw-templates" in css and ".cog-dw-tpl" in css)
    check("T54 导出格式样式", ".cog-dw-formats" in css and ".cog-dw-fmt" in css)
    check("T55 文档列表项", ".cog-dw-item" in css)

    check("T56 响应式 900px", "@media (max-width: 900px)" in css)
    check("T57 响应式 600px", "@media (max-width: 600px)" in css)
    check("T58 暗色玻璃背景", "cog-glass-bg" in css)

    # ===== JS 验证 =====
    print()
    js = js_path.read_text(encoding="utf-8")

    check("T59 Tab 绑定方法", "_bindV2Tabs" in js)
    check("T60 刷新按钮绑定", "_bindV2Refresh" in js)
    check("T61 Demo 数据加载", "_loadV2DemoData" in js)
    check("T62 自进化数据加载", "_loadSelfEvolveData" in js)
    check("T63 电脑操控数据加载", "_loadComputerControlData" in js)
    check("T64 文件整理数据加载", "_loadFileOrganizerData" in js)
    check("T65 文档写作数据加载", "_loadDocWriterData" in js)

    check("T66 init 调用 v2 方法", "_bindV2Tabs()" in js and "_loadV2DemoData()" in js)
    check("T67 Tab 点击切换逻辑", "data.cogTab" in js or "dataset.cogTab" in js)
    check("T68 CognitionPanel 类完整", js.count("class CognitionPanel") == 1)
    check("T69 window 导出", "window.cognitionPanel" in js)

    # ===== 完整性 =====
    print()
    check("T70 5 个 Tab 都有图标", html.count("cog-tab-icon") == 5)
    check("T71 5 个 Tab 都有标签", html.count("cog-tab-label") == 5)
    check("T72 4 个能力面板有 Hero", html.count("cog-v2-hero-icon") == 4)
    check("T73 原有功能未破坏", "cognition-toolbar" in html)
    check("T74 proposal 卡片槽保留", "cog-proposal-card" in html)

    # ===== 结果 =====
    print()
    print("=" * 60)
    print(f"结果: {passed}/{passed+failed} 通过")
    print("=" * 60)
    if failed == 0:
        print("\n🎉 M6.2 Cognition Panel v2 全部通过！")
        print("   5 个 Tab 完整 · 4 个能力面板就绪 · 原有功能保留")
    else:
        print(f"\n⚠️  {failed} 项未通过: {issues}")

    return failed == 0


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
