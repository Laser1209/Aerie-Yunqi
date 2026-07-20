import FeatureMatrix from '../components/FeatureMatrix'
import PageIntro from '../components/PageIntro'
import PageShell from '../components/PageShell'
import { publicPath } from '../config/publicPath'
import { productFeatures } from '../content/spotlight'

export default function FeaturesPage() {
  return (
    <PageShell videoSrc={publicPath('videos/features.mp4')} accent="#7cebd1" fallbackColor="#030b0b" scrollable>
      <div className="min-h-screen overflow-x-hidden px-5 pb-16 pt-28 sm:px-6 md:px-12 lg:px-20 lg:pb-24">
        <header className="grid gap-7 lg:grid-cols-[minmax(0,1fr)_360px] lg:items-end">
          <PageIntro
            label="Features"
            title="Aerie, in the flow"
            description="让 AI 留在桌面工作流里。Aerie 把对话、行动、陪伴与恢复能力收进一个本地优先的 Windows 桌面体验。"
          />
          <p className="max-w-sm text-sm font-light leading-relaxed text-white/60 lg:pb-1">
            Not another tab to manage. 从灵动岛到 Office Mode，每项能力都围绕同一个目标：需要时出现，完成后退回背景。
          </p>
        </header>

        <section className="mt-14 md:mt-20" aria-labelledby="feature-matrix-heading">
          <div className="mb-7 flex flex-col gap-2 border-b border-white/10 pb-5 sm:flex-row sm:items-end sm:justify-between">
            <h2 id="feature-matrix-heading" className="font-heading text-3xl italic leading-none md:text-4xl">Six systems, one presence.</h2>
            <p className="text-xs font-light text-white/45">Capability matrix / 能力矩阵</p>
          </div>
          <FeatureMatrix features={productFeatures} />
        </section>
      </div>
    </PageShell>
  )
}
