# 主链路恢复与默认能力审查报告

日期：2026-09-01

## 本次变更

- 修复 `core/companion.py` 中局部 `data_dir` 导入造成的冷启动 `UnboundLocalError`。
- 新增 `core/model_gate.py`，让主模型、PAD 情绪推断和 provider 余额探测共享 `AERIE_DISABLE_MODEL_CALLS` 门控。
- 修复 `Database`、Mobile Gateway、Workspace 的默认数据路径，使其遵循 `AERIE_DATA_DIR`。
- 将 `Workspace` 持久化路径保留为可测试覆盖点，避免 profile 切换后继续使用旧路径。
- 开启 `settings.yaml` 中原先关闭的能力旗标：聊天流、身份契约、记忆写入校验、移动网关、思维轨迹、World sidecar。`auto_start` 和 `start_minimized` 保持 false，因为它们是启动偏好而不是能力模块。
- 修复 Renderer 的 provider 连接状态函数、头像 GET 路径和主动推送面板的 `file://` 请求路径。

## 运行证据

使用新建隔离目录 `.codex-temp/runtime-20260901-final`、端口 `17890` 和显式 `AERIE_DISABLE_MODEL_CALLS=1` 启动 `main.py`：

- `/api/health`：HTTP 200；后端 healthy；`data_path_id` 指向隔离目录；QQ disconnected 但服务进入 degraded 模式。
- `POST /api/chat/send`：HTTP 202，返回 request id。
- `GET /api/chat/requests/{request_id}?user_id=1`：HTTP 200，约 0.3 秒内 `status=completed`，包含一个用户消息和两个 assistant message id。
- 日志出现 `chat_request_completed`，且本地确定性回复生效；未观察到 provider 外呼失败。
- 服务已停止，隔离日志和数据库保留用于复核；正式 `data/aerie.db` 未用于该请求。

## 测试

- `python -m compileall -q core main.py`：通过。
- 情绪禁用门控 + LLM 禁用回归：2 passed。
- Workspace、模型禁用及门控回归组合：42 passed。
- `tests/test_phase4_integration.py`：17 passed。
- Companion Studio `backend/tests`：6 passed（系统 Python）；其项目专用 venv 未安装 pytest，因此未宣称该 venv 测试通过。
- Electron Renderer 三个修改文件：`node --check` 全部通过；完整 Electron 单测为 149 passed / 7 failed，失败为既有音频附件、合成层性能、SSE/poll UI、running request UI、启动时序和 dynamic island 断言，未归因于本次 API 修复。
- 2026-09-02 生成新的 Portable 产物：`electron/dist/Aerie · 云栖-0.3.1-BETA.0815A4-portable.exe`（新时间戳，约 311 MB）；`app.asar` 和 `resources/python/core/model_gate.py` 已核验包含本轮源码。NSIS 安装器仍需后续单独修复脚本/构建环境。
- 商业默认 persona 已新增 `aerie_default` 并由 `main.py` 选择；旧 profile 的 `yita_default` 不会被删除或覆盖。双场景 Persona Hub 测试通过。
- 某个既有路径测试因仓库中已存在的 `data/companion_state.json` 遗留文件失败；未删除该文件，避免破坏用户数据。

## Companion Studio 结合结论

`E:\Retrieval-based-Voice-Conversion-WebUI\companion-studio` 已有可运行的 aiohttp Web 边界，默认 `127.0.0.1:8899`，接口包括 `/api/talk`、`/api/speak`、`/api/asr`、`/api/models/live2d` 和 `/api/models/rvc`。推荐以 HTTP 适配器接入 Aerie 的 Pipeline 输出：Aerie 保持对话、身份和持久化为唯一真源，Studio 负责 TTS/RVC/Live2D 呈现；不要复制第二套聊天业务逻辑。

当前目录缺少可验收的真实 Live2D `.model3.json`/`.moc3` 和 RVC `.pth` 资产；Cubism Core 需要按 Live2D 许可从官方 SDK 获取。未下载这些受许可或用户自备的资产，也没有把占位形象误报为真实模型。

## GitHub 组件调研

现有 Studio 已 vendor 化 `pixi.js`、`pixi-live2d-display`，并固定 Cubism 兼容版本；Aerie 自身不需要再引入一套渲染库。可复用组件应优先采用 Studio 已锁定的版本和本地接口。外部仓库/模型资产引入前仍需确认许可证、版本和实际运行验证，当前没有发现必须下载才能恢复主链路的缺失源文件。

## 商业化边界

