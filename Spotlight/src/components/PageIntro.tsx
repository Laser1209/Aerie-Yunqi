import { motion, useReducedMotion } from 'framer-motion'

interface PageIntroProps {
  label: string
  title: string
  description?: string
}

export default function PageIntro({ label, title, description }: PageIntroProps) {
  const reduceMotion = useReducedMotion()

  return (
    <motion.div
      initial={reduceMotion ? false : { opacity: 0, y: 18, filter: 'blur(8px)' }}
      animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
      transition={{ duration: reduceMotion ? 0 : 0.75, ease: [0.22, 1, 0.36, 1] }}
    >
      <p className="mb-5 font-body text-sm text-white/80">// {label}</p>
      <h1 className="max-w-5xl whitespace-pre-line font-heading italic text-5xl leading-[0.88] tracking-[-3px] text-white md:text-7xl lg:text-[5.5rem]">
        {title}
      </h1>
      {description && (
        <p className="mt-5 max-w-2xl text-sm font-light leading-snug text-white/80 md:text-base">
          {description}
        </p>
      )}
    </motion.div>
  )
}
