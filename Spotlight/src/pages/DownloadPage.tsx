import { Link } from 'react-router-dom'
import PageShell from '../components/PageShell'
import PageIntro from '../components/PageIntro'
import { ArrowUpRight, DocumentIcon } from '../components/icons'
import { release } from '../config/release'

const requirements = ['Windows 11', '约 350 MB 磁盘空间', '至少一个模型 API Key', 'QQ 功能需配置 NapCat']

export default function DownloadPage() {
  return (
    <PageShell videoSrc="/videos/download.mp4" scrollable>
      <div className="flex min-h-screen flex-col px-6 pb-10 pt-28 md:px-16 lg:px-20">
        <PageIntro label="Download" title={'Bring Aerie\nhome'} />
        <div className="mt-10 grid gap-5 lg:mt-auto lg:grid-cols-[1.35fr_.65fr]">
          <article className="liquid-glass flex min-h-[330px] flex-col rounded-[1.25rem] p-6 md:p-8">
            <div className="flex items-start justify-between">
              <div className="liquid-glass flex h-12 w-12 items-center justify-center rounded-xl">
                <DocumentIcon className="h-6 w-6" />
              </div>
              <span className="liquid-glass rounded-full px-3 py-1 text-[11px] text-white/75">Windows Setup</span>
            </div>
            <div className="mt-auto pt-10">
              <p className="text-xs text-white/60">CURRENT RELEASE · {release.date}</p>
              <h2 className="mt-2 font-heading text-4xl italic leading-none md:text-5xl">Aerie · 云栖 {release.version}</h2>
              <p className="mt-3 text-sm font-light text-white/75">本地优先的 Windows 11 AI 桌面伴侣安装版。</p>
              <div className="mt-6 flex flex-wrap items-center gap-4">
                <a href={release.url} download={release.filename} className="flex items-center gap-2 rounded-full bg-white px-5 py-2.5 text-sm font-medium text-black">
                  下载 Windows 安装版
                  <ArrowUpRight className="h-4 w-4" />
                </a>
                <Link to="/" className="text-sm text-white/75 hover:text-white">返回首页</Link>
              </div>
            </div>
          </article>
          <aside className="liquid-glass rounded-[1.25rem] p-6">
            <p className="text-xs uppercase tracking-[0.14em] text-white/55">Before you begin</p>
            <h2 className="mt-3 font-heading text-3xl italic">运行须知</h2>
            <ul className="mt-6 space-y-4">
              {requirements.map((item) => (
                <li key={item} className="flex items-center gap-3 text-sm font-light text-white/80">
                  <span className="h-1.5 w-1.5 rounded-full bg-white" />{item}
                </li>
              ))}
            </ul>
            <p className="mt-8 text-xs font-light leading-relaxed text-white/55">首次运行可能请求管理员权限，用于自启动与任务计划。你的模型密钥保存在本地配置中。</p>
          </aside>
        </div>
      </div>
    </PageShell>
  )
}
