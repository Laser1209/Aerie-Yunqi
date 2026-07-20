import type { RoadmapMilestone } from '../content/spotlight'
import StatusBadge from './StatusBadge'

interface RoadmapRailProps {
  milestones: RoadmapMilestone[]
}

export default function RoadmapRail({ milestones }: RoadmapRailProps) {
  const current = milestones.filter((milestone) => milestone.status === 'shipped' || milestone.status === 'building')
  const next = milestones.filter((milestone) => milestone.status === 'planned' || milestone.status === 'gated')

  const renderMilestones = (items: RoadmapMilestone[]) => (
    <ol className="divide-y divide-white/10">
      {items.map((milestone) => (
        <li key={milestone.phase} className="py-5 first:pt-0 last:pb-0">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-[10px] uppercase text-white/45">{milestone.phase}</p>
            <StatusBadge status={milestone.status} />
          </div>
          <h3 className="mt-3 font-heading text-2xl italic leading-none text-white">{milestone.title}</h3>
          <p className="mt-1 text-xs text-white/55">{milestone.titleZh}</p>
          <p className="mt-3 text-xs font-light leading-relaxed text-white/65">{milestone.description}</p>
        </li>
      ))}
    </ol>
  )

  return (
    <aside className="liquid-glass h-fit rounded-[1.1rem] p-6 md:p-7" aria-label="Product roadmap">
      <section>
        <h2 className="mb-5 text-xs font-medium uppercase text-cyan-50/80">Now / 已抵达与正在建设</h2>
        {renderMilestones(current)}
      </section>
      <section className="mt-8 border-t border-white/10 pt-7">
        <h2 className="mb-5 text-xs font-medium uppercase text-white/60">Next / 下一段路线</h2>
        {renderMilestones(next)}
      </section>
    </aside>
  )
}
