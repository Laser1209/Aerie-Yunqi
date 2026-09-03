export type FeatureIconName = 'desktop' | 'office' | 'tools' | 'proactive' | 'persona' | 'safety'
export type FeatureTone = 'aqua' | 'cyan' | 'ice'

export interface ProductMetric {
  value: string
  label: string
}

export interface ProductFeature {
  id: string
  icon: FeatureIconName
  tone: FeatureTone
  title: string
  titleZh: string
  description: string
  details: string[]
  metrics: ProductMetric[]
}

export const productFeatures: ProductFeature[] = [
  {
    id: 'desktop-shell',
    icon: 'desktop',
    tone: 'aqua',
    title: 'Electron Desktop Shell',
    titleZh: '融入桌面的交互外壳',
    description: '灵动岛、聊天窗、侧边栏与托盘保持常驻，让 Aerie 不必占据你的工作流中心。',
    details: ['Dynamic Island', 'Chat & Sidebar', '5+ themes'],
    metrics: [{ value: '5+', label: 'Themes' }],
  },
  {
    id: 'office-mode',
    icon: 'office',
    tone: 'ice',
    title: 'Office Mode',
    titleZh: '从对话进入任务',
    description: '自动识别文档、表格、日程与分析意图，调度专属工具并将产物保存到可配置目录。',
    details: ['Auto / Chat / Office', 'Device-aware', 'Provider Routing'],
    metrics: [{ value: '26', label: 'Office Tools' }],
  },
  {
    id: 'tool-matrix',
    icon: 'tools',
    tone: 'cyan',
    title: '20+ Tools',
    titleZh: '一个入口，多种行动',
    description: '知识库、待办、日历、天气、截图、文件整理与系统能力通过统一工具矩阵协同。',
    details: ['Preview before action', '7-day undo', 'Audit Trail'],
    metrics: [{ value: '7 days', label: 'File Undo' }],
  },
  {
    id: 'proactive-messenger',
    icon: 'proactive',
    tone: 'aqua',
    title: 'Proactive Messenger',
    titleZh: '会在合适时刻主动出现',
    description: '定时、情绪与事件三类触发源共同工作，在频控与静默时段约束下送达关怀和提醒。',
    details: ['Cron', 'Emotion', 'Event-driven'],
    metrics: [{ value: '9', label: 'Scenes' }],
  },
  {
    id: 'persona-emotion',
    icon: 'persona',
    tone: 'ice',
    title: 'Persona & Emotion',
    titleZh: '连续而非一次性的陪伴',
    description: 'Persona Hub 管理可切换人设，PAD 情感模型与四槽累积系统让回应保持状态连续性。',
    details: ['Persona Hub', 'PAD Model', 'Long-term Memory'],
    metrics: [{ value: '4', label: 'Emotion Slots' }],
  },
  {
    id: 'local-safety',
    icon: 'safety',
    tone: 'cyan',
    title: 'Local Safety & Recovery',
    titleZh: '行动有边界，也有退路',
    description: '电脑操控采用 3 级权限，文件整理提供 7 天撤销；自进化链路另设 4 道安全闸门与 24h 回滚，并覆盖 14 类故障自愈。',
    details: ['Computer control: 3 levels', 'File organizer: 7-day undo', 'Self-evolution: 4 gates / 24h rollback'],
    metrics: [{ value: '14', label: 'Failure Categories' }],
  },
  {
    id: 'context-memory',
    icon: 'persona',
    tone: 'ice',
    title: 'Context Memory',
    titleZh: '连续而非碎片化的记忆',
    description: '轮次化热窗口、温层摘要分桶、通道感知注入与跨端时间线，让上下文跨越对话与设备保持连续。',
    details: ['P0-P3 layers', 'Summary buckets', 'Channel-aware'],
    metrics: [{ value: '1400+', label: 'Regression tests' }],
  },
  {
    id: 'world-simulation',
    icon: 'proactive',
    tone: 'aqua',
    title: 'World Simulation',
    titleZh: '一个有确定性的世界',
    description: '房间级精确定位、行为调度、天气与现实同步、百度地图整合，让陪伴具备空间与时间语境。',
    details: ['Room-level positioning', 'Behavior scheduler', 'Weather sync'],
    metrics: [{ value: '20+', label: 'Built-in places' }],
  },
  {
    id: 'unified-quote',
    icon: 'tools',
    tone: 'cyan',
    title: 'Unified Quote',
    titleZh: '引用在三个端一致',
    description: '桌面/QQ/移动统一引用上下文，图片与文件随引用注入模型，跨端消息可被精确定位与回应。',
    details: ['QQ message mapping', 'Attachments in context', 'Cross-channel'],
    metrics: [{ value: '3', label: 'Channels' }],
  },
  {
    id: 'persona-isolation',
    icon: 'persona',
    tone: 'ice',
    title: 'Persona Isolation',
    titleZh: '每个角色有独立记忆',
    description: '对话、记忆、头像与图片产出按 persona_id 隔离，切换角色后历史与召回全部跟随当前角色。',
    details: ['8-table persona scoping', 'Per-persona avatar', 'Memory isolation'],
    metrics: [{ value: '8', label: 'Scoped tables' }],
  },
  {
    id: 'mobile-companion',
    icon: 'desktop',
    tone: 'aqua',
    title: 'Mobile Companion',
    titleZh: '手机里的接收端',
    description: 'Android 移动网关多端会话、文件双向传输与账号鉴权，贴身提醒、电脑思考。',
    details: ['Multi-client session', 'File transfer', 'Account auth'],
    metrics: [{ value: 'Flutter', label: 'Dual-platform' }],
  },
  {
    id: 'admin-panel',
    icon: 'safety',
    tone: 'cyan',
    title: 'Admin Panel',
    titleZh: '可观测、可恢复的后台',
    description: '统计看板、决策日志、软删回收站、记忆管理与审计留痕，操作可追溯、可撤销。',
    details: ['Stats dashboard', '7-day recycle bin', 'Audit trail'],
    metrics: [{ value: '7', label: 'Day retention' }],
  },
]

