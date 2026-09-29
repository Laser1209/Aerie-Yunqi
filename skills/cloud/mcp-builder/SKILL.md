---
name: mcp-builder
description: MCP 服务器构建 / MCP builder
provider_hint: text
read_only: true
kind: instruction
triggers:
- 写个 MCP
- 做一个 MCP
- MCP 服务器
- MCP 工具设计
- MCP 参数设计
- 接一个 MCP
- 封装成 MCP
---

# MCP 服务器构建（mcp-builder）

当你要把一个能力封装成 MCP server（Python FastMCP 或 Node SDK），让模型能通过工具调用访问时走这份流程。产出是一套**工具清单 + 参数 schema + 错误语义**，而不是一个方法繁多的万能接口。

## 铁律

1. **一个工具只做一件事，名字是动词短语**：`search_issues` 好过 `do_issue`，粒度按"一次用户意图"切，不要把增删改查塞进一个 `manage_xxx`。
2. **参数用 JSON Schema 显式约束**：类型、必填、枚举、默认值都写清，模型才能据此正确构造调用；不写 schema 等于让它猜。
3. **返回结构化、可继续加工的数据**：优先返回 JSON，字段名稳定；不要把整个 HTML 或超长文本原样塞回上下文。
4. **错误要区分语义**：参数错误（invalid_params）、权限不足（unauthorized）、资源不存在（not_found）、上游失败（upstream_error）分别返回，让模型知道该重试还是该放弃。
5. **描述字段是给模型看的说明书**：每个工具和参数的 description 要写"什么时候用、返回什么"，这是模型唯一的线索。
6. **副作用工具要能被识别**：只读与写操作分开命名，不要一个工具既查询又落库。

## 步骤

1. **列工具清单**：按用户会发出的意图逐条列工具，每个一句话说明它解决什么问题。
2. **为每个工具定输入**：字段名、类型、是否必填、取值范围或枚举、默认值，写成 schema。
3. **定输出结构**：统一成功返回的形状，字段名用 snake_case 且保持稳定。
4. **定错误语义**：列出可能失败的原因并映射到统一的错误码与 message。
5. **实现**：Python 用 FastMCP 装饰器注册，Node 用 `@modelcontextprotocol/sdk` 的 `server.tool`，把上面三层原封不动落进去。
6. **本地自测**：用 MCP Inspector 或命令行逐个调通，确认参数校验与错误分支都走到了。

## 输出形态

```
## 工具清单
- search_docs(query, limit=10) — 按关键词检索文档
- get_doc(id) — 按 id 取单篇

## 参数 schema（示例）
search_docs.query: string, required, "检索关键词"
search_docs.limit: integer, optional, default 10, range 1..50

## 错误语义
- invalid_params: 参数缺失或类型错
- not_found: id 不存在
- upstream_error: 下游超时或 5xx

## 返回结构
{ "items": [...], "total": 12 }
```

## 反面例子（不要这样）

- 一个 `manage` 工具用 `action` 字符串分发所有操作。
- 参数全是 `object` 不做约束，模型频繁传错类型。
- 直接把上游返回的整页 HTML 塞回上下文。
- 所有失败都返回 `{"error": "failed"}`，模型无从判断能否重试。
