---
name: obsidian-markdown
description: Obsidian Markdown / Obsidian MD
provider_hint: text
read_only: true
kind: instruction
triggers:
- wikilink
- obsidian 笔记
- obsidian 语法
- 双链笔记
- callout
- 笔记属性
- 库内链接
---
# Obsidian Flavored Markdown（obsidian-markdown）

在 Obsidian 库里写或改笔记时，用 OFM 语法，而不是通用 Markdown。OFM = CommonMark + 一组 Obsidian 扩展。

## 扩展语法

- **Wikilink**：`[[笔记名]]`、`[[笔记名|显示文本]]`、`[[笔记名#小节]]`、`[[笔记名#^块id]]`
- **Embed**：`![[图片.png]]`、`![[笔记名#小节]]`、`![[文档.pdf#page=3]]`
- **Callout**：第一行 `> [!note] 标题`，之后每行都要以 `>` 开头写内容。类型有 note / tip / warning / info / example / quote / success / question / failure / danger / bug；写 `> [!note]-` 表示默认折叠
- **Properties**：文件头的 YAML frontmatter，常用 `tags`、`aliases`、`cssclasses`、`date`
- **Tag**：`#标签`，嵌套用 `#项目/子项`
- **高亮**：`==文字==`
- **注释**：`%%不会被渲染的内容%%`
- **数学**：行内 `$...$`，块级 `$$...$$`

## 铁律

1. 库内引用一律用 wikilink，不要写相对路径的 Markdown 链接——改文件名后 wikilink 会自动跟随，普通链接会断
2. 只有指向库**外**的地址才用 `[文本](https://...)`
3. frontmatter 必须是文件第一行就是 `---`，紧接一行 `---` 收尾，中间不放空行
4. 一篇笔记只有一个一级标题，章节从 `##` 起

## 步骤

1. 先定位这篇笔记：日记 / 常青笔记 / MOC 索引 / 项目记录，不同类型结构不同
2. 写 frontmatter，`tags` 必填，`aliases` 按需
3. 正文结论先行：一句话摘要 → 展开论证 → 关联笔记
4. 需要复用别处内容时用 `![[...]]` 嵌入，不要复制粘贴，保持单一事实来源
5. 结尾把这篇笔记用 wikilink 挂到相关 MOC，避免成为孤岛

## 反面例子

- 库内链接写成 `[笔记名](笔记名.md)`
- callout 漏掉后续行的 `>`，在阅读视图里渲染成普通引用
- frontmatter 前面留了空行或注释，属性整块失效
- 一篇笔记里出现多个 `#` 一级标题
