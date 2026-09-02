import { motion, useReducedMotion } from 'framer-motion'
import { Link } from 'react-router-dom'
import PageIntro from '../components/PageIntro'
import PageShell from '../components/PageShell'
import { ArrowUpRight } from '../components/icons'
import { publicPath } from '../config/publicPath'

interface Milestone {
  code: string
  done: boolean
  title: string
  note: string
}

const foundation: Milestone[] = [
  {
    code: 'T1.1',
    done: true,
    title: '工程骨架',
    note: 'Flutter 双端工程、依赖锁定、平台安全配置、日志轮转与落位。',
  },
  {
    code: 'T1.2',
    done: true,
    title: '网络层',
    note: 'openapi 生成客户端、鉴权拦截器、Api 错误映射。',
  },
  {
    code: 'T1.3',
    done: true,
    title: '本地存储',
    note: 'drift 消息库、安全令牌存储、文件续传点。',
  },
  {
    code: 'T1.4',
    done: true,
    title: '认证闭环',
    note: '登录状态机 + AuthScreen，S1 门禁 PASS。',
  },
  {
    code: 'T2.1',
    done: true,
    title: '聊天核心',
    note: '分页 / 发送 / 取消 / 重试 + 本地化气泡渲染。',
  },
  {
    code: 'T2.2',
    done: true,
    title: 'SSE 状态机',
    note: '实时增量、Last-Event-ID 续传、去重、退避重连。',
  },
  {
    code: 'T2.3',
    done: true,
    title: '文件双向传输',
    note: 'SHA-256 分块上传、Range 下载、断点续传。',
  },
  {
    code: 'T2.4',
    done: true,
    title: '附件打通 + 集成',
    note: 'fileIds 填入请求、图片懒加载，S2 门禁 PASS。',
  },
  {
    code: 'T3.1',
    done: true,
    title: '多端会话',
    note: '移动网关多端会话、账号鉴权与消息顺序保序。',
  },
  {
    code: 'T3.2',
    done: true,
    title: '跨端时间线',
    note: '跨端时间线（视图 B）与多端存在提示，跨设备回忆一致。',
  },
  {
    code: 'T3.3',
    done: true,
    title: '文件双向传输增强',
    note: 'SHA-256 分块上传、Range 下载、断点续传全链路。',
  },
]

const forward: Milestone[] = [
  { code: 'P-S3', done: false, title: '只读能力屏', note: '简报 / 世界 / 记忆 / 天气四屏。' },
  { code: 'P-S4', done: false, title: '真机验收', note: 'Android + iOS 双端登录、消息、文件闭环。' },
  { code: 'P-S5', done: false, title: 'Tunnel', note: 'Cloudflare Tunnel 独立服务。' },
  { code: 'P-S6', done: false, title: '签名发布', note: '双端签名包、性能门槛。' },
  { code: 'P-S7', done: false, title: '收口', note: '主控文档与验收收口。' },
]

const boundaries = [
  '纯接收端：接收来自电脑一侧的推送与同步，不做智能推理。',
  '与电脑一对一配对后开始传输数据，链路清晰、可及时切换账号。',
  '历史消息以缓存形式保留 7 天，服务端为唯一真相源。',
  '本地数据本地存，不随云同步上传。',
]

