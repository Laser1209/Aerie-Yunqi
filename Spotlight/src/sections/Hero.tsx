import { motion } from 'framer-motion'
import { release } from '../config/release'
import BlurText from '../components/BlurText'
import { ArrowUpRight, PlayIcon, ClockIcon, GlobeIcon } from '../components/icons'

const stackNames = ['Electron', 'Python', 'NapCat', 'Qwen', 'DeepSeek']

const fadeIn = (delay: number) => ({
  initial: { filter: 'blur(10px)', opacity: 0, y: 20 },
  animate: { filter: 'blur(0px)', opacity: 1, y: 0 },
  transition: { duration: 0.8, delay, ease: 'easeOut' as const },
})

export default function Hero() {
  return (
    <section className="flex h-screen flex-col px-4 pt-24 text-center">
      <div className="flex flex-1 flex-col items-center justify-center">
        <motion.div
          {...fadeIn(0.4)}
          className="liquid-glass flex items-center gap-2.5 rounded-full py-1.5 pl-1.5 pr-4"
        >
          <span className="rounded-full bg-white px-2.5 py-0.5 text-[11px] font-semibold text-black">
            New
          </span>
          <span className="text-xs text-white/90">v{release.version} · 本地优先 AI 桌面伴侣</span>
        </motion.div>

        <div className="mt-6 max-w-3xl">
          <BlurText
            text="Your Private AI, Always Within Reach"
            className="font-heading text-5xl italic leading-[0.8] tracking-[-4px] text-white md:text-7xl lg:text-[5.5rem]"
          />
        </div>

        <motion.p
          {...fadeIn(0.8)}
          className="mt-4 max-w-2xl text-sm font-light leading-tight text-white md:text-base"
        >
          Aerie · 云栖由 Electron 桌面壳与 Python
          智能内核组成，办公学习、情感陪伴、电脑操控、主动关怀——一个就够了。
        </motion.p>

        <motion.div {...fadeIn(1.1)} className="mt-6 flex items-center gap-6">
          <a
            href={release.url}
            download={release.filename}
            className="liquid-glass-strong flex items-center gap-2 rounded-full px-5 py-2.5 text-sm font-medium text-white"
          >
            获取便携版
            <ArrowUpRight className="h-4 w-4" />
          </a>
          <button className="flex items-center gap-2 text-sm text-white/90">
            <PlayIcon className="h-4 w-4" />
            观看演示
          </button>
        </motion.div>

        <motion.div {...fadeIn(1.3)} className="mt-8 flex gap-3 md:gap-4">
          <div className="liquid-glass w-[170px] rounded-[1.25rem] p-4 text-left md:w-[220px] md:p-5">
            <ClockIcon className="h-6 w-6 text-white/90" />
            <div className="mt-4 font-heading text-4xl italic leading-none tracking-[-1px]">7×24</div>
            <div className="mt-2 text-xs font-light text-white/80">全天候待命的桌面伴侣</div>
          </div>
          <div className="liquid-glass w-[170px] rounded-[1.25rem] p-4 text-left md:w-[220px] md:p-5">
            <GlobeIcon className="h-6 w-6 text-white/90" />
            <div className="mt-4 font-heading text-4xl italic leading-none tracking-[-1px]">20+</div>
            <div className="mt-2 text-xs font-light text-white/80">内置工具系统，开箱即用</div>
          </div>
        </motion.div>
      </div>

      <motion.div {...fadeIn(1.4)} className="flex flex-col items-center gap-4 pb-7">
        <div className="liquid-glass rounded-full px-4 py-1.5 text-xs text-white/80">
          深受效率玩家与 AI 爱好者喜爱
        </div>
        <div className="flex flex-wrap items-center justify-center gap-x-8 gap-y-1 md:gap-16">
          {stackNames.map((name) => (
            <span key={name} className="font-heading text-xl italic tracking-tight md:text-3xl">
              {name}
            </span>
          ))}
        </div>
      </motion.div>
    </section>
  )
}
