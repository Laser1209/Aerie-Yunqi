import { motion, useReducedMotion } from 'framer-motion'
import type { ArchitectureLayerData } from '../content/spotlight'

interface ArchitectureStackProps {
  layers: ArchitectureLayerData[]
}

export default function ArchitectureStack({ layers }: ArchitectureStackProps) {
  const reduceMotion = useReducedMotion()

  return (
    <ol className="space-y-3" aria-label="Aerie architecture layers">
      {layers.map((layer, index) => (
        <motion.li
          key={layer.number}
          initial={reduceMotion ? false : { opacity: 0, x: -24, filter: 'blur(8px)' }}
          whileInView={reduceMotion ? undefined : { opacity: 1, x: 0, filter: 'blur(0px)' }}
          viewport={{ once: true, amount: 0.2 }}
          transition={{ duration: 0.55, delay: reduceMotion ? 0 : index * 0.08, ease: [0.22, 1, 0.36, 1] }}
          className="relative pl-8 before:absolute before:bottom-[-0.75rem] before:left-[0.72rem] before:top-6 before:w-px before:bg-white/10 last:before:hidden md:pl-11"
        >
          <span className="absolute left-0 top-6 flex h-6 w-6 items-center justify-center rounded-full border border-sky-100/30 bg-black/45 text-[9px] text-sky-50 md:h-7 md:w-7">
            {layer.number}
          </span>
          <article className="liquid-glass rounded-[1rem] px-5 py-5 transition-colors duration-300 hover:bg-white/[0.03] md:px-6">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <p className="text-[11px] font-light text-white/50">{layer.titleZh}</p>
                <h2 className="mt-1 font-heading text-2xl italic leading-tight text-white md:text-3xl">{layer.title}</h2>
                <p className="mt-3 max-w-2xl text-sm font-light leading-relaxed text-white/70">{layer.description}</p>
              </div>
              <ul className="flex max-w-sm flex-wrap gap-x-3 gap-y-1 text-[10px] uppercase text-white/40 lg:max-w-[180px] lg:justify-end lg:text-right" aria-label="Layer technologies">
                {layer.signals.map((signal) => <li key={signal}>{signal}</li>)}
              </ul>
            </div>
          </article>
        </motion.li>
      ))}
    </ol>
  )
}
