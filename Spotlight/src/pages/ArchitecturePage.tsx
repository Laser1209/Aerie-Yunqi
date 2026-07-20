import ArchitectureStack from '../components/ArchitectureStack'
import PageIntro from '../components/PageIntro'
import PageShell from '../components/PageShell'
import RoadmapRail from '../components/RoadmapRail'
import { publicPath } from '../config/publicPath'
import { architectureLayers, architectureRoadmap } from '../content/spotlight'

export default function ArchitecturePage() {
  return (
    <PageShell videoSrc={publicPath('videos/architecture.mp4')} accent="#8ecbff" fallbackColor="#050912" scrollable>
      <div className="min-h-screen overflow-x-hidden px-5 pb-16 pt-28 sm:px-6 md:px-12 lg:px-20 lg:pb-24">
        <PageIntro
          label="Architecture"
          title="From message to memory"
          description="一条消息从桌面进入本地内核，经过 Provider、工具、情感与记忆，再通过安全边界抵达行动。每一层都有清晰所有权。"
        />

        <div className="mt-14 grid min-w-0 grid-cols-1 gap-10 lg:mt-20 lg:grid-cols-[minmax(0,1fr)_minmax(300px,0.42fr)] lg:items-start">
          <section aria-labelledby="architecture-layers-heading">
            <div className="mb-7 border-b border-white/10 pb-5">
              <p className="text-xs text-sky-50/70">Runtime layers / 运行时分层</p>
              <h2 id="architecture-layers-heading" className="mt-2 font-heading text-3xl italic leading-none md:text-4xl">Local by default. Explicit by design.</h2>
            </div>
            <ArchitectureStack layers={architectureLayers} />
          </section>
          <RoadmapRail milestones={architectureRoadmap} />
        </div>
      </div>
    </PageShell>
  )
}