export interface ArchitectureLayerData {
  number: string
  title: string
  titleZh: string
  description: string
  signals: string[]
}

export const architectureLayers: ArchitectureLayerData[] = [
  {
    number: '01',
    title: 'Electron Desktop Shell',
    titleZh: '桌面交互层',
    description: 'Dynamic Island、主窗口、侧边栏与托盘，通过 contextBridge 和 IPC 进入本地服务。',
    signals: ['Electron', 'contextBridge', 'IPC'],
  },
  {
    number: '02',
    title: 'Python Intelligent Core',
    titleZh: '智能编排层',
    description: 'aiohttp 与 asyncio 驱动消息管线、请求状态、任务调度和本地业务服务。',
    signals: ['aiohttp', 'asyncio', 'Pipeline'],
  },
  {
    number: '03',
    title: 'Providers / Tools / Emotion / Memory',
    titleZh: '认知与行动层',
    description: '多 Provider 路由、20+ 工具、PAD 情感模型与分层记忆共同生成下一步行动。',
    signals: ['Qwen / DeepSeek / Gemini', 'Tool Matrix', 'PAD'],
  },
  {
    number: '04',
    title: 'NapCat / QQ Bridge',
    titleZh: '通信触达层',
    description: '通过 OneBot11 WebSocket 接入 QQ，并承接定时、情绪和事件驱动的主动消息。',
    signals: ['OneBot11', 'WebSocket', 'Event-driven'],
  },
  {
    number: '05',
    title: 'Permission & Safety Gates',
    titleZh: '权限与恢复边界',
    description: '电脑操控的三级权限、文件整理的 7 天撤销，以及自进化的四道安全闸门与 24h 回滚分别守住各自边界。',
    signals: ['Scoped Controls', 'Audit', 'Recovery'],
  },
  {
    number: '06',
    title: 'Context Memory System',
    titleZh: '上下文记忆层',
    description: '轮次化热窗口、温层摘要分桶、通道感知注入、决策自省段与跨端时间线，让上下文连续且可追溯。',
    signals: ['Summary buckets', 'Thinking trace', 'Timeline'],
  },
  {
    number: '07',
    title: 'World Simulation',
    titleZh: '世界模拟层',
    description: '房间级空间模型、每日行为调度、天气与现实同步、百度地图整合，为陪伴提供确定性的时间与空间语境。',
    signals: ['Room model', 'Behavior planner', 'Weather'],
  },
  {
    number: '08',
    title: 'Mobile Gateway & Unified Quote',
    titleZh: '多端触达与统一引用层',
    description: 'Android 移动网关多端会话与文件传输，配合三端统一引用上下文，让消息、图片与文件跨端一致可达。',
    signals: ['Mobile gateway', 'Quote V2', 'Multi-client'],
  },
]

