import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Link, Navigate, Route, Routes } from 'react-router-dom'
import '@fontsource/ibm-plex-sans/400.css'
import '@fontsource/ibm-plex-sans/500.css'
import '@fontsource/ibm-plex-sans/600.css'
import '@fontsource/ibm-plex-serif/400.css'
import testDashboardStyles from './index.css?inline'
import TestDashboard from './App.jsx'
import Workbench from './workbench/Workbench.jsx'
import { AuthGate } from './auth.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <BrowserRouter>
      <AuthGate>
      <Routes>
        <Route path="/" element={<Navigate to="/workbench" replace />} />
        <Route path="/test" element={<><style>{testDashboardStyles}</style><TestDashboard /></>} />
        <Route path="/workbench/*" element={<Workbench />} />
        <Route path="*" element={<main><h1>Page not found</h1><Link to="/workbench">Open ClauseIQ</Link></main>} />
      </Routes>
      </AuthGate>
    </BrowserRouter>
  </StrictMode>,
)