当前仓库没有已确认的注册、订阅或支付成功边界，因此本轮没有猜测性接入转化事件。后续应先定义一个真实成功事件（例如订阅创建或试用开始），再按 OpenAI Ads 文档以非阻塞 Pixel/CAPI 接入；服务端密钥只能来自服务端秘密存储，不能进入 Renderer、日志或报告。

## 残余风险与优先级

- P0：Electron `app.asar` 与当前源码不一致，必须重新生成可复现安装包并写入 commit/build manifest。
- P1：仍需把所有相对 Chroma/认证路径统一到运行时 profile，并确认环境文件没有覆盖为相对路径。
- P1：Renderer 仍有与本次无关的 7 个既有单测失败，需要单独修复后才能宣称 Electron 全绿。
- P1：World in-process 与 sidecar 同时启用后必须做单实例验证，避免状态分叉和旧 outbox 积压。
- P2：SendQueue 溢出、SSE 队列丢弃和 iLink 非 5xx 退出策略需要独立压测与重试设计。

## 2026-09-02 04:00 增量复核

- 上一版版本规则已统一为 `0.3.2-beta.0902-A04`（09 月 02 日上午 04 点）；当前发行版本已推进为 `0.3.2-beta.0902-A05`，并同步根 `package.json`、Electron 包、锁文件、Python runtime、World Service、Renderer、官网发布配置和 README。
- 构建资源路径已统一为 `electron/runtime-build-vfix`；该目录存在真实 `python.exe` 与 `Lib/encodings/utf_8.py`，避免恢复旧版本时再次触发 `ModuleNotFoundError: encodings`。
- 使用 NSIS 对应的解包 payload 进行实际 HTTP 烟雾测试：`/api/health` 返回 200、版本与 manifest 一致、权益接口正常、Companion Studio 未配置时结构化降级；QQ 未连接是唯一降级项，未阻断后端启动。
- 已在 `C:\aerie-dist-v043` 生成 A04 NSIS 与 Portable 产物；NSIS SHA-256 为 `585E728DB8AFB49E0E090440F24CD5CC388990A45BBD8CA5D2EDB3CBF733950D`。解包后 `resources/build-manifest.json` 存在，版本与 runtime SHA-256 均一致。
- 对 v043 解包 payload 进行隔离启动（端口 `17992`、独立数据目录）：`/api/health` HTTP 200，后端 healthy，manifest 版本 A04，权益接口正常，Companion Studio 未配置时结构化降级；QQ 未连接导致 degraded，但未阻断主链路。真实 NSIS 安装、升级和卸载仍需在干净 Windows profile 中人工验收。
- 为避免无交互 UAC 拦截，Windows 执行级别已统一为 `asInvoker`；高风险文件/桌面操作仍由应用内权限闸门控制。解包 Electron 外壳已在端口 `17995` 拉起内嵌 Python 并通过健康检查。Portable 单文件在当前机器上持续自解压超过 90 秒仍未产生子进程，疑似自解压性能/杀毒扫描瓶颈，暂不把它作为首发默认交付，优先使用 NSIS 或解包目录。
- Companion Studio 实例已在 `127.0.0.1:8899` 启动并响应 `/api/health`、`/api/models/live2d`、`/api/models/rvc`；Live2D 与 RVC 模型可发现，ASR 因未配置 provider 而明确 disabled，Studio 本身未崩溃。
- 回归测试契约已同步到商业默认：移动网关默认开启，但 `AERIE_MOBILE_GATEWAY_ENABLED=false` 或对应 feature flag 仍可作为显式事故回滚开关；主链路/移动网关/管理服务/权益/Studio 集合共 `70 passed`。

## 2026-09-02 05:44 增量运行验收

- 使用 `companion-studio/backend/main.py --port 8899` 临时启动 Companion Studio；`GET /api/health`、`/api/models/live2d`、`/api/models/rvc` 均返回 HTTP 200。
- Studio 的 chat provider 为 `openai -> gpt-5.6-luna`、TTS provider 为 `edge -> zh-CN-XiaoxiaoNeural`；ASR provider 明确为 `disabled`，因此健康汇总 `ok=false` 是能力未配置的降级状态，不是进程崩溃。
- Aerie `GET /api/integrations/companion-studio` 在配置 `AERIE_COMPANION_STUDIO_URL=http://127.0.0.1:8899` 时返回 HTTP 200、`status=healthy`、`base_url_configured=true`，并保留 Studio 的 ASR disabled 细节。
- 临时 Studio 进程已在验收后关闭；未修改用户已有进程或系统服务。
- 重新生成的品牌版 NSIS 安装器：`C:\aerie-dist-v045\Aerie Companion-0.3.2-beta.0902-A05-Setup.exe`，SHA-256：`8288DA7983E0FEA92CA0D304B6D9EBAF95812E467F09CCD9FBCA774DDB9A1682`。解包目录中的 `app.asar`、`resources/build-manifest.json` 和 `resources/python/core/version.py` 均核验为 `0.3.2-beta.0902-A05`。
- A05 Portable 单文件因 E 盘空间不足在写入阶段失败；当前保留 NSIS 作为封闭投放测试渠道，便携版需在至少 3 GB 可用空间的构建盘重新生成。