export type ProductStatus = 'shipped' | 'mainline' | 'building' | 'planned' | 'gated'

export interface RoadmapMilestone {
  phase: string
  title: string
  titleZh: string
  description: string
  status: ProductStatus
}

export const architectureRoadmap: RoadmapMilestone[] = [
  {
    phase: 'Phase 00-03',
    title: 'Identity & conversation foundation',
    titleZh: '身份、Persona 真源与会话四表',
    description: '安全基线、主动消息 P0、Actor / Channel / Persona 和规范会话模型已完成。',
    status: 'shipped',
  },
  {
    phase: 'Phase 04',
    title: 'Persistent Request Queue',
    titleZh: '持久请求队列',
    description: '持久队列、请求级状态、取消、重试、重启恢复与纯附件请求已进入公开主线。',
    status: 'mainline',
  },
  {
    phase: 'Phase 05-07',
    title: 'SSE, Context Budget & Streaming',
    titleZh: '恢复、上下文预算与拟人化流式输出',
    description: 'SSE 续连、Renderer 去重、Token Budget、摘要、Typing、多气泡与 pacing 已完成主线验收。',
    status: 'mainline',
  },
  {
    phase: 'Phase 08',
    title: 'Proactive Feedback & User Settings',
    titleZh: '主动反馈、频控与用户设置',
    description: '跨重启 cooldown、反馈、mute、postpone 与设置 API 已形成可观察、可暂停的闭环。',
    status: 'mainline',
  },
  {
    phase: 'Phase 09-10',
    title: 'Image Assets & Delivery',
    titleZh: '图片资产、理解、生成与投递',
    description: 'Core 已持有规范图片资产，去重、缩略图、GC、理解、生成、审核与投递链路进入主线。',
    status: 'mainline',
  },
  {
    phase: 'Phase 11-12',
    title: 'WorldPort & Deterministic World',
    titleZh: '世界接口与确定性关系模型',
    description: 'WorldPort、InProcess Adapter、确定性关系状态与 SelfModel 已通过阶段实现与测试。',
    status: 'mainline',
  },
  {
    phase: 'Phase 13',
    title: 'Remote Sidecar',
    titleZh: 'world.db 与远端 Sidecar',
    description: '独立 Sidecar、world.db、Outbox、ACK cursor 与监管路径已进入主线，默认仍受 feature flag 控制。',
    status: 'mainline',
  },
  {
    phase: 'Phase 14-15',
    title: 'Approval Loop & Dashboard',
    titleZh: '候选审批、World Dashboard 与发布',
    description: '候选审批、World Dashboard、快照 API、插件健康与 Creative Workshop 预览已经落地主线。',
    status: 'mainline',
  },
  {
    phase: 'P0-P3',
    title: 'Context Memory System',
    titleZh: '上下文记忆系统',
    description: '轮次化热窗口、温层摘要分桶、通道感知注入、决策自省段与跨端时间线已全量落地并回归验证。',
    status: 'shipped',
  },
  {
    phase: 'P4a / P4b',
    title: 'Admin Platform',
    titleZh: '后台管理平台',
    description: '统计看板、决策日志、软删回收站、记忆全量管理与审计留痕已交付，操作可追溯可撤销。',
    status: 'shipped',
  },
  {
    phase: 'Persona Isolation',
    title: 'Persona-Scoped Dialogue & Memory',
    titleZh: '角色级对话与记忆隔离',
    description: '8 张表 persona_id 维度、会话按角色哈希、记忆与头像按角色分区，切换角色零串扰。',
    status: 'shipped',
  },
  {
    phase: 'Quote V2',
    title: 'Unified Quote',
    titleZh: '三端引用统一',
    description: '桌面/QQ/移动统一引用上下文，qq_message_id 双向映射，被引用图片与文件注入模型上下文。',
    status: 'shipped',
  },
]

export type JournalStatus = Exclude<ProductStatus, 'gated'>

export interface JournalEntryData {
  id: string
  version: string
  date: string
  category: string
  title: string
  titleZh: string
  summary: string
  highlights: string[]
  status: JournalStatus
}

