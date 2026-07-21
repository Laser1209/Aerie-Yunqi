import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { useState } from 'react'
import type { JournalEntryData, JournalStatus } from '../content/spotlight'
import StatusBadge from './StatusBadge'

const filters: Array<{ value: JournalStatus; label: string; labelZh: string }> = [
  { value: 'shipped', label: 'Shipped', labelZh: '已发布' },
  { value: 'mainline', label: 'Mainline', labelZh: '公开主线' },
  { value: 'building', label: 'Building', labelZh: '建设中' },
  { value: 'planned', label: 'Planned', labelZh: '计划中' },
]

interface JournalTimelineProps {
  entries: JournalEntryData[]
}

export default function JournalTimeline({ entries }: JournalTimelineProps) {
  const [activeStatus, setActiveStatus] = useState<JournalStatus>('shipped')
  const reduceMotion = useReducedMotion()
  const availableFilters = filters.filter((filter) => entries.some((entry) => entry.status === filter.value))
  const visibleEntries = entries.filter((entry) => entry.status === activeStatus)

  return (
    <section aria-labelledby="journal-timeline-title">
      <div className="flex flex-col gap-5 border-b border-white/10 pb-6 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-xs text-emerald-50/70">Release notes / 产品进程</p>
          <h2 id="journal-timeline-title" className="mt-2 font-heading text-3xl italic leading-none md:text-4xl">A living record</h2>
        </div>
        <div className="liquid-glass grid w-full grid-flow-col auto-cols-fr rounded-full p-1 md:w-auto" role="group" aria-label="Filter journal entries">
          {availableFilters.map((filter) => {
            const isActive = filter.value === activeStatus
            return (
              <button
                key={filter.value}
                type="button"
                aria-pressed={isActive}
                onClick={() => setActiveStatus(filter.value)}
                className={`min-w-0 rounded-full px-3 py-2 text-center text-[11px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-100/60 md:min-w-[104px] ${isActive ? 'bg-white text-black' : 'text-white/60 hover:text-white'}`}
              >
                <span className="block truncate">{filter.label}</span>
                <span className={`mt-0.5 block truncate text-[9px] ${isActive ? 'text-black/55' : 'text-white/35'}`}>{filter.labelZh}</span>
              </button>
            )
          })}
        </div>
      </div>

      <div className="mt-2 min-h-[250px]" aria-live="polite">
        <AnimatePresence mode="wait" initial={false}>
          <motion.ol
            key={activeStatus}
            initial={reduceMotion ? false : { opacity: 0, y: 12, filter: 'blur(6px)' }}
            animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
            exit={reduceMotion ? undefined : { opacity: 0, y: -8, filter: 'blur(4px)' }}
            transition={{ duration: reduceMotion ? 0 : 0.35, ease: [0.22, 1, 0.36, 1] }}
            className="divide-y divide-white/10"
          >
            {visibleEntries.map((entry) => (
              <li key={entry.id}>
                <article className="grid gap-5 py-7 md:grid-cols-[150px_minmax(0,1fr)] md:gap-8">
                  <div>
                    <StatusBadge status={entry.status} />
                    <p className="mt-3 font-heading text-2xl italic leading-none text-white/75">{entry.version}</p>
                    <time className="mt-2 block text-[10px] text-white/40">{entry.date}</time>
                  </div>
                  <div>
                    <p className="text-[10px] uppercase text-white/40">{entry.category}</p>
                    <h3 className="mt-2 max-w-3xl font-heading text-3xl italic leading-[0.98] text-white md:text-4xl">{entry.title}</h3>
                    <p className="mt-2 text-xs text-white/60">{entry.titleZh}</p>
                    <p className="mt-4 max-w-2xl text-sm font-light leading-relaxed text-white/70">{entry.summary}</p>
                    <ul className="mt-4 flex flex-wrap gap-x-4 gap-y-1 text-[10px] uppercase text-emerald-50/50" aria-label="Highlights">
                      {entry.highlights.map((highlight) => <li key={highlight}>{highlight}</li>)}
                    </ul>
                  </div>
                </article>
              </li>
            ))}
          </motion.ol>
        </AnimatePresence>
      </div>
    </section>
  )
}
