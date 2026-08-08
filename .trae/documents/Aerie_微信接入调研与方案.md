---
title: Aerie 微信接入调研与方案
date: 2026-08-09
tags:
  - research
  - wechat
  - clawbot
  - ilink
  - recall
status: archived
---

# Aerie 微信接入调研与方案

> [!abstract] 一句话
> 微信端未来通过 **ClawBot（iLink 官方协议）** 接入，本轮仅做架构预留 + 调研归档，**不接真实微信**。已确认 iLink 协议**暂无独立撤回端点**，撤回能力待官方开放后接入。

> [!warning] 本文档仅供后续调取
> 记录行业做法、开源方案与撤回能力结论，作为未来真正接入微信端时的决策依据。

---

## 1. 背景与定位

Aerie 需要区分三个端口的撤回能力：
- **QQ 端**：NapCat `delete_msg` 真实撤回（✅ 已实现）
- **客户端/桌面端**：DB 标记 + 前端事件（✅ 已实现）
- **微信端**：未来接入（⏳ 仅桩 `WeChatClawbotAdapter`，`channel="clawbot"`）

微信端必须与 QQ/本地端**完全解耦**，通过同一套 `RecallAdapter` 协议扩展。

---

## 2. 官方方案：微信 ClawBot（iLink 协议）

### 2.1 背景

2026-03-22，腾讯微信官方发布 **ClawBot 插件**（OpenClaw 平台），首次向个人开放合法 Bot API。插件版本 `@tencent-weixin/openclaw-weixin`，底层 **iLink（智联）协议**，接入域名 `ilinkai.weixin.qq.com`。

### 2.2 架构模型

```
微信用户 (iOS/Android) → ClawBot 插件 → 腾讯 iLink 服务器 → Bot 程序 (HTTP/JSON 长轮询)
```

腾讯定位为纯消息管道（pipeline model）：不存储用户输入和 AI 输出，不提供 AI 服务本身。

### 2.3 关键协议细节

| 项目 | 值 |
|---|---|
| 基础 URL | `https://ilinkai.weixin.qq.com` |
| CDN URL | `https://novac2c.cdn.weixin.qq.com/c2c` |
| 协议格式 | HTTP/JSON |
| 认证 | Bearer Token（QR 扫码） |
| 请求头 | `iLink-App-Id: bot`、`Authorization: Bearer {token}`、`X-WECHAT-UIN` |

**API 端点**（前缀 `{base_url}/ilink/bot/`）：

| 端点 | 功能 | 超时 |
|---|---|---|
| `getupdates` | 长轮询接收消息 | 35s |
| `sendmessage` | 发送消息 | 15s |
| `sendtyping` | 发送输入状态 | 10s |
| `getconfig` | 获取配置 | 10s |
| `get_bot_qrcode` | 获取登录二维码 | 15s |
| `get_qrcode_status` | 轮询扫码状态 | 35s |
| `getuploadurl` | CDN 上传地址 | 15s |

**消息方向枚举**（`MessageType`）：`1=USER`（用户发）、`2=BOT`（机器人发）
**消息状态枚举**（`MessageState`）：`0=NEW`、`1=GENERATING`（流式）、`2=FINISH`

### 2.4 ⚠️ 撤回能力结论（核心）

iLink 协议 `WeixinMessage` 结构含 `delete_time_ms`（删除时间戳）字段，但**协议层无独立 revoke/撤回端点**。

> [!failure] 结论
> **ClawBot 官方通道当前无法可靠撤回自己消息。** 现有端点只有收发消息/输入状态/配置，无撤回接口。`delete_time_ms` 仅表示消息被删除的时间戳，非可调用的撤回 API。

**触发方式缺口**：`<recall>` 指令在微信端当前只能"本地标记"，无法做到平台侧真实撤回（与本地端行为一致）。

---

## 3. 备选方案对比

| 方案 | 协议 | 撤回自己消息 | 合法性 | 风控 | 备注 |
|---|---|---|---|---|---|
| **ClawBot (iLink)** | 官方 HTTP/JSON | ❌ 暂无端点 | ✅ 官方 | 低 | 首选，待撤回能力开放 |
| **WeChatFerry (wcf)** | Windows DLL 注入 | ✅ `revoke_msg` | ❌ 逆向 | **高**（封号） | 需特定微信版本 |
| **Wechaty + PadLocal** | iPad 协议 | ⚠️ 需确认 | ❌ 灰产 | 中 | 商业 token |

### 3.1 WeChatFerry（wcf）

- Windows 进程注入 + RPC（pynng）通信。
- Python 客户端 `wcferry`，`Wcf` 类提供 `revoke_msg`（撤回消息）、`send_text`、`get_msg` 等。
- **明确支持撤回自己消息**（`revoke_msg`）。
- 需特定微信版本（如 3.9.5.81），微信更新可能失效，**封号风险高**。
- 定位：仅供学习/技术研究，不用于商业。

### 3.2 Wechaty + PadLocal

- iPad 协议（PadLocal 商业 token），风控较低。
- 撤回能力需按具体 PadLocal 方案确认。
- 需商业付费。

---

## 4. 开源社区相关资料

- **微信 ClawBot 官方 API**：`@tencent-weixin/openclaw-weixin`（官方包）
- **SiverKing/weixin-ClawBot-API**：基于官方 openclaw-weixin 实现的 Python/Node 版微信 Bot，支持接入任意 AI 模型，含 `weixin-bot-api.md` 协议文档。
- **nightsailer/wechat-clawbot**：iLink 协议技术文档（`docs/ilink-protocol.md`），基于 v2.1.1 源码分析。
- **lich0821/WeChatFerry**：WeChatFerry 主仓库（微信 Hook 工具，`revoke_msg` 撤回）。
- **bobomouse/WeChatFerry**：fork 版本。

---

## 5. 接入时机与决策建议

> [!tip] 建议
> 1. **当前（本轮）**：仅保留 `WeChatClawbotAdapter` 桩（`channel="clawbot"`），`can_recall` 恒 `(False, "not_implemented")`。不新增微信业务代码。
> 2. **未来**：等待腾讯官方在 iLink 协议暴露 **revoke 端点** 后，再实现 `WeChatClawbotAdapter.recall()`。
> 3. **若不等待官方**：可评估 WeChatFerry `revoke_msg` 作为临时撤回方案，但需接受封号风险；建议维持"本地标记"降级。
> 4. 微信端撤回能力若不可用，`<recall>` 指令自动降级为**仅本地标记**（与本地端一致），不影响 QQ 端真实撤回。

---

## 6. 代码侧预留清单

| 项 | 状态 |
|---|---|
| `communication/recall/wechat_stub.py` 的 `WeChatClawbotAdapter`（`channel="clawbot"`） | ✅ 已建桩 |
| `communication/router.py` 的 `CHANNEL_CLAWBOT` 常量 | ✅ 保留 |
| `core/companion_channel.py` 的 `ClawBotChannelAdapter` | ✅ 保留 |
| `communication/recall/factory.py` 的 `get_recall_adapter("clawbot")` | ✅ 返回桩，不抛错 |

---

## 7. 参考来源

- 腾讯官方 ClawBot 插件 / OpenClaw 平台
- [SiverKing/weixin-ClawBot-API](https://github.com/SiverKing/weixin-ClawBot-API)
- [nightsailer/wechat-clawbot iLink 协议文档](https://github.com/nightsailer/wechat-clawbot/blob/master/docs/ilink-protocol.md)
- [lich0821/WeChatFerry](https://github.com/lich0821/WeChatFerry)
- CSDN 技术博客（ClawBot 深度解析、WeChatFerry 教程）
