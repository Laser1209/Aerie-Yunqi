import JournalTimeline from '../components/JournalTimeline'
import PageIntro from '../components/PageIntro'
import PageShell from '../components/PageShell'
import RoadmapTracks from '../components/RoadmapTracks'
import { publicPath } from '../config/publicPath'
import { journalEntries, productTracks } from '../content/spotlight'

export default function JournalPage() {
  return (
    <PageShell videoSrc={publicPath('videos/journal.mp4')} accent="#b8f5d4" fallbackColor="#080d0c" scrollable>
      <div className="min-h-screen overflow-x-hidden px-5 pb-16 pt-28 sm:px-6 md:px-12 lg:px-20 lg:pb-24">
        <header className="grid gap-7 lg:grid-cols-[minmax(0,1fr)_360px] lg:items-end">
          <PageIntro
            label="Journal"
            title="What shipped. What's next."
            description="从发布包到公开主线，这里分别记录已经交付的版本与通过阶段测试、仍受 feature flag 控制的源码能力。"
          />
          <p className="max-w-sm text-sm font-light leading-relaxed text-white/55 lg:pb-1">
            Release facts come from GitHub Release and CHANGELOG. 主线能力来自阶段状态与验收证据，不与 beta.1 下载包混写。
          </p>
        </header>

        <div className="liquid-glass mt-14 rounded-[1.1rem] p-5 md:mt-20 md:p-8 lg:p-10">
          <JournalTimeline entries={journalEntries} />
        </div>

        <div className="mt-20 md:mt-28">
          <RoadmapTracks tracks={productTracks} />
        </div>
      </div>
    </PageShell>
  )
}
