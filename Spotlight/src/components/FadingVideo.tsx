import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties } from 'react'

interface FadingVideoProps {
  src: string | string[]
  className?: string
  style?: CSSProperties
  poster?: string
}

export default function FadingVideo({ src, className, style, poster }: FadingVideoProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const rafRef = useRef<number | null>(null)
  const fadedOutRef = useRef(false)
  const failedSourceIndexesRef = useRef<Set<number>>(new Set())
  const sources = useMemo(() => (Array.isArray(src) ? src : [src]), [src])
  const [index, setIndex] = useState(0)
  const [failed, setFailed] = useState(false)
  const [reducedMotion, setReducedMotion] = useState(false)

  const fadeTo = useCallback((target: number, duration: number) => {
    const video = videoRef.current
    if (!video) return
    if (rafRef.current !== null) cancelAnimationFrame(rafRef.current)
    if (duration <= 0) {
      video.style.opacity = String(target)
      return
    }
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
    const media = window.matchMedia('(prefers-reduced-motion: reduce)')
    const syncMotion = () => setReducedMotion(media.matches)
    syncMotion()
    media.addEventListener('change', syncMotion)
    return () => media.removeEventListener('change', syncMotion)
  }, [])

  useEffect(() => {
    failedSourceIndexesRef.current.clear()
    setIndex(0)
    setFailed(false)
  }, [sources])

  useEffect(() => {
    const video = videoRef.current
    if (!video) return

    fadedOutRef.current = false
    setFailed(false)
    video.style.opacity = '0'

    const handleLoadedData = () => {
      failedSourceIndexesRef.current.delete(index)
      fadeTo(1, reducedMotion ? 0 : 500)
    }
    const handleTimeUpdate = () => {
      if (!reducedMotion && !fadedOutRef.current && video.duration && video.duration - video.currentTime <= 0.55) {
        fadedOutRef.current = true
        fadeTo(0, 550)
      }
    }
    const handleEnded = () => {
      if (sources.length === 1) {
        video.currentTime = 0
        fadedOutRef.current = false
        if (!reducedMotion) void video.play().catch(() => undefined)
        fadeTo(1, reducedMotion ? 0 : 500)
      } else {
        setIndex((i) => (i + 1) % sources.length)
      }
    }
    const handleError = () => {
      if (sources.length > 1) {
        const failedIndexes = failedSourceIndexesRef.current
        failedIndexes.add(index)

        if (failedIndexes.size >= sources.length) {
          setFailed(true)
          return
        }

        setIndex((currentIndex) => {
          for (let offset = 1; offset <= sources.length; offset += 1) {
            const candidateIndex = (currentIndex + offset) % sources.length
            if (!failedIndexes.has(candidateIndex)) return candidateIndex
          }
          return currentIndex
        })
      } else {
        setFailed(true)
      }
    }

    video.addEventListener('loadeddata', handleLoadedData)
    video.addEventListener('timeupdate', handleTimeUpdate)
    video.addEventListener('ended', handleEnded)
    video.addEventListener('error', handleError)
    video.load()
    if (!reducedMotion) void video.play().catch(() => undefined)
    return () => {
      video.removeEventListener('loadeddata', handleLoadedData)
      video.removeEventListener('timeupdate', handleTimeUpdate)
      video.removeEventListener('ended', handleEnded)
      video.removeEventListener('error', handleError)
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current)
    }
  }, [sources, index, fadeTo, reducedMotion])

  return (
    <video
      ref={videoRef}
      src={sources[index]}
      className={className}
      style={{ opacity: 0, display: failed ? 'none' : undefined, ...style }}
      poster={poster}
      autoPlay={!reducedMotion}
      muted
      playsInline
      preload="auto"
      aria-hidden="true"
    />
  )
}
