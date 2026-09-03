# A08 桌面流量通路与运行状态诊断

> 版本：`0.3.2-beta.0903-A08`  
> 构建：`D:\aerie-dist-v048`  
> 审计证据：`D:\aerie-desktop-audit-0903-v4`

## 结论

Aerie 的 Electron -> preload -> Python 后端链路在隔离端口 `7896` 能启动并进入 `ready`。A08 修复后，渲染器不再把后端地址写死为 `7890`，无自定义头像时也不再请求必然返回 404 的 `/api/persona/avatar`。

桌面审计脚本仍返回 `failed`，但不是主链路整体不可用：

- `pageIdentity` 正确：标题为 `Aerie Companion`，页面加载成功；
- 后端：`ready=true`，端口 `7896`；
- `missingStates` 为空，七类状态均已收集；
- 业务请求失败为 0；剩余 3 个失败请求是隔离环境中止 Google Fonts；
- 2 个 renderer error 是 Electron reload/关闭阶段的 `ERR_CONNECTION_CLOSED`，没有业务异常栈；
- 整体失败原因主要是 358 个审计交互和 49 个 phase 未满足严格的 locator 唯一性、控件重叠或安全跳过规则，以及 `approval_modal_not_initialized`。

## 流量通路

```text
Electron main
  -> spawn Python main.py (AERIE_BACKEND_PORT=7896)
  -> /api/health ready
  -> preload 注入 window.__API_BASE__
  -> renderer chat/settings/workspace/dynamic-island
  -> http://127.0.0.1:7896/api/*
  -> SQLite / local files / optional Companion Studio :8899
```

Companion Studio 当前在 `127.0.0.1:8899` 返回 HTTP 200。Edge TTS 可用；ASR、Chat 和 RVC 在没有外部地址或模型时按设计返回 `provider=disabled`，不应宣传为已配置的云服务。

## A08 修复项

| 位置 | 修复 | 验证 |
| --- | --- | --- |
| `electron/src/preload.js` | 注入动态 `window.__API_BASE__`，跟随隔离端口 | Electron 158 项单元测试通过 |
| Chat/Settings/Workspace | 所有附件、头像、诊断和工作区请求使用动态 API base | 7896 审计无业务端口错配 |
| `electron/src/renderer/js/dynamic-island.js` | 先读取 `/api/persona` 的 `avatar_dataurl`，无头像保留本地默认图 | v4 审计不再出现头像 404 |
| `electron/tests/system-status.test.js` | 增加头像降级回归断言 | 测试通过 |

## 仍存在的问题

1. 审计器的控件唯一性、重叠和安全跳过规则过严，导致业务可用时整体仍为 failed；应拆分为“业务 smoke 结果”和“UI 质量结果”两个结论。
2. Google Fonts 依赖外网，隔离环境会产生 `ERR_ABORTED/ERR_CONNECTION_CLOSED`。商业包应提供本地字体回退或将远程字体改为可选资源。
3. `approval_modal_not_initialized` 表明电脑操控审批卡片没有在通用审计前初始化；需要专门的审批流程测试，不应在普通只读审计中判定主链路失败。
4. 无 QQ、外部 Chat、ASR、RVC 配置时的降级是合法状态，不是文件丢失或版本不兼容；产品页必须继续显示“未配置/disabled”边界。

## 已执行验证

```text
Electron unit tests: 158 passed
Python tests/test_topic_system.py: 32 passed
Spotlight production build: passed
OpenAI Ads secret scan (Spotlight): passed
OpenAI Ads setup check (Spotlight): passed
A08 Windows build: passed
GitHub A08 assets: Setup / portable / blockmap all present
```

## 发布状态

- GitHub Release：<https://github.com/Laser1209/Aerie-Yunqi/releases/tag/v0.3.2-beta.0903-A08>
- GitHub Pages Actions：成功，提交 `75c937e`
- 官网已显示 A08 下载链接，HTTP HEAD 返回 200；线上页面标题为 `Aerie Companion · 本地优先 AI 桌面伙伴`。

部署前仍需完成干净 Windows 的安装、升级、卸载和真实用户封闭测试。没有真实支付成功边界、商业 EULA 和真实 Pixel ID 前，不开启订阅转化上报或公开收费。
