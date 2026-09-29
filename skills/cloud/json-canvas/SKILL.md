---
name: json-canvas
description: JSON Canvas / Canvas
provider_hint: text
read_only: true
kind: instruction
triggers:
- .canvas
- json canvas
- 画布文件
- 思维导图文件
- 关系图文件
- 节点图
- 生成画布
---
# JSON Canvas（json-canvas）

生成或修改 Obsidian `.canvas` 文件时套用这套格式规范。`.canvas` 就是纯 JSON，没有容错解析器——字段名写错 Obsidian 会直接打不开，所以格式必须严格。

## 文件结构

```json
{ "nodes": [ ... ], "edges": [ ... ] }
```

两个键都可省略，空画布就是 `{}`。

## 节点（node）

必填：`id`（唯一字符串）、`type`、`x`、`y`、`width`、`height`。

`type` 四选一，各自带专属字段：

- `text` → `text`（Markdown 正文）
- `file` → `file`（库内相对路径），可选 `subpath`（`#标题` 或 `#^块id`）
- `link` → `url`
- `group` → 可选 `label`、`background`（本地图片路径）、`backgroundStyle`（`cover` / `ratio` / `repeat`）

## 边（edge）

必填：`id`、`fromNode`、`toNode`。可选：`fromSide` / `toSide`（`top` / `right` / `bottom` / `left`）、`fromEnd` / `toEnd`（`none` / `arrow`）、`color`、`label`。

## 颜色

`"1"`~`"6"` 六个预设色，或十六进制 `"#RRGGBB"`。节点和边都适用。

## 坐标

原点在左上角，`y` 轴向下。同组节点先算好宽高再定位，避免压在一起。

## 步骤

1. 先列出要表达的实体和它们的关系，别急着写坐标
2. 定一套网格（例如每列间隔 400、每行间隔 200），所有节点按网格摆位
3. 先写 `nodes` 再写 `edges`，边只引用已经出现过的节点 id
4. 用 `file_write` 落盘为 `.canvas`
5. 自检：JSON 能解析、id 全局唯一、每条边两端的 id 都存在

## 反面例子

- id 用中文、带空格或重复
- 边引用了不存在的节点 id
- 漏写 `width` / `height`，Obsidian 里节点塌成一条线
- 两个节点坐标完全相同，叠在一起只看得见一个
