import { DocumentIcon, LightbulbIcon, ControlIcon } from '../components/icons'
import type { SVGProps } from 'react'

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
    body: '26 个静态注册办公工具与智能任务检测，从文档写作到文件整理，预览执行、7 天可撤销，办公学习一个就够了。',
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
    <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
      {cards.map((card) => (
        <article
          key={card.title}
          className="liquid-glass flex min-h-[340px] flex-col rounded-[1.25rem] p-6"
        >
          <div className="flex items-start justify-between gap-3">
            <div className="liquid-glass flex h-11 w-11 shrink-0 items-center justify-center rounded-[0.75rem]">
              <card.icon className="h-5 w-5 text-white" />
            </div>
            <div className="flex flex-wrap justify-end gap-1.5">
              {card.tags.map((tag) => (
                <span
                  key={tag}
                  className="liquid-glass whitespace-nowrap rounded-full px-3 py-1 text-[11px] text-white/90"
                >
                  {tag}
                </span>
              ))}
            </div>
          </div>
          <div className="flex-1" />
          <h2 className="font-heading text-3xl italic leading-none tracking-[-1px] md:text-4xl">
            {card.title}
          </h2>
          <p className="mt-3 max-w-[32ch] text-sm font-light leading-snug text-white/90">
            {card.body}
          </p>
        </article>
      ))}
    </div>
  )
}
