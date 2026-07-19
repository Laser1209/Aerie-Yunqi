import PageShell from '../components/PageShell'
import PageIntro from '../components/PageIntro'

const layers = [
  ['01', 'Electron Desktop Shell', '主窗口 · 灵动岛 · 侧边栏 · 托盘'],
  ['02', 'Python Intelligent Core', 'aiohttp · asyncio · 五阶段 Pipeline'],
  ['03', 'Providers · Tools · Emotion · Memory', 'Qwen · DeepSeek · Gemini · PAD 情感模型'],
  ['04', 'NapCat OneBot11 / QQ Bridge', 'WebSocket · 事件驱动主动推送'],
  ['05', 'Permission & Safety Gates', '3 级权限 · 4 道安全闸门 · 24h 回滚'],
]

export default function ArchitecturePage() {
  return (
    <PageShell videoSrc="/videos/architecture.mp4" scrollable>
      <div className="min-h-screen px-6 pb-10 pt-28 md:px-16 lg:px-20">
        <PageIntro
          label="Architecture"
          title={'Local intelligence,\nlayered with intent'}
          description="从桌面交互到智能调度，再到通信与安全边界，每一层都保持清晰、可控且本地优先。"
        />
        <div className="mt-10 grid gap-2 lg:ml-auto lg:mt-[-5rem] lg:w-[54%]">
          {layers.map(([number, title, body], index) => (
            <div key={number} className="relative">
              <article className="liquid-glass flex items-center gap-5 rounded-[1.25rem] px-5 py-4">
                <span className="font-heading text-2xl italic text-white/50">{number}</span>
                <div>
                  <h2 className="font-heading text-2xl italic leading-none md:text-3xl">{title}</h2>
                  <p className="mt-1 text-xs font-light text-white/65 md:text-sm">{body}</p>
                </div>
              </article>
              {index < layers.length - 1 && <div className="mx-auto h-2 w-px bg-white/30" />}
            </div>
          ))}
        </div>
      </div>
    </PageShell>
  )
}
