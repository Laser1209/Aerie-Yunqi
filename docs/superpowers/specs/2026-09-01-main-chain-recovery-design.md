# 主链路恢复设计

## 目标

恢复 Aerie 桌面端的最小可用闭环：Electron Renderer 启动后能够通过后端代理访问 FastAPI，提交一条聊天请求，Worker 调用 Pipeline，结果通过事件流返回并写入 SQLite。隔离验证使用独立数据目录，不修改正式数据、凭据或已生成安装包。

## 范围

第一阶段只处理会阻断或破坏上述闭环的确定性问题：后端冷启动异常、模型禁用开关未覆盖隐式 provider 外呼、请求上下文和终态字段丢失、Renderer 与后端接口名称不一致。World sidecar、Companion Studio、GitHub 组件和商业化测量作为后续阶段，先记录兼容边界，不在本阶段引入新的基础设施。

## 数据流

`Renderer -> preload/contextBridge -> Electron IPC 或 HTTP 代理 -> FastAPI -> ChatRequestService/Repository -> ChatRequestWorker -> Pipeline -> LLM/工具/持久化 -> chat_events/SSE -> Renderer ChatStore`。

模型被显式禁用时，Pipeline 及其情绪推断、provider 健康探测必须共享同一个门控；所有外呼失败都应转换为可观察的降级结果，而不是阻塞请求终态。

## 设计决策

1. 删除 `Companion.__init__` 中重复的局部 `data_dir` 导入，统一使用模块级导入。
2. 由统一路径入口提供数据库、Chroma、persona、workspace 和移动网关路径；本阶段先覆盖启动链路所触及的路径，并保留显式环境变量覆盖。
3. Worker 从持久化请求恢复完整 persona、原始事件和消息元数据；只有 Pipeline 成功产生完整结果时才标记批次完成，否则进入失败或可重试终态。
4. Renderer 使用后端公开的 `/api/persona/avatar` 和动态后端端口，所有 `file://` 页面请求经过 preload API。
5. 验证必须包含进程级启动、`/api/health`、一条禁用模型的聊天请求、SSE/轮询事件及数据库终态；历史日志只能作为回归证据，不能替代当前运行证据。

## 后续阶段

主链路稳定后，单独评估 Companion Studio 的 HTTP/Live2D/RVC 接口和可复用 GitHub 组件；商业化阶段再定义明确的注册、订阅或付费成功边界，并按 OpenAI Ads 文档接入非阻塞 Pixel/CAPI 测量，不在核心聊天路径中放置任何服务端密钥。

