import { motion, useReducedMotion } from 'framer-motion'
import { Link } from 'react-router-dom'
import PageIntro from '../components/PageIntro'
import PageShell from '../components/PageShell'
import { ArrowUpRight } from '../components/icons'
import { publicPath } from '../config/publicPath'
import { downloadRequirements, localDataNotes } from '../content/spotlight'
import { release } from '../config/release'

export default function DownloadPage() {
  const reduceMotion = useReducedMotion()

  return (
    <PageShell videoSrc={publicPath('videos/download.mp4')} accent="#d7eeff" fallbackColor="#080b10" scrollable>
      <div className="flex min-h-screen flex-col overflow-x-hidden px-5 pb-16 pt-28 sm:px-6 md:px-12 lg:px-20 lg:pb-24">
        <PageIntro
          label="Download"
          title="Take Aerie with you"
          description="Aerie · 云栖当前以 Windows 内测版本提供。下载到本机，连接你选择的模型 Provider；QQ 能力按需配置 NapCat。"
        />

        <div className="mt-14 grid min-w-0 grid-cols-1 gap-5 lg:mt-20 lg:grid-cols-[minmax(0,1.25fr)_minmax(310px,0.75fr)]">
          <motion.article
            initial={reduceMotion ? false : { opacity: 0, y: 24, filter: 'blur(8px)' }}
            animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
            transition={{ duration: reduceMotion ? 0 : 0.7, ease: [0.22, 1, 0.36, 1] }}
            className="liquid-glass flex min-h-[430px] flex-col rounded-[1.1rem] p-6 md:p-9"
          >
            <div className="flex flex-wrap items-start justify-between gap-5">
              <span className="flex h-12 w-12 items-center justify-center rounded-xl border border-white/10 bg-black/20 text-sky-50">
                <img src={publicPath('aerie-mark-mono.svg')} alt="" className="h-7 w-7 object-contain" aria-hidden="true" />
              </span>
              <div className="text-right">
                <p className="text-[10px] uppercase text-white/45">Current release</p>
                <p className="mt-1 text-xs text-white/70">{release.date}</p>
              </div>
            </div>

            <div className="mt-auto pt-14">
              <p className="text-xs text-sky-50/70">Windows beta / Windows 内测版</p>
              <h2 className="mt-3 font-heading text-4xl italic leading-none md:text-6xl">Aerie · 云栖 {release.version}</h2>
              <p className="mt-5 max-w-xl text-sm font-light leading-relaxed text-white/70">
                便携版适合直接放进自己的工作目录；Windows Setup 则提供标准安装流程。两种真实构建共享同一 beta 基线。
              </p>
              <div className="mt-8 flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
                <a
                  href={release.url}
                  download={release.filename}
                  className="flex w-full items-center justify-center gap-2 rounded-full bg-white px-5 py-3 text-sm font-medium text-black transition-colors hover:bg-sky-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-2 focus-visible:ring-offset-black sm:w-auto"
                >
                  Portable edition
                  <ArrowUpRight className="h-4 w-4" aria-hidden="true" />
                </a>
                <a
                  href={release.installerUrl}
                  download={release.installerFilename}
                  className="liquid-glass flex w-full items-center justify-center gap-2 rounded-full px-5 py-3 text-sm font-medium text-white transition-colors hover:bg-white/[0.05] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/70 sm:w-auto"
                >
                  Windows Setup
                  <ArrowUpRight className="h-4 w-4" aria-hidden="true" />
                </a>
                <Link to="/" className="text-center text-sm text-white/60 transition-colors hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/60 sm:text-left">
                  返回首页 / Back home
                </Link>
              </div>
            </div>
          </motion.article>

          <aside className="liquid-glass rounded-[1.1rem] p-6 md:p-7" aria-labelledby="requirements-title">
            <p className="text-xs text-sky-50/70">Before you begin / 运行须知</p>
            <h2 id="requirements-title" className="mt-2 font-heading text-3xl italic leading-none">Small setup, clear boundaries.</h2>
            <dl className="mt-7 divide-y divide-white/10">
              {downloadRequirements.map((requirement) => (
                <div key={requirement.label} className="grid grid-cols-[72px_minmax(0,1fr)] gap-4 py-4 first:pt-0">
                  <dt className="text-[10px] uppercase text-white/40">{requirement.label}</dt>
                  <dd>
                    <p className="text-sm font-medium text-white/85">{requirement.value}</p>
                    <p className="mt-1 text-xs font-light leading-relaxed text-white/50">{requirement.note}</p>
                  </dd>
                </div>
              ))}
            </dl>
          </aside>
        </div>

        <section className="mt-5 grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,0.75fr)_minmax(0,1.25fr)]" aria-labelledby="local-data-title">
          <div className="liquid-glass rounded-[1.1rem] p-6 md:p-7">
            <p className="text-xs text-white/50">Delivery / 交付方式</p>
            <h2 className="mt-3 font-heading text-3xl italic leading-none">Setup now. Portable by design.</h2>
            <p className="mt-4 text-sm font-light leading-relaxed text-white/65">
              Portable 与 Windows Setup 均为当前 beta 的本地构建，不引入额外账户或发行渠道。
            </p>
          </div>
          <div className="liquid-glass rounded-[1.1rem] p-6 md:p-7">
            <p className="text-xs text-sky-50/70">Local-first data / 本地数据策略</p>
            <h2 id="local-data-title" className="mt-3 font-heading text-3xl italic leading-none">Your device remains the home base.</h2>
            <ul className="mt-6 space-y-4">
              {localDataNotes.map((note) => (
                <li key={note} className="grid grid-cols-[18px_minmax(0,1fr)] gap-3 text-sm font-light leading-relaxed text-white/70">
                  <span className="mt-[0.45rem] h-px w-3 bg-sky-100/70" aria-hidden="true" />
                  <span>{note}</span>
                </li>
              ))}
            </ul>
          </div>
        </section>
      </div>
    </PageShell>
  )
}
