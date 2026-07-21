import { motion, useReducedMotion } from 'framer-motion'
import type { ProductTrack } from '../content/spotlight'

interface RoadmapTracksProps {
  tracks: ProductTrack[]
}

export default function RoadmapTracks({ tracks }: RoadmapTracksProps) {
  const reduceMotion = useReducedMotion()

  return (
    <section aria-labelledby="product-tracks-title">
      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-xs text-emerald-50/65">Product tracks / 产品化路线</p>
          <h2 id="product-tracks-title" className="mt-2 font-heading text-4xl italic leading-none md:text-5xl">Three paths, one local-first core.</h2>
        </div>
        <p className="max-w-sm text-xs font-light leading-relaxed text-white/50">三条路线已进入公开主线并通过阶段测试；feature flag 决定实际启用范围，不等同于 beta.1 安装包内容。</p>
      </div>
      <div className="mt-8 grid grid-cols-1 gap-4 lg:grid-cols-3">
        {tracks.map((track, index) => (
          <motion.article
            key={track.number}
            initial={reduceMotion ? false : { opacity: 0, y: 20 }}
            whileInView={reduceMotion ? undefined : { opacity: 1, y: 0 }}
            viewport={{ once: true, amount: 0.25 }}
            transition={{ duration: 0.5, delay: reduceMotion ? 0 : index * 0.08 }}
            className="liquid-glass min-h-[245px] rounded-[1rem] p-6"
          >
            <div className="flex items-center justify-between text-[10px] uppercase text-white/40">
              <span>{track.number}</span>
              <span>{track.phases}</span>
            </div>
            <div className="mt-14">
              <h3 className="font-heading text-3xl italic leading-none">{track.title}</h3>
              <p className="mt-2 text-xs text-white/55">{track.titleZh}</p>
              <p className="mt-4 text-sm font-light leading-relaxed text-white/70">{track.description}</p>
            </div>
          </motion.article>
        ))}
      </div>
    </section>
  )
}
