# 功能包（Feature Packs）

本目录存放**一方功能包**的源码与装配产物。功能包让"重型能力"（浏览器内核、向量库、
语音模型、变声权重）不进入核心安装包，而是按需下载到 `userData/plugins`。

> **本目录不进安装包**：`electron/electron-builder.yml` 的 `extraResources`
> 只放行 `core/ config/ tools/ ... skills/` 等源码目录，`plugins/**` 与 `models/**`
> 都不在白名单里（`tests/test_plugin_pack_not_packaged.py` 钉住这条）。
> 用户从官方站点下载 `.aeriepack`，由桌面端「模块中心」安装。

---

## 一、包目录形态

```
<plugins_root>/<pack_id>/
├── pack.json            # 清册（宿主唯一的入场券）
├── py/                  # 包自身的 Python 代码（追加进 sys.path）
│   └── <module>.py      #   必须导出 register(ctx)，可选 start/stop
├── vendor/              # 该包独占的三方库（同样追加进 sys.path）
├── models/              # 模型权重（用 ctx.pack_path("models", ...) 取绝对路径）
├── bin/                 # 内置可执行文件（如 Chromium）
└── .aerie-installed     # 安装准入标记（模块中心安装时写入；开发态豁免）
```

`<plugins_root>` 由 `core/paths.py::plugins_dir()` 决定：

- 打包态 → `userData/plugins`（免管理员、卸载不删）
- 开发态 → 仓库根 `plugins/`（与源码同级，便于调试）

## 二、pack.json 字段

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | ✅ | 包 id，必须与目录名一致（宿主按 id 去重，多版本取最高） |
| `version` | ✅ | 语义版本；同 id 多目录时版本高的胜出 |
| `api_level` | ✅ | 契约版本，**一期要求精确等于 `core/plugin_host.py::API_LEVEL`** |
| `min_core` | | 需要的最低核心版本（`core/version.py::APP_VERSION` 比对） |
| `entry` | ✅ | `模块名:函数名`，宿主 import 后调用 `register(ctx)` |
| `lifecycle.start` / `stop` | | `模块名:函数名`；`start(companion)` 可返回协程 |
| `tools` | | 本包注册的工具名（供面板展示与冲突排查） |
| `vendored` | | vendor/ 内含的三方库清单（发布说明用） |
| `assets` | | models/bin 等随包资源清单（发布说明用） |
| `settings_schema` | | 本包在 `settings.yaml → plugins.<id>` 下的配置项 |
| `feature_flags` | | 与本包绑定的开关名（**声明用**；宿主一期不读取，开关由 `settings.yaml → plugins.<id>` 行为参数控制） |
| `restart_required` | | 改动是否需重启（下载器提示用） |

## 三、五条硬约束（违反会被拒载或造成故障）

1. **顶层禁止 import 重库**。`register(ctx)` 只做注册；`chromadb` / `torch` /
   `playwright` / `sherpa_onnx` 一律延迟到 `start(companion)` 里加载 ——
   发现阶段只扫目录 + 读清单，import 重库会让整个后端启动变慢甚至卡死。
2. **工具名不得与 `tools/` 内置工具重名**。`ToolRegistry.register()` 是**覆盖**语义，
   且核心在包之后注册（`companion.py::_register_tools` 先包后核心），
   重名会让包里的实现被静默顶掉。重名能力（如 `browser_*`）必须由核心侧按配置
   主动让位（见 `tools/__init__.py::_browser_backend()`）。
3. **失败必须软着陆**。`start()` 抛异常只会把该包标成 `broken`，核心继续跑；
   包内**不允许**吞掉异常后假装成功（例如 chromadb 缺失要返回
   `{"status": "unavailable", ...}` 而不是空结果）。
4. **模型/二进制路径走 `ctx.pack_path(...)`**，绝不写绝对路径 —— 用户可能把
   `userData` 装在任意盘符。
5. **只通过 `ctx` 五件套接入**：`tool_registry` / `add_api_router` / `emit` /
   `pack_path` / `get_config`。包**不允许**反向 import `core.*` 的内部模块，
   也不允许读取 `settings.yaml` 之外的全局状态（依赖方向由
   `tests/test_plugin_host.py` 守卫）。

## 四、构建与发布

```bash
# 装配单个包（py + vendor + models → SHA256SUMS + zip）
python scripts/build_plugin_pack.py --pack knowledge

# 校验产物（篡改一个字节必须被发现）
python scripts/build_plugin_pack.py --verify dist/knowledge-1.0.0.aeriepack

# 输出可直接粘进 electron/src/plugin-catalog.json 的条目
python scripts/build_plugin_pack.py --pack knowledge --emit-catalog-entry
```

发布物上传到 Cloudflare R2 后，把 URL / SHA256 / 体积回填到
`electron/src/plugin-catalog.json`（`urls` / `sha256` / `sizeMb`）。

## 五、当前包清单

| 包 | 能力 | 依赖形态 | 现状 |
|---|---|---|---|
| `browser` | 13 个 `browser_*` 工具（打开/点击/填表/抓取/截图/标签页/PDF） | `vendor/playwright` + `bin/ms-playwright` | 代码就绪；内核二进制待装配（未装内核时工具返回可读错误） |
| `knowledge` | `knowledge_vector_search` / `knowledge_vector_upsert` | `vendor/chromadb`（缺失时返回 unavailable） | **可跑**（chromadb 在位时已实测检索/写入） |
| `voice-asr` | `voice_asr_transcribe` + 接管 `voice_service.asr_provider` | `models/sensevoice/*.onnx + tokens.txt` + `vendor/sherpa_onnx` | 代码就绪；模型待装配（缺失时返回 unavailable，不假装成功） |
| `voice-rvc` | `voice_rvc_convert` | `models/rvc/*.pth + *.index` + `py/rvc_converter.py` + `vendor/torch` | 包契约就绪；**权重与移植实现待补**（见该包模块头注释） |

> 装配后可用 `python tmp/scripts/probe_plugin_packs.py` 复跑一遍：
> 该探针用真实宿主装配全部包、打印状态与工具名，并断言 `torch/playwright/sherpa_onnx`
> **在装配阶段没有被 import**（顶层惰性加载守卫）。
