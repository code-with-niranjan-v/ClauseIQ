import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Link, Navigate, Route, Routes } from 'react-router-dom'
import '@fontsource/ibm-plex-sans/400.css'
import '@fontsource/ibm-plex-sans/500.css'
import '@fontsource/ibm-plex-sans/600.css'
import '@fontsource/ibm-plex-serif/400.css'
import testDashboardStyles from './index.css?inline'
import TestDashboard from './App.jsx'
import RegDesk from './regdesk/RegDesk.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/workbench" replace />} />
        <Route path="/test" element={<><style>{testDashboardStyles}</style><TestDashboard /></>} />
        <Route path="/workbench/*" element={<RegDesk />} />
        <Route path="*" element={<main><h1>Page not found</h1><Link to="/workbench">Open RegDesk</Link></main>} />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
)
