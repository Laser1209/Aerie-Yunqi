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
    metrics: [{ value: '7', label: 'Office Tools' }],
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
]

export type ProductStatus = 'shipped' | 'building' | 'planned' | 'gated'

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
    description: '正在实现可取消、可重试、可恢复的 Request 队列与请求级状态。',
    status: 'building',
  },
  {
    phase: 'Phase 05-07',
    title: 'SSE, Context Budget & Streaming',
    titleZh: '恢复、上下文预算与拟人化流式输出',
    description: '统一事件、SSE 续连、Token Budget、摘要、Typing、多气泡与 pacing。',
    status: 'planned',
  },
  {
    phase: 'Phase 08',
    title: 'Proactive Feedback & User Settings',
    titleZh: '主动反馈、频控与用户设置',
    description: '把主动消息的反馈、频控与用户偏好纳入可观察、可暂停的设置闭环。',
    status: 'planned',
  },
  {
    phase: 'Phase 09-10',
    title: 'Image Assets & Delivery',
    titleZh: '图片资产、理解、生成与投递',
    description: '由 Core 持有规范图片资产，并完成理解、生成、审核与投递闭环。',
    status: 'planned',
  },
  {
    phase: 'Phase 11-12',
    title: 'WorldPort & Deterministic World',
    titleZh: '世界接口与确定性关系模型',
    description: 'Plugin Host、InProcess Adapter、关系与 SelfModel 先在进程内稳定下来。',
    status: 'planned',
  },
  {
    phase: 'Phase 13',
    title: 'Remote Sidecar',
    titleZh: 'world.db 与远端 Sidecar',
    description: '依赖 Phase 12；以前置验收为门槛，再引入 Outbox、ACK cursor 与监管。',
    status: 'gated',
  },
  {
    phase: 'Phase 14-15',
    title: 'Approval Loop & Dashboard',
    titleZh: '候选审批、World Dashboard 与发布',
    description: '世界图片候选、主动消息审批、插件健康和 Creative Workshop。',
    status: 'planned',
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
    date: 'Now',
    category: 'Request Reliability',
    title: 'Every message gets its own durable state.',
    titleZh: '持久 Request 队列正在建设',
    summary: '目标是让请求可排队、取消、重试并在重启后恢复，同时保留旧同步路径兼容性。',
    highlights: ['Cancel & retry', 'Restart recovery', 'Per-request state'],
    status: 'building',
  },
  {
    id: 'phase05-08',
    version: 'Phase 05-08',
    date: 'Next',
    category: 'Conversation Quality',
    title: 'Recovery first, then a more human rhythm.',
    titleZh: 'SSE、上下文预算、流式节奏与主动反馈',
    summary: '先统一事件和恢复语义，再扩展完整上下文、长期记忆、Typing、多气泡与用户反馈。',
    highlights: ['SSE recovery', 'Context budget', 'Pacing'],
    status: 'planned',
  },
  {
    id: 'phase09-15',
    version: 'Phase 09-15',
    date: 'Later',
    category: 'Visual & World Systems',
    title: 'Images and a world, without giving up control.',
    titleZh: '图片资产、WorldPort、Sidecar 与 Dashboard',
    summary: '图片链路先由 Core 建立所有权，再逐步推进确定性世界、受监管 Sidecar 和审批界面。',
    highlights: ['Image assets', 'WorldPort', 'Approval loop'],
    status: 'planned',
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
    phases: 'Phase 04-08',
    description: '请求状态、SSE 恢复、上下文预算、流式节奏与主动反馈逐层收口。',
  },
  {
    number: '02',
    title: 'Visual Intelligence',
    titleZh: '让图片成为受控的一等资产',
    phases: 'Phase 09-10',
    description: '从规范存储开始，贯通理解、生成、审核、保留与投递。',
  },
  {
    number: '03',
    title: 'World Extension',
    titleZh: '在可靠边界内扩展一个世界',
    phases: 'Phase 11-15',
    description: 'WorldPort、确定性状态、Sidecar、审批闭环与 Dashboard 按前置门禁推进。',
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