export const journalEntries: JournalEntryData[] = [
  {
    id: 'beta-031',
    version: '0.3.2-beta.0903-A09',
    date: '2026-08-14',
    category: 'Release Candidate',
    title: 'A warm first hello, a guided first run.',
    titleZh: '开场动画、新手教程与硬件诊断落地',
    summary: '新增不可跳过的开场动画、首次使用新手教程与内嵌使用指南，并接入本地硬件指纹用于诊断打包。',
    highlights: ['Unskippable splash', 'Guided onboarding', 'Hardware fingerprint'],
    status: 'shipped',
  },
  {
    id: 'beta-030',
    version: '0.3.0-Beta.1',
    date: '2026-08-13',
    category: 'Major Incremental Release',
    title: 'Memory learns the channel, persona learns the boundary.',
    titleZh: '上下文记忆、后台管理与角色隔离全面落地',
    summary: '上下文记忆系统 P0-P3、后台管理平台 P4a/P4b、世界模拟房间级定位与行为调度、生图链路加固、Aerie WS 多 Key 轮询与 ASR 回退、电脑操控权限 v2、人设 AI 生成器与角色级对话记忆隔离。',
    highlights: ['Context memory P0-P3', 'Admin platform P4', 'Persona isolation', 'Room-level world'],
    status: 'shipped',
  },
  {
    id: 'beta-021',
    version: '0.2.1-beta.1',
    date: '2026-08-11',
    category: 'Incremental Beta',
    title: 'A sharper eye, a warmer home.',
    titleZh: '发图体验与世界迁移重庆落地',
    summary: '聊天主动触发生图、AI 回复语义触发与图片表达层次认知、同主题去重与 LLM 提示词接力；世界模拟迁移重庆、百度地图接入、对话知识库与身份锚定。',
    highlights: ['Chat-triggered photos', 'Dialogue knowledge', 'Chongqing world', 'Identity anchoring'],
    status: 'shipped',
  },
  {
    id: 'beta-020',
    version: '0.2.0-beta.1',
    date: '2026-08-10',
    category: 'Major Beta Release',
    title: 'From a chat window to a companion.',
    titleZh: '陪伴融合、世界模拟与移动端网关落地',
    summary: 'P1 陪伴融合（内在状态/同理心/记忆可见性）、三端撤回、多模态生图与三视图、世界模拟（Phase 11-15）、专用向量知识库、移动端网关与分层简报资讯。',
    highlights: ['P1 companion fusion', 'Multi-channel recall', 'Vector KB', 'Mobile gateway'],
    status: 'shipped',
  },
  {
    id: 'beta-baseline',
    version: '0.1.0-beta.1',
    date: '2026-07-19',
    category: 'Internal Beta Baseline',
    title: 'A quieter version number, a clearer promise.',
    titleZh: '内测基线正式建立',
    summary: '从 v13.9.8 重置版本号，以 beta 规范渐进收敛后续体验与可靠性。',
    highlights: ['Semantic beta cadence', 'Stable baseline'],
    status: 'shipped',
  },
  {
    id: 'v13-9',
    version: '13.9.x',
    date: '2026-07-18 / 19',
    category: 'Iteration & Final Audit',
    title: 'Progress closed with an honest audit.',
    titleZh: '功能推进，也把未解决问题写进审计',
    summary: '13.9.1-13.9.4 推进办公目录、QQ RPC、权限与任务执行；13.9.8 收尾审计确认 15 个待修复问题，其中 5 个 Critical、6 个 High。',
    highlights: ['Office & permission updates', '15 pending bugs', '5 Critical / 6 High'],
    status: 'shipped',
  },
  {
    id: 'v13',
    version: '13.0.0',
    date: '2026-07-18',
    category: 'Major Capability Release',
    title: 'Conversation learned when to become work.',
    titleZh: '办公模式、双层校验与事件驱动推送落地',
    summary: '七个办公工具、Accuracy Guard + Quality Judge、三类主动触发源与 Persona Hub 同期发布。',
    highlights: ['7 office tools', 'Dual validation', '3 trigger sources'],
    status: 'shipped',
  },
  {
    id: 'v12',
    version: '12.x',
    date: '2026-07-18',
    category: 'Desktop & Agent Foundation',
    title: 'Aerie moved from a window into the desktop.',
    titleZh: '灵动岛与 Agent 能力底座成形',
    summary: 'Dynamic Island、电脑操控、文件整理、文档写作、自进化 L4 和便携版打包构成桌面基础。',
    highlights: ['Dynamic Island', '7-day undo', '4 safety gates'],
    status: 'shipped',
  },
  {
    id: 'phase04',
    version: 'Phase 04',
    date: '2026-07-20',
    category: 'Request Reliability',
    title: 'Every message gets its own durable state.',
    titleZh: '持久 Request 队列完成主线实现',
    summary: '请求现在可排队、取消、重试并在重启后恢复，同时保留旧同步路径兼容性与纯附件请求。',
    highlights: ['Cancel & retry', 'Restart recovery', 'Attachment-only requests'],
    status: 'mainline',
  },
  {
    id: 'phase05-08',
    version: 'Phase 05-08',
    date: '2026-07-20 / 21',
    category: 'Conversation Quality',
    title: 'Recovery first, then a more human rhythm.',
    titleZh: 'SSE、上下文预算、流式节奏与主动反馈进入主线',
    summary: '统一事件与恢复语义已落地，并完成上下文预算、摘要、Typing、多气泡、pacing、跨重启频控和用户反馈。',
    highlights: ['SSE recovery', 'Context budget', 'Feedback & pacing'],
    status: 'mainline',
  },
  {
    id: 'phase09-15',
    version: 'Phase 09-15',
    date: '2026-07-21',
    category: 'Visual & World Systems',
    title: 'Images and a world, without giving up control.',
    titleZh: '图片资产、WorldPort、Sidecar 与 Dashboard 完成主线实现',
    summary: 'Core 图片所有权、确定性世界、受监管 Sidecar、候选审批、Dashboard 快照与 Creative Workshop 已通过阶段测试。',
    highlights: ['Image delivery', 'Remote Sidecar', 'World Dashboard'],
    status: 'mainline',
  },
]

