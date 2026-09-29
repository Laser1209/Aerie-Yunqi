---
name: byted-bp-cdn-pagesdeploy
description: 字节边缘 Pages 部署 / BytePlus Edge Pages（官方 CLI）
provider_hint: shell-safe
read_only: false
requires_cli: nest
---

# byted-bp-cdn-pagesdeploy / BytePlus Edge Pages 部署

通过本机官方 CLI `@byteplus/nest`（二进制名 `nest`）把静态站点一键部署到
BytePlus Edge Pages，并可绑定自定义域名。

## 前置

```bash
npm install -g @byteplus/nest
nest config set -g cloud.access_key <AccessKey ID>       # IAM 密钥管理页获取
nest config set -g cloud.secret_key <SecretAccessKey>
```

AK/SK 由 CLI 自己的配置持有，**本 skill 不代持任何密钥**。

> ⚠️ 二进制名 `nest` 与 NestJS CLI 撞名。若跑 `deploy` 报 `unknown command`，
> 说明本机装的是 NestJS，需要改装 `@byteplus/nest`。

## 入参

- `action`：必填，取值见下表
- `project_name`：`deploy` 必填，2~31 位，仅小写字母 / 数字 / 连字符
- `assets_dir`：`deploy` 必填，静态资源**目录**（必须在项目根之内且含 `index.html`）
- `deploy`：可选，创建后是否立即部署（默认 `true`）
- `pages_id`：`domain_add` 必填，Pages 实例 id（形如 `p-2e9hpae39m2sqksy`）
- `domain`：`domain_add` 必填，要绑定的自定义域名

## action 取值（已查证白名单）

| action | 命令 | 说明 |
|---|---|---|
| `deploy` | `pages create --name ... --assets ... [--deploy]` | 创建项目并发布 |
| `domain_add` | `pages domain add -p <id> --domain <域名>` | 绑定自定义域名 |
| `version` | `--version` | 版本探测 |
| `help` | `--help` | 打印 CLI 帮助 |

未绑定自定义域名时，平台会分配临时预览域名 `<随机串>.synthopages.bytepluses.com`。

## 出参

- 成功：`{"status": "ok", "action": "...", "stdout": "..."}`
- CLI 未安装：`{"status": "error", "error": "nest CLI 不可用（未安装或不在 PATH）..."}`
- 参数非法（项目名/资源目录越界或缺 index.html/域名格式）：`{"error": "invalid arguments"}`
- 装成了 NestJS：`{"status": "error", "error": "... —— 若本机装的是 NestJS CLI 而非 @byteplus/nest ..."}`

## 平台限制（来自官方文档）

单账号最多 10 个实例；单实例保留 100 个历史部署；每月最多 100 次部署；
zip 包 ≤ 50MB、≤ 500 个文件、单文件 ≤ 25MB。

## 安全

- `read_only = false`（会创建/发布线上资源），由 SkillLoader 强制
- 子进程调用，`shell=False`，argv 由「固定前缀 + 白名单参数」拼出
- 静态资源目录必须落在项目根之内且含 `index.html`，越界直接拒绝

provider_hint: `shell-safe`
