# 功能包分发源（Cloudflare R2）

功能包本体不进安装包，用户从官方站点下载 `.aeriepack`。本目录是**发布侧**的
最小工具集：一个 R2 桶 + 一个上传脚本 + 一份 catalog 模板。

```
tools/plugin-registry/
├── wrangler.toml      # R2 桶绑定
├── upload.mjs         # 上传 dist/*.aeriepack + 生成 catalog.json
└── README.md
```

## 为什么选 R2

| 事实 | 影响 |
|---|---|
| **出网流量免费** | 4 个包约 1.7GB，千次下载也是 0 元 |
| **原生支持 HTTP Range** | 桌面端下载器正是靠它做断点续传（`plugin-manager.js`） |
| **catalog 放 R2** | 加包 / 改版本号**不用重发客户端**（客户端按 `AERIE_PLUGIN_CATALOG_URL` 拉） |
| 前面可挂 Worker | 将来要鉴权 / 灰度 / 签名时不用改客户端约定（仓库已有 `tools/relay-gateway/` 先例） |

仓库已经在用 R2：`tools/telemetry-receiver/wrangler.toml` 绑了 `aerie-diagnostics` 桶。

## 你要手动做的 3 件事

1. **建桶**（若还没有）：
   ```bash
   npx wrangler r2 bucket create aerie-plugins
   ```
2. **让桶可公开读**：在 Cloudflare 控制台给桶绑一个自定义域名（或
   `r2.dev` 公共开发域名）。记下形如 `https://plugins.example.com` 的地址。
3. **回填两处地址**：
   - 客户端：环境变量 `AERIE_PLUGIN_CATALOG_URL=https://plugins.example.com/catalog.json`
   - 上传脚本：`PUBLIC_BASE=https://plugins.example.com`

## 上传 / 更新

```bash
# 1) 先在仓库根装配产物（含 SHA256SUMS）
python scripts/build_plugin_pack.py --all

# 2) 上传（上传后自动生成 catalog.json 并一起传上去）
cd tools/plugin-registry
PUBLIC_BASE=https://plugins.example.com node upload.mjs ../../dist
```

生成的 `catalog.json` 结构：

```json
{
  "schema": 1,
  "packs": [
    {
      "id": "knowledge",
      "available": true,
      "sizeMb": 0.004,
      "api_level": 1,
      "min_core": "0.3.2",
      "restart_required": true,
      "urls": ["https://plugins.example.com/packs/knowledge-1.0.0.aeriepack"],
      "sha256": "…"
    }
  ]
}
```

客户端 `loadCatalog()` 会把它与**内置** `plugin-catalog.json` **按 id 合并**：
远程只做增量 / 覆盖同名项，所以远程拉挂时模块中心仍列出内置 4 个包
（`electron/tests/plugin-catalog-remote.test.js` 钉住这条）。
