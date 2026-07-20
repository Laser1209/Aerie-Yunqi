import type { CSSProperties, ReactNode } from 'react'
import FadingVideo from './FadingVideo'
import SiteHeader from './SiteHeader'

interface PageShellProps {
  videoSrc: string
  children: ReactNode
  videoClassName?: string
  videoStyle?: CSSProperties
  videoPoster?: string
  fallbackColor?: string
  accent?: string
  overlayClassName?: string
  scrollable?: boolean
}

export default function PageShell({
  videoSrc,
  children,
  videoClassName = 'absolute inset-0 h-full w-full object-cover',
  videoStyle,
  videoPoster,
  fallbackColor = '#050608',
  accent = '#8de7dc',
  overlayClassName = '',
  scrollable = false,
}: PageShellProps) {
  const shellStyle = { '--page-accent': accent } as CSSProperties

  return (
    <main className={`page-shell relative min-h-screen bg-black text-white ${scrollable ? '' : 'overflow-hidden'}`} style={shellStyle}>
      <div className="page-media fixed inset-0 z-0 overflow-hidden" style={{ backgroundColor: fallbackColor }}>
        <FadingVideo src={videoSrc} className={videoClassName} style={videoStyle} poster={videoPoster} />
        <div className={`page-media-overlay absolute inset-0 bg-black/20 ${overlayClassName}`} />
        <div className="page-media-vignette absolute inset-0" aria-hidden="true" />
      </div>
      <SiteHeader />
      <div className="relative z-10 min-h-screen overflow-x-hidden">{children}</div>
    </main>
  )
}
