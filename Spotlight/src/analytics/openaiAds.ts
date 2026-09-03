type Oaiq = ((command: string, ...args: unknown[]) => void) & {
  q?: unknown[]
}

declare global {
  interface Window {
    oaiq?: Oaiq
  }
}

let initialized = false
const CONSENT_STORAGE_KEY = 'aerie.openai_ads_consent'
const CONSENT_CHANGED_EVENT = 'aerie:openai-ads-consent-changed'

function config() {
  return {
    pixelId: String(import.meta.env.VITE_OPENAI_ADS_PIXEL_ID || '').trim(),
    enabled: String(import.meta.env.VITE_OPENAI_ADS_MEASUREMENT_ENABLED || '').toLowerCase() === 'true',
  }
}

export type OpenAIAdsConsent = 'granted' | 'denied' | null

export function isOpenAIAdsConfigured() {
  const { pixelId, enabled } = config()
  return enabled && Boolean(pixelId)
}

export function getOpenAIAdsConsent(): OpenAIAdsConsent {
  if (typeof window === 'undefined') return null
  try {
    const value = window.localStorage.getItem(CONSENT_STORAGE_KEY)
    return value === 'granted' || value === 'denied' ? value : null
  } catch {
    return null
  }
}

export function setOpenAIAdsConsent(value: Exclude<OpenAIAdsConsent, null>) {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(CONSENT_STORAGE_KEY, value)
  } catch {
    // Storage can be unavailable in privacy modes; keep measurement disabled.
  }
  window.dispatchEvent(new CustomEvent(CONSENT_CHANGED_EVENT, { detail: value }))
  if (value === 'granted') initializeOpenAIAds()
}

export function onOpenAIAdsConsentChanged(listener: (value: OpenAIAdsConsent) => void) {
  if (typeof window === 'undefined') return () => undefined
  const handler = (event: Event) => listener((event as CustomEvent<OpenAIAdsConsent>).detail)
  window.addEventListener(CONSENT_CHANGED_EVENT, handler)
  return () => window.removeEventListener(CONSENT_CHANGED_EVENT, handler)
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
  const { pixelId, enabled } = config()
  if (!enabled || !pixelId || getOpenAIAdsConsent() !== 'granted') return
  initialized = true
  ensurePixel(pixelId)?.('measure', 'page_viewed', {})
}

export function measureOpenAIAds(eventName: 'contents_viewed') {
  const { pixelId, enabled } = config()
  if (!enabled || !pixelId || getOpenAIAdsConsent() !== 'granted') return
  ensurePixel(pixelId)?.('measure', eventName, {})
}