export interface ProductTrack {
  number: string
  title: string
  titleZh: string
  phases: string
  description: string
}

export const productTracks: ProductTrack[] = [
  {
    number: '01',
    title: 'Reliability',
    titleZh: '先把每一次对话可靠送达',
    phases: 'Phase 04-08 · mainline',
    description: '请求状态、SSE 恢复、上下文预算、流式节奏与主动反馈已进入主线，由 feature flag 控制启用范围。',
  },
  {
    number: '02',
    title: 'Visual Intelligence',
    titleZh: '让图片成为受控的一等资产',
    phases: 'Phase 09-10 · mainline',
    description: '规范存储、理解、生成、审核、保留与投递已贯通主线，由 feature flag 控制启用范围。',
  },
  {
    number: '03',
    title: 'World Extension',
    titleZh: '在可靠边界内扩展一个世界',
    phases: 'Phase 11-15 · mainline',
    description: 'WorldPort、确定性状态、Sidecar、审批闭环与 Dashboard 已进入主线，由 feature flag 控制启用范围。',
  },
  {
    number: '04',
    title: 'Context Memory',
    titleZh: '让记忆连续且可追溯',
    phases: 'P0-P3 · shipped',
    description: '轮次化热窗口、温层摘要分桶、通道感知注入与跨端时间线已交付，写入门一致性校验护航。',
  },
  {
    number: '05',
    title: 'Persona & Multi-client',
    titleZh: '角色隔离与多端触达',
    phases: 'Persona Isolation · shipped',
    description: '8 表角色隔离、移动网关、三端引用统一与后台管理平台，让每个角色与每个端都有清晰边界。',
  },
]

export interface DownloadRequirement {
  label: string
  value: string
  note: string
}

export const downloadRequirements: DownloadRequirement[] = [
  { label: 'OS', value: 'Windows 11', note: 'Windows 10 1809+ 亦在兼容范围' },
  { label: 'Disk', value: '~350 MB', note: '解压后的参考占用空间' },
  { label: 'Model', value: '1+ API Key', note: 'Qwen / DeepSeek / Gemini 等任选其一' },
  { label: 'QQ Bridge', value: 'NapCat v4.18.9', note: 'QQ 9.9.26+，仅 QQ 能力需要' },
]

export const localDataNotes = [
  '首次运行可能请求管理员权限，仅用于自启动与 Windows Task Scheduler。',
  'API Key 由本机配置管理；模型请求会发送给你选择的 Provider。',
  '对话与业务数据本地优先，并支持每日备份与一键迁移。',
] as const