## 2026-09-02 06:15 商业默认与发布链路复核

- 商业首屏、下载页、使用指南、Persona 向导、灵动岛和系统通知的默认文案已切换为中性的 `Aerie Companion`；旧 `yita_default` 与旧主题仍仅作为用户本地兼容/显式选择项保留。
- `electron/package.json`、NSIS `shortcutName`、Python FastAPI 应用名和健康检查兼容判断已同步到 `Aerie Companion`；后处理脚本支持 `AERIE_BUILD_OUTPUT_DIR`，自定义输出目录不会再被误报为构建失败。
- 品牌版 NSIS 已在 `C:\aerie-dist-v045\Aerie Companion-0.3.2-beta.0902-A05-Setup.exe` 生成并完成图标注入；包内 manifest、runtime 与版本均为 A05。未自动执行安装/升级/卸载，避免改变当前 Windows 系统状态。
- Spotlight 下载配置已改为品牌版文件名并对空格进行 URL 编码；对 GitHub Release URL 的 HEAD 检查返回 404，说明 A05 尚未上传到远端 Release。上传前线上下载页不能作为已发布证据；本地安装器可用于封闭测试。

## 2026-09-02 07:30 继续复核

- 版本入口再次核验：根 `package.json`、`electron/package.json`、`Spotlight/package.json` 及两份锁文件均为 `0.3.2-beta.0902-A05`；版本格式符合 `0.3.2-beta.mmdd-A/P hh`。
- 修复 `PersonaManager` 独立导入时的默认兜底：未设置环境变量时现在使用 `aerie_default`，不会因启动顺序重新激活 `yita_default`。旧 persona 文件不删除。
- 兼容投影默认名称已改为 `Aerie Companion`，避免缺少字段时把私有角色名重新写入商业界面或健康摘要。
- Spotlight 页面标题已改为 `Aerie Companion`。浏览器验收：首屏非空、A05 版本可见、页面标题正确、console error/warn 为空。
- Electron UI 的 Emoji 门禁已修复：关闭、状态、文件类型、说明提示改用 SVG sprite 或普通文字；`npm run check:emojis` 通过。
- Companion Studio 实测复核：`/api/health`、`/api/models/live2d`、`/api/models/rvc` 均 HTTP 200；chat=`openai -> gpt-5.6-luna`，tts=`edge -> zh-CN-XiaoxiaoNeural`，asr 明确为 disabled，属于配置降级而非进程故障。临时进程已关闭。
- GitHub API 只读核验：`FanyinLiu/Nexus`（MIT）、`lulu930128/desktop-agent-runtime`、`Dregxmoon/Kaoru-Agent`、`DennyWanye/deskpet`、`realtoletole/Amadeus` 均可访问；未发现必须下载才能恢复主链路的缺失文件，暂不引入未经许可证和运行验证的外部代码。
- `ContextBuilder` 的缺字段兜底已中性化：不再生成 `None 岁女性`、恋人关系、亲密称谓或伊塔专属风格；`aerie_default` 补齐耐心/压力/主动意愿阈值，兼容层和 focused tests 均通过（91 passed）。

## 2026-09-02 08:10 最终回归补充

