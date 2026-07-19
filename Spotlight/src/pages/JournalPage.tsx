import PageShell from '../components/PageShell'
import PageIntro from '../components/PageIntro'

const entries = [
  { version: '0.1.0-beta.1', date: '2026-07-19', type: 'Internal Beta Baseline', title: '内测基准版本', body: '重置版本号并确立内测阶段第一个稳定基线，后续按 beta 规范渐进收敛。' },
  { version: '13.9.8', date: '2026-07-19', type: 'Final v13.9 Release', title: '综合修复方案', body: '完成 v13.9 收尾审查，识别运行时崩溃、静默失效与技术债务。' },
  { version: '13.9.4', date: '2026-07-19', type: 'Office Enhancement', title: '办公模式增强', body: '办公文件目录可配置，并统一 QQ 客户端 RPC 调用与登录状态判断。' },
  { version: '13.9.3', date: '2026-07-19', type: 'Desktop Iteration', title: '桌面交互迭代', body: '完善灵动岛媒体能力、办公菜单无障碍与 SMTC 中文编码处理。' },
]

export default function JournalPage() {
  return (
    <PageShell videoSrc="/videos/journal.mp4" scrollable>
      <div className="min-h-screen px-6 pb-10 pt-28 md:px-16 lg:px-20">
        <PageIntro label="Journal" title={'Built in public,\nrefined in private'} />
        <div className="mt-10 grid grid-cols-1 gap-4 lg:grid-cols-2">
          {entries.map((entry, index) => (
            <article
              key={entry.version}
              className={`liquid-glass flex flex-col rounded-[1.25rem] p-6 ${index === 0 ? 'min-h-[300px] lg:row-span-2' : 'min-h-[150px]'}`}
            >
              <div className="flex items-center justify-between text-[11px] text-white/55">
                <span>{entry.type}</span>
                <time>{entry.date}</time>
              </div>
              <div className="mt-auto pt-8">
                <p className="font-heading text-2xl italic text-white/60">v{entry.version}</p>
                <h2 className="mt-1 font-heading text-3xl italic leading-none md:text-4xl">{entry.title}</h2>
                <p className="mt-3 max-w-xl text-sm font-light leading-snug text-white/80">{entry.body}</p>
              </div>
            </article>
          ))}
        </div>
      </div>
    </PageShell>
  )
}
