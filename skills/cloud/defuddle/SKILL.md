---
name: defuddle
description: 网页正文提取 / Extract clean content from a web page
provider_hint: text
read_only: true
requires_cli: defuddle
---

# defuddle / 网页正文提取

把一个网页抓成**干净的 Markdown 正文**：去掉导航、广告、侧栏、页脚等杂质，
只留文章内容。适合"帮我看看这个链接讲了什么""把这篇文摘下来"这类请求。

## 入参

- `url`：必填，网页地址（也可以是本地 HTML 文件路径）
- `frontmatter`：可选，true 时在正文前附上标题 / 作者 / 来源等元信息

## 出参

- 成功：`{"status": "ok", "markdown": "...", "url": "...", "chars": N}`
- 缺参数：`{"error": "missing url"}`
- CLI 缺失：`{"status": "error", "error": "defuddle CLI 不可用: ..."}`
- 抓取失败：`{"status": "error", "error": "..."}`

## 与内置 web_fetch 的分工

`web_fetch` 是通用抓取（拿原始内容），本 skill 专职**正文提取**：
页面导航复杂、广告多时用它明显更干净。要正文就用这个。
