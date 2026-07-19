import { Navigate, Route, Routes } from 'react-router-dom'
import HomePage from './pages/HomePage'
import FeaturesPage from './pages/FeaturesPage'
import ArchitecturePage from './pages/ArchitecturePage'
import CapabilitiesPage from './pages/CapabilitiesPage'
import JournalPage from './pages/JournalPage'
import DownloadPage from './pages/DownloadPage'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/features" element={<FeaturesPage />} />
      <Route path="/architecture" element={<ArchitecturePage />} />
      <Route path="/capabilities" element={<CapabilitiesPage />} />
      <Route path="/journal" element={<JournalPage />} />
      <Route path="/download" element={<DownloadPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
