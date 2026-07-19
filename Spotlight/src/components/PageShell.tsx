import type { ReactNode } from 'react'
import FadingVideo from './FadingVideo'
import SiteHeader from './SiteHeader'

interface PageShellProps {
  videoSrc: string
  children: ReactNode
  videoClassName?: string
  videoStyle?: React.CSSProperties
  scrollable?: boolean
}

export default function PageShell({
  videoSrc,
  children,
  videoClassName = 'absolute inset-0 h-full w-full object-cover',
  videoStyle,
  scrollable = false,
}: PageShellProps) {
  return (
    <main className={`relative min-h-screen bg-black text-white ${scrollable ? '' : 'overflow-hidden'}`}>
      <div className="fixed inset-0 z-0 overflow-hidden bg-black">
        <FadingVideo src={videoSrc} className={videoClassName} style={videoStyle} />
        <div className="absolute inset-0 bg-black/20" />
      </div>
      <SiteHeader />
      <div className="relative z-10 min-h-screen">{children}</div>
    </main>
  )
}
