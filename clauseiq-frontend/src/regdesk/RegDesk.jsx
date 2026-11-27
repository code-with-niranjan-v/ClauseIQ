import { useEffect, useState } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { pending, severity } from './format.js'
import { useCatalog, useDetails } from './useWorkbenchData.js'
import workbenchStyles from './workbench.css?inline'
import Overview from './pages/Overview.jsx'
import Ingest from './pages/Ingest.jsx'
import ReviewWorkbench from './pages/ReviewWorkbench.jsx'
import GapsAndMapping from './pages/GapsAndMapping.jsx'
import ActionPlan from './pages/ActionPlan.jsx'
import AuditTrail from './pages/AuditTrail.jsx'
import DataDiscovery from './pages/DataDiscovery.jsx'
import PolicyChat from './PolicyChat.jsx'

const nav = [
  { name: 'Overview', path: '/workbench', icon: 'M3 3v18h18M7 14l3-3 3 2 5-6' },
  { name: 'Ingest', path: '/workbench/ingest', icon: 'M12 3v12m0 0l-4-4m4 4l4-4M4 17v3h16v-3' },
  { name: 'Review workbench', path: '/workbench/review', icon: 'M3 4h6v16H3zM11 4h10v7H11zM11 14h10v6H11z' },
  { name: 'Gaps & mapping', path: '/workbench/gaps', icon: 'M3 6h18M3 12h18M3 18h18M8 3v18M15 3v18' },
  { name: 'Action plan', path: '/workbench/actions', icon: 'M9 6h11M9 12h11M9 18h11M4 6l1 1 2-2M4 12l1 1 2-2M4 18l1 1 2-2' },
  { name: 'Audit trail', path: '/workbench/audit', icon: 'M12 8v4l3 2M3 12a9 9 0 109-9 9 9 0 00-7 3.4M3 4v4h4' },
  { name: 'Data discovery', path: '/workbench/data-discovery', icon: 'M4 6c0-4 16-4 16 0s-16 4-16 0v12c0 4 16 4 16 0V6M4 12c0 4 16 4 16 0' },
]

