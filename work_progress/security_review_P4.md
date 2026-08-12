# P4（管理平台·统计看板）安全审查报告

- 审查时间：2026-08-13
- 审查范围：`35b7094..HEAD` 代码面（core 9 文件 +1314/-9；含 `/api/admin/*`、软删级联、解锁门闩、状态重置、统计端点）
- 方法：TRAE-security-review（Pass A 基线 → Pass B 偏差图 → Pass C source→sink 全链）

## 结论

**1 项 HIGH（authz_bypass），0 项 MEDIUM/LOW 存活。**

| # | Category | Title | Severity | Confidence | Evidence | Location |
|---|---|---|---|---|---|---|
| 1 | authz_bypass | CORS 通配 + 无鉴权 unlock 端点回传管理 token，任意网站可解锁并清空本地数据 | HIGH | 0.85 | 恶意网页 fetch 127.0.0.1:7890/api/admin/unlock（CORS `*` 放行预检+读响应）→ 拿 token → fetch /api/admin/trash/purge（X-Aerie-Admin-Token + {"all":true}）物理删除回收站，或枚举批量 trash 级联删消息/分桶/记忆/向量 | core/api_server.py:2661-2665（unlock 回传 token）；:2722-2727（purge） |

## 攻击链（source → sink）

1. 受害浏览器打开恶意网页（Aerie 本地运行中，127.0.0.1:7890）
2. `fetch('http://127.0.0.1:7890/api/admin/unlock', {method:'POST'})`
   - 预检 `OPTIONS` 被 CORS `allow_origins=["*"]` + `allow_methods=["*"]` + `allow_headers=["*"]` 放行
   - 响应 `{"status":"ok","token":<随机token>}` 跨源可读（`Access-Control-Allow-Origin: *`）
3. `fetch('http://127.0.0.1:7890/api/admin/trash/purge', {method:'POST', headers:{'X-Aerie-Admin-Token':token}, body:'{"all":true}'})`
   - `_require_admin`（api_server.py:2613-2619）校验通过（已 unlock + token 正确）
   - 物理删除回收站内全部消息/分桶/长期记忆/Chroma 向量；或先枚举 `/api/admin/conversations` 后批量 trash 级联删

- 回环绑定（host=127.0.0.1）不缓解：浏览器运行在受害机本机，属 localhost 边界内请求
- 前提：浏览器未启用 Private Network Access 强制（当前主流浏览器默认未强制）+ 受害者在应用运行期间访问任意恶意站点

## 修复建议（prose，未改动代码）

1. 对 `/api/admin/*` 收紧 CORS：拒绝 `*` 来源，仅放行 `null`/`file://`/`app://`（Electron file:// 渲染）或按 Origin 白名单
2. unlock 改由 Electron main 进程经 `X-Aerie-Main-Token`（既有的内部写端点鉴权）置位，浏览器端不再直接可调
3. 或 token 不随 unlock 响应体回传：改服务端生成一次性挑战码，浏览器端用挑战码确权

## 已核验剔除项

- SQL 注入：admin_service.py 全部 `?` 参数化（channel/category/ids 绑定；layer 固定集合校验；IN 子句占位符）
- 路径穿越：`_STATE_FILES.get(kind)` 未知返回 400
- XSS：admin-window.js 全 textContent + CSP `script-src 'self'`
- Electron IPC admin:api 路径 `startsWith("/api/admin/")`：Starlette 不归一匹配 `..`，置信 <0.8
- token 比较时序侧信道：回环 + 256 位随机，不可演示利用


## 修复状态（2026-08-13 同日修复）
- **实现细节修正**：同源 POST 浏览器会带 Origin（如 http://127.0.0.1:7890），守卫同时放行服务端自身 Origin（request.url.scheme://netloc），浏览器模式不受影响；测试补充同源 POST 用例，admin API 4 例全绿。


- **已落地**：`core/api_server.py` 新增 `_admin_origin_guard` HTTP 中间件（L2598-2607），对 `/api/admin/*` 做 Origin 白名单校验（允许 空/file:///null/app://），任意 http/https 网页 Origin 一律 403——直接网页攻击链（fetch unlock → 拿 token → purge）已阻断；中间件先于 CORS 执行，跨源预检同样被 403 拦截。
- **测试**：`tests/test_admin_api.py::test_admin_cross_origin_guard_blocks_web_pages` 新增 7 断言（evil Origin 对 unlock/status/conversations/purge 全 403；无 Origin 与 file:///null 正常），admin 测试 17 例全绿。
- **残留风险（LOW，与计划已接受模型一致）**：sandboxed iframe 可伪造 `Origin: null` 绕过白名单，需受害者访问嵌有沙箱 iframe 的站点 + 未来 PNA 强制前；计划本身接受"门闩可被客户端伪造=防误触非防敌"，此残留处于该已接受边界内。
