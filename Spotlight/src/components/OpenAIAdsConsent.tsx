import { useEffect, useState } from 'react'
import {
  getOpenAIAdsConsent,
  isOpenAIAdsConfigured,
  onOpenAIAdsConsentChanged,
  setOpenAIAdsConsent,
  type OpenAIAdsConsent as ConsentValue,
} from '../analytics/openaiAds'

export default function OpenAIAdsConsent() {
  const configured = isOpenAIAdsConfigured()
  const [consent, setConsent] = useState<ConsentValue>(() => getOpenAIAdsConsent())
  const [editing, setEditing] = useState(consent === null)

  useEffect(() => onOpenAIAdsConsentChanged((value) => {
    setConsent(value)
    setEditing(false)
  }), [])

  if (!configured) return null

  if (!editing && consent !== null) {
    return (
      <button
        type="button"
        onClick={() => setEditing(true)}
        className="fixed bottom-4 left-4 z-[80] border border-white/15 bg-black/80 px-3 py-2 text-xs text-white/70 shadow-lg backdrop-blur-md transition-colors hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/70"
      >
        隐私选择
      </button>
    )
  }

  return (
    <section
      aria-label="投放效果测量选择"
      className="fixed inset-x-4 bottom-4 z-[90] mx-auto max-w-2xl border border-white/15 bg-black/95 p-4 shadow-2xl backdrop-blur-xl sm:p-5"
    >
      <h2 className="text-sm font-medium text-white">投放效果测量</h2>
      <p className="mt-2 text-xs font-light leading-relaxed text-white/65">
        允许后仅记录官网页面与下载入口事件，用于判断投放效果；不发送聊天内容、角色设定、音频、屏幕内容或 API Key。你可以随时撤回。
      </p>
      <div className="mt-4 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <button
          type="button"
          onClick={() => setOpenAIAdsConsent('denied')}
          className="border border-white/15 px-4 py-2 text-sm text-white/75 transition-colors hover:bg-white/[0.06] hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/70"
        >
          仅必要功能
        </button>
        <button
          type="button"
          onClick={() => setOpenAIAdsConsent('granted')}
          className="bg-white px-4 py-2 text-sm font-medium text-black transition-colors hover:bg-sky-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-2 focus-visible:ring-offset-black"
        >
          允许测量
        </button>
      </div>
    </section>
  )
}
