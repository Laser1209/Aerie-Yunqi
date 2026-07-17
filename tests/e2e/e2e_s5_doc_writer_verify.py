"""Aerie v12.0 · S5 M5.4 文档写作验证

验证项：
  T1 5 种文档类型定义
  T2 4 种导出格式定义
  T3 5 个模板存在
  T4 默认字段填充
  T5 Document 数据模型
  T6 日记模板渲染 (Markdown)
  T7 报告模板渲染 (Markdown)
  T8 技术规格模板渲染 (Markdown)
  T9 研究报告模板渲染 (Markdown)
  T10 简历模板渲染 (Markdown)
  T11 Markdown 转 HTML (标题/段落/列表/表格)
  T12 HTML 三种样式 (default/elegant/minimal)
  T13 HTML 行内格式 (加粗/斜体/代码)
  T14 HTML 引用块
  T15 HTML 代码块
  T16 DocWriter 创建文档
  T17 DocWriter 导出 Markdown
  T18 DocWriter 导出 HTML
  T19 DocWriter 导出 PDF (回退 HTML)
  T20 DocWriter 导出 DOCX (回退 MD)
  T21 获取模板字段
  T22 快速创建文档
  T23 列出已导出文档
  T24 文档 to_dict 序列化
  T25 长文档渲染性能
"""

from __future__ import annotations
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core.doc_writer import (
    DEFAULT_FIELDS,
    DOC_TEMPLATES,
    DOC_TYPE_NAMES,
    DocType,
    Document,
    DocWriter,
    ExportFormat,
)


def t1_doc_types() -> tuple[bool, str]:
    """T1 5 种文档类型定义"""
    types = list(DocType)
    expected = [DocType.DIARY, DocType.REPORT, DocType.SPEC,
                DocType.RESEARCH, DocType.RESUME]
    checks = [len(types) == 5]
    for t in expected:
        checks.append(t in types)
    return all(checks), f"5种: {[t.value for t in types]}"


def t2_export_formats() -> tuple[bool, str]:
    """T2 4 种导出格式定义"""
    fmts = list(ExportFormat)
    expected = [ExportFormat.MARKDOWN, ExportFormat.HTML,
                ExportFormat.PDF, ExportFormat.DOCX]
    checks = [len(fmts) == 4]
    for f in expected:
        checks.append(f in fmts)
    return all(checks), f"4种: {[f.value for f in fmts]}"


def t3_templates_exist() -> tuple[bool, str]:
    """T3 5 个模板存在"""
    checks = []
    for t in DocType:
        checks.append(t in DOC_TEMPLATES)
        checks.append(len(DOC_TEMPLATES[t]) > 100)
    return all(checks), f"templates={len(DOC_TEMPLATES)}个"


def t4_default_fields() -> tuple[bool, str]:
    """T4 默认字段填充"""
    checks = []
    for t in DocType:
        checks.append(t in DEFAULT_FIELDS)
        checks.append(len(DEFAULT_FIELDS[t]) >= 3)
    return all(checks), f"fields_per_type={len(DEFAULT_FIELDS[DocType.DIARY])}个起"


def t5_document_model() -> tuple[bool, str]:
    """T5 Document 数据模型"""
    doc = Document(
        doc_type=DocType.DIARY,
        title="测试日记",
        content="今天天气不错",
    )
    checks = [
        doc.doc_type == DocType.DIARY,
        doc.title == "测试日记",
        doc.type_name == "日记",
        isinstance(doc.created_at, float),
        hasattr(doc, "render_markdown"),
        hasattr(doc, "render_html"),
        hasattr(doc, "to_dict"),
    ]
    return all(checks), f"type_name={doc.type_name}"


def t6_diary_render_md() -> tuple[bool, str]:
    """T6 日记模板渲染 (Markdown)"""
    doc = Document(
        doc_type=DocType.DIARY,
        title="我的一天",
        content="今天学习了 Python。",
        fields={"mood": "开心", "weather": "晴"},
    )
    md = doc.render_markdown()
    checks = [
        "# 我的一天" in md,
        "今天学习了 Python" in md,
        "开心" in md,
        "晴" in md,
        "今日点滴" in md,
        "感悟与收获" in md,
        "明日计划" in md,
        "---" in md,
    ]
    return all(checks), f"len={len(md)}字"