export default function RegDesk() {
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const page = nav.findIndex(({ path }) => pathname.replace(/\/$/, '') === path)
  const setPage = (index) => navigate(nav[index].path)
  const [selected, setSelected] = useState(null)
  const [filter, setFilter] = useState('All')
  const [qa, setQa] = useState(false)
  const [chat, setChat] = useState([])
  const [dark, setDark] = useState(() => localStorage.getItem('regdesk-theme') === 'dark')
  const [sidebarExpanded, setSidebarExpanded] = useState(() => {
    if (window.matchMedia('(max-width: 660px)').matches) return false
    const preference = localStorage.getItem('regdesk-sidebar')
    return preference ? preference === 'expanded' : window.matchMedia('(min-width: 1150px)').matches
  })
  const [revision, setRevision] = useState(0)
  const { data, error, refresh } = useCatalog()
  const { documents = [], obligations = [], findings = [], sources = [], roles = [] } = data
  const visible = findings.filter((item) => filter === 'All' || (filter === 'Pending' ? pending(item) : severity(item) === filter))
  const current = visible.find((item) => item.id === selected) ?? visible[0]
  const detailsKey = page === 2 ? current?.id : [0, 3, 4, 5].includes(page) ? findings.map(({ id }) => id).join(',') : ''
  const { entries: details, error: detailError } = useDetails(detailsKey, revision)
  const audit = Object.values(details).flatMap((item) => item.decisions.map((decision) => ({ ...decision, item })))
    .sort((a, b) => Date.parse(b.decidedAt) - Date.parse(a.decidedAt))
  const open = (id) => { setSelected(id); setFilter('All'); setPage(2) }

  function toggleSidebar() {
    const expanded = !sidebarExpanded
    setSidebarExpanded(expanded)
    if (!window.matchMedia('(max-width: 660px)').matches) {
      localStorage.setItem('regdesk-sidebar', expanded ? 'expanded' : 'collapsed')
    }
  }

  function closeSidebarOnMobile() {
    if (window.matchMedia('(max-width: 660px)').matches) setSidebarExpanded(false)
  }

  useEffect(() => {
    localStorage.setItem('regdesk-theme', dark ? 'dark' : 'light')
  }, [dark])

  useEffect(() => {
    function shortcuts(event) {
      if (event.key === 'Escape') setQa(false)
      if (event.ctrlKey || event.metaKey || event.altKey || event.target.closest('input,textarea,select,[contenteditable]')) return
      if (event.key === '/') { event.preventDefault(); setQa(true) }
      if (page !== 2 || qa || !['j', 'k'].includes(event.key)) return
      const index = visible.findIndex(({ id }) => id === current?.id)
      const next = visible[index + (event.key === 'j' ? 1 : -1)]
      if (next) setSelected(next.id)
    }
    window.addEventListener('keydown', shortcuts)
    return () => window.removeEventListener('keydown', shortcuts)
  })

  if (page < 0) return <Navigate to="/workbench" replace />

  function handleReviewSaved() {
    refresh()
    setRevision((value) => value + 1)
  }

  let screen
  switch (page) {
    case 1:
      screen = <Ingest data={data} refresh={refresh} />
      break
    case 2:
      screen = <ReviewWorkbench visible={visible} current={current} filter={filter} setFilter={setFilter}
        setSelected={setSelected} details={details} roles={roles} onSaved={handleReviewSaved} detailError={detailError} />
      break
    case 3:
      screen = <GapsAndMapping obligations={obligations} findings={findings} details={details} open={open} />
      break
    case 4:
      screen = <ActionPlan details={details} open={open} />
      break
    case 5:
      screen = <AuditTrail audit={audit} open={open} />
      break
    case 6:
      screen = <DataDiscovery />
      break
    default:
      screen = <Overview documents={documents} obligations={obligations} findings={findings} details={details}
        audit={audit} sources={sources} open={open} navigate={setPage} />
  }

  return <div className={dark ? "regdesk dark" : "regdesk"}><style>{workbenchStyles}</style><div className="shell" data-sidebar={sidebarExpanded ? 'expanded' : 'collapsed'}><header className="bar"><div className="logo">RD</div>
    <button type="button" className="tb sidebar-toggle" aria-controls="regdesk-sidebar" aria-expanded={sidebarExpanded}
      aria-label={sidebarExpanded ? 'Collapse sidebar' : 'Expand sidebar'} title={sidebarExpanded ? 'Collapse sidebar' : 'Expand sidebar'} onClick={toggleSidebar}>
      <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2" /><path d="M9 5v14" /></svg>
    </button><div className="crumb">RegDesk <span>/ {nav[page].name}</span></div>
    <button className="cmd" aria-label="Ask the approved policies" onClick={() => setQa(true)}><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="7" /><path d="M21 21l-4-4" /></svg><span>Ask the approved policies…</span><kbd>/</kbd></button>
    <span className="live">{sources.length > 0 && <i />} {sources.length ? `Watching ${sources.map((source) => source.regulator).join(' · ')}` : 'Regulator watcher'}</span>
    <button className="tb" aria-label="Toggle theme" aria-pressed={dark} onClick={() => setDark(!dark)}>◐</button>
    <div className="me" title="Reviewer">R</div></header>
    <nav id="regdesk-sidebar" className="rail" aria-label="Workbench">{nav.map(({ name, icon, path }, index) => <Link key={path} to={path} className={`rb ${page === index ? 'on' : ''}`} data-t={name}
      aria-label={name} aria-current={page === index ? 'page' : undefined} onClick={closeSidebarOnMobile}><svg viewBox="0 0 24 24"><path d={icon} /></svg>
      <span className="nav-label">{name}</span>{index === 2 && <b>{findings.filter(pending).length}</b>}</Link>)}
      <Link className="rb" to="/test" data-t="Testing dashboard" aria-label="Testing dashboard"><svg viewBox="0 0 24 24"><path d="M4 5h16v14H4zM8 10l2 2-2 2m5 0h3" /></svg><span className="nav-label">Testing dashboard</span></Link>
      <span className="sp" /><button className="rb" data-t="Policy Q&A ( / )" aria-label="Policy Q&A" onClick={() => setQa(true)}>
        <svg viewBox="0 0 24 24"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" /></svg><span className="nav-label">Policy Q&amp;A</span></button></nav>
    <main key={page}><div className="pg">{(error || (page !== 2 && detailError)) && <p className="workbench-empty" role="status">{error || detailError}</p>}{screen}</div></main>
  </div>{qa && <aside className="slide" aria-label="Policy Q&A"><div className="sh">Policy Q&A <span>approved policies only</span>
    <button className="btn r" onClick={() => setQa(false)}>Close <kbd>Esc</kbd></button></div>
    <PolicyChat messages={chat} setMessages={setChat} />
  </aside>}</div>
}
