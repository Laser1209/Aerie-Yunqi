---
name: gh-cli
description: GitHub 仓库/PR/Issue 查询 / GitHub CLI queries
provider_hint: shell-safe
read_only: true
requires_cli: gh
---

# gh-cli / GitHub 查询

通过本机 `gh` 命令查询 GitHub 的**只读**信息：仓库概况、PR 与 Issue 列表/详情、
Actions 运行记录、仓库搜索。写入类操作（创建 PR、合并、评论）**不在本 skill 范围内**。

## 入参

- `action`：必填，取值见下表
- `repo`：可选，`owner/name`（省略则用当前目录所属仓库）
- `number`：PR / Issue 编号（`pr_view` / `issue_view` 必填）
- `query`：搜索关键词（`search_repos` 必填）
- `limit`：可选，返回条数上限（默认 10，最大 50）
- `state`：可选，`open` / `closed` / `all`（列表类动作，默认 open）

## action 取值（白名单）

| action | 说明 |
|---|---|
| `pr_list` | PR 列表 |
| `pr_view` | 单个 PR 详情 |
| `issue_list` | Issue 列表 |
| `issue_view` | 单个 Issue 详情 |
| `repo_view` | 仓库概况 |
| `run_list` | Actions 运行记录 |
| `search_repos` | 搜索仓库 |

## 出参

- 成功：`{"status": "ok", "action": "...", "count": N, "items": [...]}`
- 未登录：`{"status": "error", "error": "gh 未登录，请先执行 gh auth login"}`
- 缺参数：`{"error": "missing number"}` 等

## 注意

`gh` 需要先登录（`gh auth login`）；未登录时本 skill 会**如实报错**，
不会假装查到空结果。只读动作全部走 `--json`，输出结构化数据而不是给人看的表格。