def t7_report_render_md() -> tuple[bool, str]:
    """T7 报告模板渲染 (Markdown)"""
    doc = Document(
        doc_type=DocType.REPORT,
        title="项目周报",
        fields={
            "report_type": "周报",
            "author": "Etta",
            "version": "1.0",
        },
        content="本周完成了核心功能开发。",
    )
    md = doc.render_markdown()
    checks = [
        "# 项目周报" in md,
        "周报" in md,
        "Etta" in md,
        "摘要" in md,
        "背景" in md,
        "结论与建议" in md,
        "附录" in md,
    ]
    return all(checks), f"len={len(md)}字"


def t8_spec_render_md() -> tuple[bool, str]:
    """T8 技术规格模板渲染 (Markdown)"""
    doc = Document(
        doc_type=DocType.SPEC,
        title="用户系统",
        fields={"version": "2.0", "author": "Etta", "status": "草稿"},
        content="用户系统功能规格...",
    )
    md = doc.render_markdown()
    checks = [
        "用户系统" in md,
        "技术规格文档" in md,
        "系统架构" in md,
        "功能规格" in md,
        "接口定义" in md,
        "非功能需求" in md,
        "实施计划" in md,
    ]
    return all(checks), f"len={len(md)}字"


def t9_research_render_md() -> tuple[bool, str]:
    """T9 研究报告模板渲染 (Markdown)"""
    doc = Document(
        doc_type=DocType.RESEARCH,
        title="LLM 优化研究",
        fields={
            "topic": "大语言模型推理优化",
            "author": "研究员A",
        },
        content="详细研究内容...",
    )
    md = doc.render_markdown()
    checks = [
        "LLM 优化研究" in md,
        "研究报告" in md,
        "摘要" in md,
        "研究背景" in md,
        "研究方法" in md,
        "研究结论" in md,
        "参考文献" in md,
        "关键词" in md,
    ]
    return all(checks), f"len={len(md)}字"


def t10_resume_render_md() -> tuple[bool, str]:
    """T10 简历模板渲染 (Markdown)"""
    doc = Document(
        doc_type=DocType.RESUME,
        title="张三的简历",
        fields={
            "name": "张三",
            "position": "全栈工程师",
            "email": "zhangsan@example.com",
        },
    )
    md = doc.render_markdown()
    checks = [
        "张三" in md,
        "个人简介" in md,
        "工作经历" in md,
        "教育背景" in md,
        "技能专长" in md,
        "项目经历" in md,
        "全栈工程师" in md,
    ]
    return all(checks), f"len={len(md)}字"


def t11_md_to_html() -> tuple[bool, str]:
    """T11 Markdown 转 HTML (标题/段落/列表/表格)"""
    doc = Document(doc_type=DocType.REPORT, title="测试", content="")
    md = """# 一级标题

## 二级标题

普通段落。

- 列表项1
- 列表项2
- 列表项3

1. 有序1
2. 有序2

| 列1 | 列2 |
|---|---|
| a | b |
| c | d |

---

> 引用文字
"""
    # 直接测试 _markdown_to_html
    html = doc._markdown_to_html(md)
    checks = [
        "<h1>一级标题</h1>" in html,
        "<h2>二级标题</h2>" in html,
        "<p>普通段落。</p>" in html,
        "<ul>" in html and "</ul>" in html,
        "<ol>" in html and "</ol>" in html,
        "<table>" in html,
        "<th>列1</th>" in html,
        "<hr>" in html,
        "<blockquote>" in html,
    ]
    return all(checks), f"html_len={len(html)}"


def t12_html_styles() -> tuple[bool, str]:
    """T12 HTML 三种样式 (default/elegant/minimal)"""
    doc = Document(doc_type=DocType.DIARY, title="测试", content="内容")

    styles = ["default", "elegant", "minimal"]
    htmls = {}
    for s in styles:
        htmls[s] = doc.render_html(style=s)

    checks = [
        all("<!DOCTYPE html>" in htmls[s] for s in styles),
        all("<style>" in htmls[s] for s in styles),
        htmls["default"] != htmls["elegant"],
        htmls["elegant"] != htmls["minimal"],
    ]
    return all(checks), f"3 styles: {styles}"


