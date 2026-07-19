import FadingVideo from '../components/FadingVideo'
import { DocumentIcon, LightbulbIcon, ControlIcon } from '../components/icons'
import type { SVGProps } from 'react'

const CAPABILITIES_VIDEO =
  'https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260622_093722_ccfc7ebf-182f-419f-8a62-2dc02db7dd9d.mp4'

interface CapabilityCard {
  icon: (props: SVGProps<SVGSVGElement>) => JSX.Element
  title: string
  tags: string[]
  body: string
}

const cards: CapabilityCard[] = [
  {
    icon: DocumentIcon,
    title: 'Office Mode 办公模式',
    tags: ['文档写作', '文件整理', '任务检测', '豆包优先'],
    body: '7 大办公工具与智能任务检测，从文档写作到文件整理，预览执行、7 天可撤销，办公学习一个就够了。',
  },
  {
    icon: LightbulbIcon,
    title: 'Emotion 情感引擎',
    tags: ['PAD 模型', '人设切换', '主动关怀', 'QQ 接入'],
    body: 'PAD 三维情感模型与可切换人设，事件驱动的主动推送，经 NapCat 接入 QQ——陪伴不止于问答。',
  },
  {
    icon: ControlIcon,
    title: 'Control 电脑操控',
    tags: ['3 级权限', '键鼠自动化', '截图', '自进化 L4'],
    body: '三级权限的键鼠与 UIA 自动化、截图理解，配合自进化 L4 的 4 道安全闸门与 24 小时回滚，强大且可控。',
  },
]

export default function Capabilities() {
  return (
    <section className="relative min-h-screen overflow-hidden bg-black">
      <FadingVideo
        src={CAPABILITIES_VIDEO}
        className="absolute inset-0 w-full h-full object-cover z-0"
      />

      <div className="relative z-10 px-8 md:px-16 lg:px-20 pt-24 pb-10 flex flex-col min-h-screen">
        <div className="mb-auto">
          <p className="text-sm font-body text-white/80 mb-6">// Capabilities</p>
          <h2 className="font-heading italic text-6xl md:text-7xl lg:text-[6rem] leading-[0.9] tracking-[-3px] whitespace-pre-line">
            {'One companion,\nend to end'}
          </h2>
        </div>

        <div className="mt-16 grid grid-cols-1 md:grid-cols-3 gap-6">
          {cards.map((card) => (
            <div
              key={card.title}
              className="liquid-glass rounded-[1.25rem] p-6 min-h-[360px] flex flex-col"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="liquid-glass h-11 w-11 rounded-[0.75rem] flex items-center justify-center shrink-0">
                  <card.icon className="h-5 w-5 text-white" />
                </div>
                <div className="flex flex-wrap gap-1.5 justify-end">
                  {card.tags.map((tag) => (
                    <span
                      key={tag}
                      className="liquid-glass rounded-full px-3 py-1 text-[11px] text-white/90 font-body whitespace-nowrap"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              </div>
              <div className="flex-1" />
              <h3 className="font-heading italic text-3xl md:text-4xl tracking-[-1px] leading-none">
                {card.title}
              </h3>
              <p className="mt-3 text-sm text-white/90 font-body font-light leading-snug max-w-[32ch]">
                {card.body}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
