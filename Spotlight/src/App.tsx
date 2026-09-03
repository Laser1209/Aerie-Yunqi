import { useLayoutEffect } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import HomePage from './pages/HomePage'
import FeaturesPage from './pages/FeaturesPage'
import ArchitecturePage from './pages/ArchitecturePage'
import CapabilitiesPage from './pages/CapabilitiesPage'
import JournalPage from './pages/JournalPage'
import DownloadPage from './pages/DownloadPage'
import MobilePage from './pages/MobilePage'
import OpenAIAdsConsent from './components/OpenAIAdsConsent'

function ScrollToTop() {
  const { pathname } = useLocation()

  useLayoutEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: 'auto' })
  }, [pathname])

  return null
}

export default function App() {
  return (
    <>
      <ScrollToTop />
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/features" element={<FeaturesPage />} />
        <Route path="/architecture" element={<ArchitecturePage />} />
        <Route path="/capabilities" element={<CapabilitiesPage />} />
        <Route path="/journal" element={<JournalPage />} />
        <Route path="/download" element={<DownloadPage />} />
        <Route path="/mobile" element={<MobilePage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <OpenAIAdsConsent />
    </>
  )
}