def t13_html_inline_format() -> tuple[bool, str]:
    """T13 HTML 行内格式 (加粗/斜体/代码)"""
    doc = Document(doc_type=DocType.DIARY, title="测试", content="")
    html = doc._markdown_to_html("这是 **加粗** 和 *斜体* 还有 `代码`。")
    checks = [
        "<strong>加粗</strong>" in html,
        "<em>斜体</em>" in html,
        "<code>代码</code>" in html,
    ]
    return all(checks), "加粗/斜体/代码 均支持"


def t14_html_blockquote() -> tuple[bool, str]:
    """T14 HTML 引用块"""
    doc = Document(doc_type=DocType.DIARY, title="测试", content="")
    html = doc._markdown_to_html("> 这是引用\n> 多行引用")
    checks = [
        "<blockquote>" in html,
        "</blockquote>" in html,
        "这是引用" in html,
    ]
    return all(checks), "blockquote 渲染正常"


def t15_html_code_block() -> tuple[bool, str]:
    """T15 HTML 代码块"""
    doc = Document(doc_type=DocType.DIARY, title="测试", content="")
    html = doc._markdown_to_html("```python\ndef hello():\n    print('hi')\n```")
    checks = [
        "<pre><code>" in html,
        "</code></pre>" in html,
        "def hello" in html,
    ]
    return all(checks), "代码块渲染正常"


def t16_writer_create() -> tuple[bool, str]:
    """T16 DocWriter 创建文档"""
    tmpdir = Path(tempfile.mkdtemp(prefix="aerie_doc_"))
    try:
        writer = DocWriter(output_dir=str(tmpdir))
        doc = writer.create_document(
            DocType.DIARY,
            "测试日记",
            content="今天很开心",
            fields={"mood": "愉快"},
        )
        checks = [
            isinstance(doc, Document),
            doc.doc_type == DocType.DIARY,
            doc.title == "测试日记",
        ]
        return all(checks), f"created: {doc.title}"
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def t17_export_markdown() -> tuple[bool, str]:
    """T17 DocWriter 导出 Markdown"""
    tmpdir = Path(tempfile.mkdtemp(prefix="aerie_doc_"))
    try:
        writer = DocWriter(output_dir=str(tmpdir))
        doc = writer.create_document(DocType.DIARY, "测试日记", content="内容")
        path = writer.export(doc, ExportFormat.MARKDOWN)
        checks = [
            path.exists(),
            path.suffix == ".md",
            len(path.read_text(encoding="utf-8")) > 50,
        ]
        return all(checks), f"exported: {path.name}"
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def t18_export_html() -> tuple[bool, str]:
    """T18 DocWriter 导出 HTML"""
    tmpdir = Path(tempfile.mkdtemp(prefix="aerie_doc_"))
    try:
        writer = DocWriter(output_dir=str(tmpdir))
        doc = writer.create_document(DocType.REPORT, "测试报告", content="内容")
        path = writer.export(doc, ExportFormat.HTML, style="elegant")
        checks = [
            path.exists(),
            path.suffix == ".html",
            "<!DOCTYPE html>" in path.read_text(encoding="utf-8"),
        ]
        return all(checks), f"exported: {path.name}"
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def t19_export_pdf_fallback() -> tuple[bool, str]:
    """T19 DocWriter 导出 PDF (回退 HTML)"""
    tmpdir = Path(tempfile.mkdtemp(prefix="aerie_doc_"))
    try:
        writer = DocWriter(output_dir=str(tmpdir))
        doc = writer.create_document(DocType.DIARY, "测试", content="内容")
        path_str = writer.export(doc, ExportFormat.PDF)
        # 无 WeasyPrint 时回退为 HTML
        checks = [
            Path(path_str).exists(),
        ]
        return all(checks), f"exported: {Path(path_str).name}"
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def t20_export_docx_fallback() -> tuple[bool, str]:
    """T20 DocWriter 导出 DOCX (回退 MD)"""
    tmpdir = Path(tempfile.mkdtemp(prefix="aerie_doc_"))
    try:
        writer = DocWriter(output_dir=str(tmpdir))
        doc = writer.create_document(DocType.RESUME, "简历", content="内容")
        path_str = writer.export(doc, ExportFormat.DOCX)
        checks = [
            Path(path_str).exists(),
        ]
        return all(checks), f"exported: {Path(path_str).name}"
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def t21_get_template_fields() -> tuple[bool, str]:
    """T21 获取模板字段"""
    tmpdir = Path(tempfile.mkdtemp(prefix="aerie_doc_"))
    try:
        writer = DocWriter(output_dir=str(tmpdir))
        fields = writer.get_template_fields(DocType.DIARY)
        checks = [
            isinstance(fields, dict),
            "title" in fields,
            "mood" in fields,
            "weather" in fields,
        ]
        return all(checks), f"diary_fields={len(fields)}个"
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def t22_quick_create() -> tuple[bool, str]:
    """T22 快速创建文档"""
    tmpdir = Path(tempfile.mkdtemp(prefix="aerie_doc_"))
    try:
        writer = DocWriter(output_dir=str(tmpdir))
        doc = writer.quick_create(
            DocType.REPORT,
            "快速报告",
            content="快速内容",
            author="Etta",
            version="1.0",
        )
        checks = [
            doc.title == "快速报告",
            doc.fields.get("author") == "Etta",
            doc.fields.get("version") == "1.0",
        ]
        return all(checks), f"quick_created: {doc.title}"
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def t23_list_documents() -> tuple[bool, str]:
    """T23 列出已导出文档"""
    tmpdir = Path(tempfile.mkdtemp(prefix="aerie_doc_"))
    try:
        writer = DocWriter(output_dir=str(tmpdir))
        # 导出几个文档
        for i in range(3):
            doc = writer.create_document(DocType.DIARY, f"日记{i}", content="内容")
            writer.export(doc, ExportFormat.MARKDOWN)

        docs = writer.list_documents()
        checks = [
            len(docs) >= 3,
            all(isinstance(p, Path) for p in docs),
        ]
        return all(checks), f"listed={len(docs)}个文档"
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def t24_document_to_dict() -> tuple[bool, str]:
    """T24 文档 to_dict 序列化"""
    doc = Document(
        doc_type=DocType.SPEC,
        title="测试规格",
        content="内容",
        fields={"version": "1.0"},
    )
    d = doc.to_dict()
    checks = [
        isinstance(d, dict),
        d["doc_type"] == "spec",
        d["title"] == "测试规格",
        "fields" in d,
        "created_at" in d,
        "updated_at" in d,
    ]
    return all(checks), f"keys={list(d.keys())}"


