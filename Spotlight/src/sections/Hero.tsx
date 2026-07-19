import { motion } from 'framer-motion'
import FadingVideo from '../components/FadingVideo'
import BlurText from '../components/BlurText'
import { ArrowUpRight, PlayIcon, ClockIcon, GlobeIcon } from '../components/icons'

const HERO_VIDEO =
  'https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260619_191346_9d19d66e-86a4-47f7-8dc6-712c1788c3b2.mp4'

const navLinks = ['Features', 'Architecture', 'Capabilities', 'Journal', 'Download']
const stackNames = ['Electron', 'Python', 'NapCat', 'Qwen', 'DeepSeek']

const fadeIn = (delay: number) => ({
  initial: { filter: 'blur(10px)', opacity: 0, y: 20 },
  animate: { filter: 'blur(0px)', opacity: 1, y: 0 },
  transition: { duration: 0.8, delay, ease: 'easeOut' as const },
})

export default function Hero() {
  return (
    <section className="relative h-screen overflow-hidden bg-black">
      <FadingVideo
        src={HERO_VIDEO}
        className="absolute left-1/2 top-0 -translate-x-1/2 object-cover object-top z-0"
        style={{ width: '120%', height: '120%' }}
      />

      <div className="relative z-10 flex flex-col h-full">
        {/* Navbar */}
        <header className="fixed top-4 left-0 right-0 z-50 flex items-center justify-between px-8 lg:px-16">
          <div className="liquid-glass h-12 w-12 rounded-full flex items-center justify-center">
            <img src="/aerie-logo.svg" alt="Aerie · 云栖" className="h-8 w-8 object-contain" />
          </div>
          <nav className="hidden md:flex liquid-glass rounded-full px-1.5 py-1.5 items-center">
            {navLinks.map((link) => (
              <a
                key={link}
                href="#"
                className="px-3 py-2 text-sm font-medium text-white/90 font-body"
              >
                {link}
              </a>
            ))}
            <a
              href="/Aerie-Cloud-0.1.0-beta.1-Setup.exe"
              download="Aerie · 云栖-0.1.0-beta.1-Setup.exe"
              className="ml-1 flex items-center gap-1.5 rounded-full bg-white px-4 py-2 text-sm font-medium text-black font-body"
            >
              获取便携版
              <ArrowUpRight className="h-4 w-4" />
            </a>
          </nav>
          <div className="h-12 w-12" />
        </header>

        {/* Main content */}
        <div className="flex-1 flex flex-col items-center justify-center pt-24 px-4 text-center">
          <motion.div
            {...fadeIn(0.4)}
            className="liquid-glass rounded-full flex items-center gap-2.5 pl-1.5 pr-4 py-1.5"
          >
            <span className="rounded-full bg-white px-2.5 py-0.5 text-[11px] font-semibold text-black font-body">
              New
            </span>
            <span className="text-xs text-white/90 font-body">
              v0.1.0-beta.1 · 本地优先 AI 桌面伴侣
            </span>
          </motion.div>

          <div className="mt-6 max-w-3xl">
            <BlurText
              text="Your Private AI, Always Within Reach"
              className="text-6xl md:text-7xl lg:text-[5.5rem] font-heading italic text-white leading-[0.8] tracking-[-4px]"
            />
          </div>

          <motion.p
            {...fadeIn(0.8)}
            className="mt-4 text-sm md:text-base text-white max-w-2xl font-body font-light leading-tight"
          >
            Aerie · 云栖由 Electron 桌面壳与 Python
            智能内核组成，办公学习、情感陪伴、电脑操控、主动关怀——一个就够了。
          </motion.p>

          <motion.div {...fadeIn(1.1)} className="mt-6 flex items-center gap-6">
            <a
              href="/Aerie-Cloud-0.1.0-beta.1-Setup.exe"
              download="Aerie · 云栖-0.1.0-beta.1-Setup.exe"
              className="liquid-glass-strong rounded-full px-5 py-2.5 flex items-center gap-2 text-sm font-medium text-white font-body"
            >
              获取便携版
              <ArrowUpRight className="h-4 w-4" />
            </a>
            <button className="flex items-center gap-2 text-sm text-white/90 font-body">
              <PlayIcon className="h-4 w-4" />
              观看演示
            </button>
          </motion.div>

          <motion.div {...fadeIn(1.3)} className="mt-8 flex gap-4">
            <div className="liquid-glass p-5 w-[220px] rounded-[1.25rem] text-left">
              <ClockIcon className="h-6 w-6 text-white/90" />
              <div className="text-4xl font-heading italic tracking-[-1px] leading-none mt-4">
                7×24
              </div>
              <div className="mt-2 text-xs text-white/80 font-body font-light">
                全天候待命的桌面伴侣
              </div>
            </div>
            <div className="liquid-glass p-5 w-[220px] rounded-[1.25rem] text-left">
              <GlobeIcon className="h-6 w-6 text-white/90" />
              <div className="text-4xl font-heading italic tracking-[-1px] leading-none mt-4">
                20+
              </div>
              <div className="mt-2 text-xs text-white/80 font-body font-light">
                内置工具系统，开箱即用
              </div>
            </div>
          </motion.div>
        </div>

        {/* Bottom trust bar */}
        <motion.div {...fadeIn(1.4)} className="flex flex-col items-center gap-4 pb-8">
          <div className="liquid-glass rounded-full px-4 py-1.5 text-xs text-white/80 font-body">
            深受效率玩家与 AI 爱好者喜爱
          </div>
          <div className="flex items-center gap-12 md:gap-16">
            {stackNames.map((name) => (
              <span
                key={name}
                className="font-heading italic text-2xl md:text-3xl tracking-tight"
              >
                {name}
              </span>
            ))}
          </div>
        </motion.div>
      </div>
    </section>
  )
}
