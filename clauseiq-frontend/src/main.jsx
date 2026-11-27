import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Link, Navigate, Route, Routes } from 'react-router-dom'
import '@fontsource/ibm-plex-sans/400.css'
import '@fontsource/ibm-plex-sans/500.css'
import '@fontsource/ibm-plex-sans/600.css'
import '@fontsource/ibm-plex-serif/400.css'
import './index.css'
import App from './App.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/test" replace />} />
        <Route path="/test" element={<App />} />
        <Route path="*" element={
          <main className="page">
            <div className="masthead">
              <h1>Page not found</h1>
            </div>
            <Link to="/test">Open the testing dashboard</Link>
          </main>
        } />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
)
