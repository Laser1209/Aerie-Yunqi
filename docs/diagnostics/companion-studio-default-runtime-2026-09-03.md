# Companion Studio 默认运行链路诊断（2026-09-03）

## 现象

在 `E:\Retrieval-based-Voice-Conversion-WebUI\companion-studio` 启动后，`GET /api/health` 返回 HTTP 200，但首次 `POST /api/talk` 会等待外部 Chat provider，最终超时。这个现象会让用户误以为语音链路或 Aerie 适配器损坏。

## 根因

`configs/settings.json` 是本机配置且被 Studio 的 `.gitignore` 排除。恢复旧版本后该文件可能保留：

- `pipeline.echoMode=false`；
- `services.chat.provider=openai`；
- 旧的外部 `baseUrl` 或遗留 API Key。

此组合会让无 Key 的首次 `/api/talk` 进入外部网络，而不是使用本地可用的回声路径。配置文件中的 API Key 不应进入仓库、安装包或日志。

## 已验证修复

本机默认配置已调整为：

```json
{
  "services": {
    "chat": { "provider": "disabled", "options": { "baseUrl": "", "apiKey": "", "model": "" } },
    "asr": { "provider": "disabled" },
    "rvc": { "provider": "disabled" }
  },
  "pipeline": { "echoMode": true }
}
```

随后真实启动 `backend/main.py --port 8899`：

- `GET http://127.0.0.1:8899/api/health`：HTTP 200；Chat/ASR/RVC 明确显示 disabled，TTS Edge healthy。
- `POST http://127.0.0.1:8899/api/talk`：HTTP 200，返回 `reply`、音频文件名、音频 URL 和 `durationMs`。
- 未配置外部 Chat Key 时不再等待网络调用。

默认角色也已统一为中性的 `Aerie Companion`：本机配置、示例配置、后端缺省值、前端首屏和开发文档均不再把伊塔、云栖或栖音作为默认角色。测试夹具中保留的旧名称只用于验证用户显式自定义 persona 的兼容性。

## 发布检查

1. 首次启动前从 `settings.example.json` 生成本机配置时，默认必须是 `echoMode=true`。
2. Chat、ASR、RVC 没有凭据或服务地址时必须显示 disabled，而不是重试外部网络。
3. 真正启用 Chat 时由用户在设置页输入自己的 Key；不得把 Key 写入 Git、安装器、遥测或错误日志。
4. Aerie 适配器继续把 Studio 视为可选连接器；Studio 不可用时 Aerie 主聊天必须保持可用。
5. 发布前同时验证 `/api/health`、`/api/talk` 和 `/api/speak`，不能只验证静态页面 200。

## 结论

该问题不是 Aerie 核心流量通路的数据库或 HTTP 代理错误，而是恢复旧版本后被忽略的 Studio 本机配置漂移。修复默认配置并把检查项纳入发布验收后，Companion Studio 才符合“无外部模型也能完成第一条体验”的商业测试承诺。