export default function MobilePage() {
  const reduceMotion = useReducedMotion()
  const fade = reduceMotion
    ? {}
    : { initial: { opacity: 0, y: 22, filter: 'blur(6px)' }, whileInView: { opacity: 1, y: 0, filter: 'blur(0px)' }, viewport: { once: true, amount: 0.4 } }

  return (
    <PageShell videoSrc={publicPath('videos/features.mp4')} accent="#b8f5d4" fallbackColor="#04070a" scrollable>
      <div className="min-h-screen overflow-x-hidden px-5 pb-16 pt-28 sm:px-6 md:px-12 lg:px-20 lg:pb-24">
        <header className="grid gap-7 lg:grid-cols-[minmax(0,1fr)_340px] lg:items-end">
          <PageIntro
            label="Mobile · Android"
            title={'A companion,\nin your pocket.'}
            description={'Aerie Companion 的移动端接收端。用 Flutter 双端重写，与桌面端经安全网关一对一配对，把对话、文件与跨端时间线同步放进手机。基础架构与多端会话已落地，只读能力屏与真机验收持续推进中。'}
          />
          <motion.p
            {...fade}
            className="max-w-sm text-sm font-light leading-relaxed text-white/60 lg:pb-1"
          >
            A pure receiver for now. 纯接收端、可及时切换账号，不承载推理。手机负责贴身与提醒，电脑负责思考与行动。
          </motion.p>
        </header>

        <section className="mt-14 md:mt-20" aria-labelledby="android-status">
          <div className="mb-7 flex flex-col gap-2 border-b border-white/10 pb-5 sm:flex-row sm:items-end sm:justify-between">
            <h2 id="android-status" className="font-heading text-3xl italic leading-none md:text-4xl">The mobile companion is taking shape.</h2>
            <p className="text-xs font-light text-white/45">Status / 当前进度</p>
          </div>

          <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            <motion.div
              {...fade}
              className="liquid-glass flex min-h-[240px] flex-col rounded-[1.1rem] p-6 md:p-8"
            >
              <p className="text-xs text-white/50">Baseline / 基础里程碑</p>
              <div className="mt-6 flex flex-wrap items-center gap-4">
                <span className="inline-flex items-center gap-2 rounded-full bg-white/10 px-3 py-1 text-sm font-medium text-white">
                  P-S1 <span className="text-emerald-300">PASS</span>
                </span>
                <span className="inline-flex items-center gap-2 rounded-full bg-white/10 px-3 py-1 text-sm font-medium text-white">
                  P-S2 <span className="text-emerald-300">PASS</span>
                </span>
                <span className="inline-flex items-center gap-2 rounded-full border border-white/15 px-3 py-1 text-sm font-medium text-white/60">
                  P-S3 … P-S7 <span className="text-white/40">—</span>
                </span>
              </div>
              <p className="mt-auto pt-6 text-sm font-light leading-relaxed text-white/70">
                历经认证闭环与消息 / SSE / 文件双向基础，S1、S2 门禁均已 PASS：
                <span className="text-white">flutter analyze 零告警 · 测试全绿 · 覆盖率达标</span>。
              </p>
            </motion.div>

            <motion.div {...fade} className="liquid-glass rounded-[1.1rem] p-6 md:p-8">
              <p className="text-xs text-sky-50/70">Boundaries / 设计边界</p>
              <h3 className="mt-3 font-heading text-2xl italic leading-none">Small receiver, clear contract.</h3>
              <ul className="mt-6 space-y-4">
                {boundaries.map((note) => (
                  <li key={note} className="grid grid-cols-[18px_minmax(0,1fr)] gap-3 text-sm font-light leading-relaxed text-white/70">
                    <span className="mt-[0.5rem] h-px w-3 bg-emerald-200/70" aria-hidden="true" />
                    <span>{note}</span>
                  </li>
                ))}
              </ul>
            </motion.div>
          </div>
        </section>

        <section className="mt-14 md:mt-20" aria-labelledby="milestones-title">
          <div className="mb-7 flex flex-col gap-2 border-b border-white/10 pb-5 sm:flex-row sm:items-end sm:justify-between">
            <h2 id="milestones-title" className="font-heading text-3xl italic leading-none md:text-4xl">What already landed.</h2>
            <p className="text-xs font-light text-white/45">Shipped milestones / 已落地节点</p>
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {foundation.map((m, index) => (
              <motion.div
                key={`${m.code}-${index}`}
                {...fade}
                className="liquid-glass rounded-[1.1rem] p-5"
              >
                <div className="flex items-center justify-between">
                  <span className="text-[10px] uppercase text-white/40">{m.code}</span>
                  <span className="text-emerald-300">{'\u2713'}</span>
                </div>
                <h3 className="mt-4 font-heading text-xl italic leading-none">{m.title}</h3>
                <p className="mt-3 text-sm font-light leading-relaxed text-white/60">{m.note}</p>
              </motion.div>
            ))}
          </div>
        </section>

        <section className="mt-14 md:mt-20" aria-labelledby="upnext-title">
          <div className="mb-7 flex flex-col gap-2 border-b border-white/10 pb-5 sm:flex-row sm:items-end sm:justify-between">
            <h2 id="upnext-title" className="font-heading text-3xl italic leading-none md:text-4xl">What's next.</h2>
            <p className="text-xs font-light text-white/45">Roadmap / 下一步</p>
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {forward.map((m) => (
              <div key={m.code} className="liquid-glass rounded-[1.1rem] p-5 opacity-80">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] uppercase text-white/40">{m.code}</span>
                  <span className="h-2 w-2 rounded-full bg-white/30" />
                </div>
                <h3 className="mt-4 font-heading text-xl italic leading-none text-white/70">{m.title}</h3>
                <p className="mt-3 text-sm font-light leading-relaxed text-white/45">{m.note}</p>
              </div>
            ))}
          </div>
        </section>

        <motion.div
          {...fade}
          className="mt-14 flex flex-col items-start gap-5 rounded-[1.1rem] p-7 md:mt-16 md:flex-row md:items-center md:justify-between md:p-9"
        >
          <div>
            <p className="text-xs text-white/50">Stay in the loop / 随时回来看看</p>
            <p className="mt-2 max-w-2xl text-sm font-light leading-relaxed text-white/70">
              当前版本的 Android 接收端处于基础里程碑阶段；后续只读屏、真机验收、签名发布将在官网 Journal 与移动端页面持续更新。
            </p>
          </div>
          <Link
            to="/journal"
            className="flex w-full items-center justify-center gap-2 rounded-full bg-white px-5 py-3 text-sm font-medium text-black transition-colors hover:bg-sky-50 md:w-auto"
          >
            View the journal
            <ArrowUpRight className="h-4 w-4" aria-hidden="true" />
          </Link>
        </motion.div>
      </div>
    </PageShell>
  )
}
