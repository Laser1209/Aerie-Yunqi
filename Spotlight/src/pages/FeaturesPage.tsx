import PageShell from '../components/PageShell'
import PageIntro from '../components/PageIntro'
import { DocumentIcon, LightbulbIcon, ControlIcon, GlobeIcon, ClockIcon } from '../components/icons'
import type { SVGProps } from 'react'

const features = [
  { icon: GlobeIcon, title: 'Desktop Presence', subtitle: '灵动岛与桌面壳', body: '聊天窗、侧边栏、托盘与媒体控制，把 AI 自然嵌入 Windows 桌面。' },
  { icon: ControlIcon, title: 'Tool Matrix', subtitle: '智能工具矩阵', body: '知识库、待办、日历、天气、截图和系统工具，20+ 能力统一调度。' },
  { icon: ClockIcon, title: 'Proactive Care', subtitle: '主动关怀', body: '定时、情绪与事件三类触发，让陪伴不必等待一句提问。' },
  { icon: LightbulbIcon, title: 'Persona Hub', subtitle: '个性化体验', body: '自定义人设、随时切换，搭配 5+ 主题塑造专属桌面伙伴。' },
  { icon: DocumentIcon, title: 'Local Data', subtitle: '本地数据', body: '每日自动备份与一键迁移，关键数据优先留在自己的设备。' },
  { icon: ControlIcon, title: 'Self Healing', subtitle: '故障自愈', body: '覆盖 14 类故障的自动恢复与运行守护，减少长期使用中的中断。' },
] satisfies Array<{ icon: (props: SVGProps<SVGSVGElement>) => JSX.Element; title: string; subtitle: string; body: string }>

export default function FeaturesPage() {
  return (
    <PageShell videoSrc="/videos/features.mp4" scrollable>
      <div className="min-h-screen px-6 pb-10 pt-28 md:px-16 lg:px-20">
        <PageIntro label="Features" title={'Built for every\npart of your day'} />
        <div className="mt-10 grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {features.map((feature) => (
            <article key={feature.title} className="liquid-glass flex min-h-[210px] flex-col rounded-[1.25rem] p-5">
              <div className="liquid-glass flex h-10 w-10 items-center justify-center rounded-xl">
                <feature.icon className="h-5 w-5" />
              </div>
              <div className="mt-auto pt-8">
                <p className="text-[11px] uppercase tracking-[0.14em] text-white/60">{feature.subtitle}</p>
                <h2 className="mt-1 font-heading text-3xl italic leading-none">{feature.title}</h2>
                <p className="mt-3 text-sm font-light leading-snug text-white/80">{feature.body}</p>
              </div>
            </article>
          ))}
        </div>
      </div>
    </PageShell>
  )
}
