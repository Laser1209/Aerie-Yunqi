import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties } from 'react'

interface FadingVideoProps {
  src: string | string[]
  className?: string
  style?: CSSProperties
}

export default function FadingVideo({ src, className, style }: FadingVideoProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const rafRef = useRef<number | null>(null)
  const sources = useMemo(() => (Array.isArray(src) ? src : [src]), [src])
  const [index, setIndex] = useState(0)

  const fadeTo = useCallback((target: number, duration: number) => {
    const video = videoRef.current
    if (!video) return
    if (rafRef.current !== null) cancelAnimationFrame(rafRef.current)
    const from = parseFloat(video.style.opacity || '0')
    const start = performance.now()
    const tick = (now: number) => {
      const t = Math.min((now - start) / duration, 1)
      video.style.opacity = String(from + (target - from) * t)
      if (t < 1) rafRef.current = requestAnimationFrame(tick)
    }
    rafRef.current = requestAnimationFrame(tick)
  }, [])

  useEffect(() => {
    const video = videoRef.current
    if (!video) return

    const handleLoadedData = () => fadeTo(1, 500)
    const handleTimeUpdate = () => {
      if (video.duration && video.duration - video.currentTime <= 0.55) {
        fadeTo(0, 550)
      }
    }
    const handleEnded = () => {
      if (sources.length === 1) {
        video.currentTime = 0
        void video.play()
        fadeTo(1, 500)
      } else {
        setIndex((i) => (i + 1) % sources.length)
      }
    }

    video.addEventListener('loadeddata', handleLoadedData)
    video.addEventListener('timeupdate', handleTimeUpdate)
    video.addEventListener('ended', handleEnded)
    return () => {
      video.removeEventListener('loadeddata', handleLoadedData)
      video.removeEventListener('timeupdate', handleTimeUpdate)
      video.removeEventListener('ended', handleEnded)
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current)
    }
  }, [sources, fadeTo])

  return (
    <video
      ref={videoRef}
      src={sources[index]}
      className={className}
      style={{ opacity: 0, ...style }}
      autoPlay
      muted
      playsInline
      preload="auto"
    />
  )
}