- 修复 `WorldSimulation` 的时间语义回归：显式注入的 aware datetime 按调用方墙上时间解释，默认系统时钟仍使用北京时间；`09:00+00:00` 不再错误映射为 afternoon。
- 收敛时段边界：`evening` 为 18:00–22:00，`late_evening` 为 22:00–23:30，21:30 不再落入空档或过早进入夜深。
- 恢复三个 PoC/实验开关的默认关闭契约：`memory_write_validation_v1`、`thinking_trace_injection_v1`、`multi_channel_identity_v1`；可通过环境变量或运行时配置显式开启。
- 世界看板开关优先级修复：共享运行时旗标优先；无共享旗标时，`AERIE_FEATURE_WORLD_SIDECAR_V1=false` 才作为全局禁用开关。
- Electron workspace 目录箭头改为 SVG sprite；Emoji 检查器跳过第三方 `electron/src/renderer/vendor` 产物，仅扫描一方代码。
- 验证：Spotlight `npm run build`、Python `compileall`、`tools/check_forbidden.py`、`tools/check_emojis.py` 均通过。
- Python 全量测试在 1208 passed 后停止于旧主动推送断言：`tests/test_phase1_proactive_baseline.py` 仍期待 `persona_id=yita_default`，当前商业默认按要求为 `aerie_default`。该用例需迁移，不能以回退商业默认来“修复”。
- 后续隔离回归继续修复：内部状态上下文采样固定为秒级时间，避免连续调用的 `updated_at` 漂移；旧 `long_term_memory` 表重建改为按实际旧字段动态迁移，补齐新增列默认值；Persona Hub 保留旧模板但新环境默认 `aerie_default`。相关定向测试均通过。
- 旧库迁移回归已实测通过：缺少 `source_message_id` 等新增列的 legacy SQLite 表可成功重建并保留核心记录。
- Persona fallback 也已中性化：即使商业模板文件缺失或损坏，初始化不会回退到恋人式称谓、亲密关系或小众人格设定。
- `check_forbidden.py` 的规则声明豁免改为按字段识别，不再依赖会随代码移动失效的固定行号；当前禁用词与 Emoji 门禁均通过。
- D 盘隔离全量回归已验证至 76%：当前剩余失败为 `test_submit_claim_pipeline_complete_status_and_events_end_to_end` 的全量时序抖动；该测试连续单独运行 5 次均通过，待后续拆分 worker 生命周期/测试隔离后再宣称全量稳定。
- Phase 3 + Phase 4 组合回归（队列、迁移、会话、移动端共享历史）再次通过 `118 passed`；失败仅出现在加入全部前置模块的全量顺序中，未在核心集成文件内复现。
- 最新全量审计在 1367 passed 后出现 3 个同类请求队列断言（普通、移动、同会话）；Phase 4 单文件及核心组合仍通过。该模式表明前置测试/异步生命周期污染，尚未达到全量稳定标准。
- 根因已确认：宿主机 `.env` 中的 SiliconFlow 轻量纠错凭据会让测试额外调用 typo-corrector，污染 E2E brain 调用计数；测试公共 fixture 现已隔离可选 provider 凭据。
- 修复 QQ 媒体失败时的历史 `[语音]` 占位契约、QQ 表情视觉适配器的位置参数兼容、世界现实地点与室内对象合并，以及 23:00 时段契约。
- D 盘隔离全量回归最终通过：`1754 passed, 13 warnings, 21 subtests passed`（约 2 分 24 秒）。

## 2026-09-03 A12 发布核验

- 按版本规则 `0.3.2-beta.mmdd-A/P hh`，当前版本同步为 `0.3.2-beta.0903-A12`（北京时间 00:33）。运行时、根/ Electron/ Spotlight 包清单、Renderer、World Service 与 README 均已同步；历史段落保留 A05 作为旧构建记录。
- 三个此前默认关闭的能力已改为商业默认开启：`memory_write_validation_v1`、`thinking_trace_injection_v1`、`multi_channel_identity_v1`；对应 38 项定向回归通过。L4 代码自修改仍保留人工审批和安全闸门。
- A12 NSIS 与 portable 已输出至 `D:\aerie-dist-v046`，包内 `build-manifest.json` 与 `core/version.py` 均核验为 A12。NSIS SHA-256：`3CEE3119B06F8717FE04F2E1F536DE145D7FFA17AE427160BE8FB5E09B0AA1DE`；portable SHA-256：`13BA74A7AFEF09C52EB094A7E9579E681DDEC99D50C21FF2A6D62D50B5A0A680`。
- 修复 D 盘构建后处理路径：`build:win:d` 现在将输出、Electron cache、TEMP/TMP 固定至 D 盘，并让 rcedit 自动识别该输出目录。
- Spotlight `npm run build` 通过；当前仍未在干净 Windows 用户 profile 执行安装/升级/卸载流程，也未上传 GitHub Release。

## 当前未闭合项

> 路径更新：由于 C/E 盘空间不足，A05 构建输出已迁移至 `D:\aerie-dist-v045`；此前记录中的 `C:\aerie-dist-v045` 为迁移前路径。

- `npm run check:all` 的 `check:tokens` 仍报告历史 CSS 中 100 个硬编码颜色值；这会阻断该质量门禁，但不影响当前 Vite 构建或运行。需单独进行 CSS token 化，不应通过放宽扫描器掩盖。
- 全量 Python 测试中仍有旧 `test_persona_hub.py` 把 `yita_default/伊塔` 写死为默认契约；与新的商业默认契约冲突，需要迁移测试夹具后才能宣称全量测试通过。
- A05 GitHub Release 仍为 404；真实 Windows 安装/升级/卸载和干净用户配置冒烟尚未执行。
