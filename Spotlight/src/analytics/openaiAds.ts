type Oaiq = ((command: string, ...args: unknown[]) => void) & {
  q?: unknown[]
}

declare global {
  interface Window {
    oaiq?: Oaiq
  }
}

let initialized = false

function config() {
  return {
    pixelId: String(import.meta.env.VITE_OPENAI_ADS_PIXEL_ID || '').trim(),
    enabled: String(import.meta.env.VITE_OPENAI_ADS_MEASUREMENT_ENABLED || '').toLowerCase() === 'true',
  }
}

function ensurePixel(pixelId: string): Oaiq | null {
  if (typeof window === 'undefined' || !pixelId) return null
  if (window.oaiq) return window.oaiq

  const queue = ((command: string, ...args: unknown[]) => {
    queue.q?.push([command, ...args])
  }) as Oaiq
  queue.q = []
  window.oaiq = queue

  const script = document.createElement('script')
  script.async = true
  script.src = 'https://bzrcdn.openai.com/sdk/oaiq.min.js'
  script.dataset.aerieAdsPixel = 'true'
  document.head.appendChild(script)
  queue('init', { pixelId })
  return queue
}

export function initializeOpenAIAds() {
  if (initialized) return
  initialized = true
  const { pixelId, enabled } = config()
  if (!enabled) return
  ensurePixel(pixelId)?.('measure', 'page_viewed', {})
}

export function measureOpenAIAds(eventName: 'contents_viewed') {
  const { pixelId, enabled } = config()
  if (!enabled) return
  ensurePixel(pixelId)?.('measure', eventName, {})
}