def t25_long_doc_performance() -> tuple[bool, str]:
    """T25 长文档渲染性能"""
    import time
    content = "# 标题\n\n" + ("这是一段测试内容。" * 100 + "\n\n") * 50
    doc = Document(doc_type=DocType.REPORT, title="长文档", content=content)

    t0 = time.time()
    md = doc.render_markdown()
    t1 = time.time()
    html = doc.render_html()
    t2 = time.time()

    md_time = (t1 - t0) * 1000
    html_time = (t2 - t1) * 1000

    checks = [
        len(md) > 5000,
        len(html) > 5000,
        md_time < 1000,  # Markdown 渲染 < 1s
        html_time < 5000,  # HTML 渲染 < 5s
    ]
    return all(checks), f"md={md_time:.0f}ms, html={html_time:.0f}ms, chars={len(content)}"


def main() -> int:
    tests = [
        t1_doc_types,
        t2_export_formats,
        t3_templates_exist,
        t4_default_fields,
        t5_document_model,
        t6_diary_render_md,
        t7_report_render_md,
        t8_spec_render_md,
        t9_research_render_md,
        t10_resume_render_md,
        t11_md_to_html,
        t12_html_styles,
        t13_html_inline_format,
        t14_html_blockquote,
        t15_html_code_block,
        t16_writer_create,
        t17_export_markdown,
        t18_export_html,
        t19_export_pdf_fallback,
        t20_export_docx_fallback,
        t21_get_template_fields,
        t22_quick_create,
        t23_list_documents,
        t24_document_to_dict,
        t25_long_doc_performance,
    ]

    print("=" * 60)
    print("Aerie v12.0 · S5 M5.4 文档写作验证")
    print("  5类文档 + 4种导出 + 3种样式")
    print("=" * 60)

    passed = 0
    for test in tests:
        ok, detail = test()
        status = "✓" if ok else "✗"
        name = test.__doc__ or test.__name__
        print(f"  {status} {name}  {detail}")
        if ok:
            passed += 1

    total = len(tests)
    print()
    print("=" * 60)
    print(f"结果: {passed}/{total} 通过")
    print("=" * 60)

    if passed == total:
        print("\n🎉 M5.4 文档写作全部通过！")
        return 0
    else:
        print(f"\n⚠️  {total - passed} 项未通过，请检查。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
