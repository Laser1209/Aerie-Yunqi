interface PageIntroProps {
  label: string
  title: string
  description?: string
}

export default function PageIntro({ label, title, description }: PageIntroProps) {
  return (
    <div>
      <p className="mb-5 text-sm text-white/80 font-body">// {label}</p>
      <h1 className="max-w-5xl whitespace-pre-line font-heading italic text-5xl leading-[0.88] tracking-[-3px] text-white md:text-7xl lg:text-[5.5rem]">
        {title}
      </h1>
      {description && (
        <p className="mt-5 max-w-2xl text-sm font-light leading-snug text-white/80 md:text-base">
          {description}
        </p>
      )}
    </div>
  )
}
