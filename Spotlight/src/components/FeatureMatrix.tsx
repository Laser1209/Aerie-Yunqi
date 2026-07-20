import { motion, useReducedMotion } from 'framer-motion'
import type { SVGProps } from 'react'
import type { FeatureIconName, FeatureTone, ProductFeature } from '../content/spotlight'
import { ClockIcon, ControlIcon, GlobeIcon, LightbulbIcon } from './icons'

type IconComponent = (props: SVGProps<SVGSVGElement>) => JSX.Element

function DesktopIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <rect x="3" y="4" width="18" height="13" rx="2" />
      <path d="M8 21h8M12 17v4M7 8h10" />
    </svg>
  )
}

function OfficeIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <rect x="3" y="7" width="18" height="13" rx="2" />
      <path d="M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2M3 12h18M10 12v2h4v-2" />
    </svg>
  )
}

const featureIcons: Record<FeatureIconName, IconComponent> = {
  desktop: DesktopIcon,
  office: OfficeIcon,
  tools: GlobeIcon,
  proactive: ClockIcon,
  persona: LightbulbIcon,
  safety: ControlIcon,
}

const toneClassNames: Record<FeatureTone, { icon: string; line: string }> = {
  aqua: { icon: 'text-emerald-100', line: 'bg-emerald-200/70' },
  cyan: { icon: 'text-cyan-100', line: 'bg-cyan-200/70' },
  ice: { icon: 'text-sky-100', line: 'bg-sky-200/70' },
}

interface FeatureMatrixProps {
  features: ProductFeature[]
}

export default function FeatureMatrix({ features }: FeatureMatrixProps) {
  const reduceMotion = useReducedMotion()

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
      {features.map((feature, index) => {
        const Icon = featureIcons[feature.icon]
        const tone = toneClassNames[feature.tone]

        return (
          <motion.article
            key={feature.id}
            tabIndex={0}
            aria-labelledby={`${feature.id}-title`}
            initial={reduceMotion ? false : { opacity: 0, y: 28, filter: 'blur(10px)' }}
            whileInView={reduceMotion ? undefined : { opacity: 1, y: 0, filter: 'blur(0px)' }}
            whileHover={reduceMotion ? undefined : { y: -5 }}
            viewport={{ once: true, amount: 0.16 }}
            transition={{ duration: 0.65, delay: reduceMotion ? 0 : index * 0.07, ease: [0.22, 1, 0.36, 1] }}
            className="liquid-glass group relative flex min-h-[360px] flex-col rounded-[1.1rem] p-6 outline-none transition-colors duration-300 hover:bg-white/[0.035] focus-visible:bg-white/[0.045] focus-visible:ring-2 focus-visible:ring-cyan-100/50"
          >
            <div className={`absolute inset-x-10 top-0 h-px ${tone.line} opacity-40 transition-opacity group-hover:opacity-90 group-focus-visible:opacity-90`} />
            <div className="flex items-start justify-between gap-5">
              <span className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-white/10 bg-black/20 ${tone.icon}`}>
                <Icon className="h-5 w-5" aria-hidden="true" />
              </span>
              <span className="font-heading text-2xl italic text-white/35">0{index + 1}</span>
            </div>

            <div className="mt-auto pt-10">
              <p className="text-xs font-light text-white/55">{feature.titleZh}</p>
              <h2 id={`${feature.id}-title`} className="mt-2 font-heading text-3xl italic leading-none text-white md:text-4xl">
                {feature.title}
              </h2>
              <p className="mt-4 max-w-[36ch] text-sm font-light leading-relaxed text-white/75">{feature.description}</p>
              <ul className="mt-5 flex flex-wrap gap-x-3 gap-y-1.5 text-[11px] text-white/50" aria-label="Capability details">
                {feature.details.map((detail) => (
                  <li key={detail} className="before:mr-1.5 before:text-white/25 before:content-['/']">{detail}</li>
                ))}
              </ul>
              <dl className="mt-6 grid grid-cols-2 gap-4 border-t border-white/10 pt-5">
                {feature.metrics.map((metric) => (
                  <div key={metric.label}>
                    <dt className="text-[10px] uppercase text-white/40">{metric.label}</dt>
                    <dd className="mt-1 font-heading text-2xl italic leading-none text-white">{metric.value}</dd>
                  </div>
                ))}
              </dl>
            </div>
          </motion.article>
        )
      })}
    </div>
  )
}
