# OpenAI Ads 投放测量设置报告

## 当前结论

本仓库当前没有已配置的真实 Pixel ID、CAPI secret、注册系统或支付成功回调，因此本轮只加入默认关闭的营销页 Pixel 骨架，不创建伪造的订阅转化。未配置 ID 或未显式开启时完全 no-op，避免把本地桌面用户数据误送到广告系统。

## 已确认的转化边界

| 阶段 | 状态 | 说明 |
| --- | --- | --- |
| 营销页访问 | 可实现 | Spotlight 是 React/Vite 浏览器页面，可承载单点 Pixel 初始化 |
| 下载 | 可实现 | 下载按钮是明确的内容查看/下载意图，但需按实际页面组件接入 `contents_viewed` |
| 首次成功启动/试用激活 | 待接入 | 需要产品侧匿名激活事件或服务端试用创建边界 |
| 注册完成 | 未确认 | 当前未发现账户注册系统 |
| 订阅成功 | 未确认 | 当前未发现支付供应商、订单回调或 entitlement 服务 |

## 采用的初始模式

当前采用 browser Pixel-only 骨架：在 Spotlight 根入口单点初始化 `oaiq`，仅在 `VITE_OPENAI_ADS_MEASUREMENT_ENABLED=true` 且存在 `VITE_OPENAI_ADS_PIXEL_ID` 时发送 `page_viewed` / `contents_viewed`。当试用或订阅服务拥有真实成功回调后，再采用 Pixel+CAPI，并由服务端生成同一 `event_id` 做去重。

## 本轮实现与验证

- 新增 `Spotlight/src/analytics/openaiAds.ts`，单点初始化、无 Pixel ID 或未显式开启时完全 no-op。
- `Spotlight/src/main.tsx` 发送营销页 `page_viewed`；首页和下载页的 A05 下载入口发送 `contents_viewed`。
- 未发送用户标识、聊天内容、音频、屏幕内容、Persona 字段、`oppref` 或 CAPI 请求；当前没有 CAPI 事件。
- `Spotlight` 生产构建成功；CAPI secret 暴露扫描无发现；Ads 静态检查通过。
- 浏览器实测默认关闭状态：A05 下载链接可见，`window.oaiq` 不存在，Ads 脚本注入数量为 0，页面无 console error/warn。

启用前仍需由运营/法务确认真实 Pixel ID、营销页 consent/opt-out 规则和 canonical origin。配置完成后应重新运行 Ads 静态检查，并确认只在同意后加载脚本。

## 明确跳过的事件

- `registration_completed`：没有确认的注册成功边界。
- `trial_started`：目前没有试用创建/激活服务端事件；首次启动不能直接等同于试用开始。
- `subscription_created`：没有支付供应商和订单状态回调。
- `checkout_started`、`order_created`：当前产品没有结账和订单模型。
- `lead_created`、`appointment_scheduled`：不属于当前桌面产品漏斗。

## 隐私与安全边界

- 不采集聊天正文、原始音频、屏幕内容、私有 Persona 字段或 API key。
- CAPI secret 只能放服务端 secret manager/环境变量，不能进入 Renderer、安装包、日志或报告。
- CAPI Web 事件必须使用清理后的 HTTP(S) `source_url`，去除 query/fragment；`oppref` 只透传原始不透明值。
- 转化上报必须是非阻塞的；广告服务失败不能影响下载、启动、试用或支付成功。

## 投放前置条件

1. 确认广告账户和真实 Pixel ID。
2. 确认 consent/opt-out 规则及营销页 canonical origin。
3. 确认试用和订阅供应商、成功回调、服务端 secret 名称及去重 ID 生成位置。
4. 接入后运行 Ads 静态检查与无密钥扫描，再做小预算封闭测试。

部署前必须由运营和法务复核隐私、用户同意、安全及数据处理要求。
