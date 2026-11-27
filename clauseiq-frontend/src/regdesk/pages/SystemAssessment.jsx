import { Fragment, useCallback, useEffect, useState } from 'react'
import { api } from '../../api.js'
import { Heading, Table, Tag } from '../components.jsx'
import { date, title } from '../format.js'

const inputs = [
  { key: 'sre', label: 'SRE document', hint: 'PDF', demo: 'neopay-sre.pdf' },
  { key: 'architecture', label: 'Architecture diagram', hint: 'PDF or image', demo: 'neopay-architecture.png' },
  { key: 'er', label: 'ER diagram', hint: 'PDF or image', demo: 'neopay-er-diagram.png' },
]
const accept = '.pdf,.png,.jpg,.jpeg,.webp,application/pdf,image/png,image/jpeg,image/webp'
const running = (item) => ['QUEUED', 'PROCESSING'].includes(item?.status)
const kinds = { SRE: 'SRE document', ARCHITECTURE: 'Architecture diagram', ER: 'ER diagram' }

function Circular({ circular }) {
  const label = `${circular.regulator}: ${circular.title}`
  return /^https?:\/\//i.test(circular.sourceUrl ?? '')
    ? <a className="text-action" href={circular.sourceUrl} target="_blank" rel="noreferrer">{label}</a>
    : label
}

function Evidence({ item }) {
  return <li><span className="cl">{kinds[item.kind] ?? item.kind}{item.pageNumber ? ` · p.${item.pageNumber}` : ''}</span> {item.content}</li>
}

function Detail({ assessment }) {
  const [open, setOpen] = useState(null)
  if (running(assessment)) {
    return <div className="sec sa-wait"><div className="pb"><b className="working" /></div>
      <p>{assessment.stage || 'Waiting to start'}…</p>
      <p className="muted">Reading diagrams and comparing obligations takes a minute or two.</p></div>
  }
  if (assessment.status === 'FAILED') {
    return <div className="sec sa-wait"><p className="sa-error" role="alert">{assessment.error}</p></div>
  }
  const { stats, artifacts, findings, plan } = assessment
  const open_findings = findings.filter((item) => item.status !== 'MEETS')
  const meets = findings.filter((item) => item.status === 'MEETS')
  return <>
    <div className="rib sa-rib">
      {[['System facts read', stats.facts], ['Obligations compared', stats.compared], ['Not applicable', stats.notApplicable],
        ['Meets', stats.meets], ['Open findings', stats.open],
        ['High severity', open_findings.filter((item) => item.severity === 'HIGH').length]].map(([label, value]) =>
        <div key={label}><small>{label}</small><b>{value ?? '—'}</b></div>)}
    </div>
    <div className="sec"><div className="sh">Documents read <span>{artifacts.length}</span></div>
      <Table headers={['Document', 'File', 'Read by', 'Facts', 'What it shows']}>{artifacts.map((item) => <tr key={item.id}>
        <td>{kinds[item.kind]}</td><td className="mono">{item.filename}</td>
        <td><Tag>{item.method === 'VISION' ? 'Vision model' : 'Text'}</Tag></td><td>{item.factCount}</td>
        <td className="sa-wrap">{item.summary || '—'}</td></tr>)}</Table></div>
    <div className="sec"><div className="sh">Improvement plan <span>open findings by priority, quick wins first</span></div>
      {plan.length === 0 ? <p className="workbench-empty">No open findings.</p>
        : <Table headers={['Improvement', 'Owner', 'Effort', 'Circular']}>{plan.flatMap((phase) => [
          <tr key={phase.phase} className="gr"><td colSpan="4">{phase.phase} · {phase.window}</td></tr>,
          ...phase.items.map((item) => <tr key={item.findingId}>
            <td className="sa-wrap"><b>{item.title}</b><div>{item.improvement}</div></td>
            <td>{item.ownerRole}</td><td><Tag>{title(item.effort)}</Tag></td>
            <td className="sa-wrap"><Circular circular={item.circular} /></td></tr>),
        ])}</Table>}</div>
    <div className="sec"><div className="sh">Findings <span>{open_findings.length} open · {meets.length} meet the obligation</span></div>
      <Table headers={['Severity', 'Result', 'Finding', 'Circular obligation']}>{[...open_findings, ...meets].map((item) =>
        <Fragment key={item.id}>
          <tr className="k" onClick={() => setOpen(open === item.id ? null : item.id)} aria-expanded={open === item.id}>
            <td><Tag>{item.severity ? title(item.severity) : 'Covered'}</Tag></td>
            <td><span className={`sa-status ${item.status}`}>{title(item.status)}</span></td>
            <td className="sa-wrap"><b>{item.title}</b>{item.systemQuote && <q className="sa-quote">{item.systemQuote}</q>}</td>
            <td className="sa-wrap">{item.obligation.summary}<div className="muted"><Circular circular={item.obligation.circular} /></div></td>
          </tr>
          {open === item.id && <tr className="sa-more"><td colSpan="4">
            <p>{item.explanation}</p>
            {item.improvement && <p><b>Improvement:</b> {item.improvement} <span className="muted">· {item.ownerRole} · {title(item.effort)} effort</span></p>}
            {item.obligation.quotedText && <p><b>Circular text</b>{item.obligation.pageNumber ? ` (p.${item.obligation.pageNumber})` : ''}: <q>{item.obligation.quotedText}</q></p>}
            <b>System evidence</b><ul className="sa-evidence">{item.evidence.map((entry) => <Evidence key={entry.id} item={entry} />)}</ul>
            <p className="muted">Confidence {Math.round(item.confidence * 100)}%. Diagram evidence was read by a vision model; check it against the diagram.</p>
          </td></tr>}
        </Fragment>)}</Table></div>
  </>
}

export default function SystemAssessment() {
  const [name, setName] = useState('')
  const [files, setFiles] = useState({})
  const [list, setList] = useState([])
  const [chosenId, setChosenId] = useState(null)
  const [loaded, setLoaded] = useState(null)
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [revision, setRevision] = useState(0)
  const reload = useCallback(() => setRevision((value) => value + 1), [])
  const selected = chosenId ?? list[0]?.id ?? null
  const detail = loaded?.id === selected ? loaded : null

  useEffect(() => {
    let active = true
    api.systemAssessments().then((items) => { if (active) setList(items) },
      (error) => { if (active) setMessage(error.message) })
    return () => { active = false }
  }, [revision])

  useEffect(() => {
    if (!selected) return undefined
    let active = true
    let timer
    async function load() {
      try {
        const item = await api.systemAssessment(selected)
        if (!active) return
        setLoaded(item)
        if (running(item)) timer = setTimeout(load, 3000)
        else reload()
      } catch (error) { if (active) setMessage(error.message) }
    }
    load()
    return () => { active = false; clearTimeout(timer) }
  }, [selected, reload])

  async function submit(chosen, systemName) {
    if (busy) return
    const form = new FormData()
    form.append('name', systemName)
    for (const { key } of inputs) if (chosen[key]) form.append(key, chosen[key])
    setBusy(true)
    setMessage('')
    try {
      const created = await api.createSystemAssessment(form)
      setFiles({})
      setName('')
      setChosenId(created.id)
      reload()
    } catch (error) { setMessage(error.message) } finally { setBusy(false) }
  }

  async function loadDemo() {
    setBusy(true)
    setMessage('')
    try {
      const demo = {}
      for (const { key, demo: file } of inputs) {
        const response = await fetch(`/demo-bank/${file}`)
        if (!response.ok) throw new Error(`Could not load the demo file ${file}.`)
        const blob = await response.blob()
        demo[key] = new File([blob], file, { type: blob.type })
      }
      setBusy(false)
      await submit(demo, 'NeoPay (Kaveri Bank demo)')
    } catch (error) { setMessage(error.message); setBusy(false) }
  }

  const chosen = inputs.filter(({ key }) => files[key]).length
  return <><Heading name="System assessment" description="Compare a system's SRE document, architecture diagram and ER diagram with ingested circulars.">
    <button className="btn" disabled={busy} onClick={loadDemo}>Use demo bank files</button></Heading>
    <form className="strip sa-form" onSubmit={(event) => { event.preventDefault(); submit(files, name) }}>
      <input className="f sa-name" aria-label="System name" placeholder="System name" maxLength={120} value={name}
        onChange={(event) => setName(event.target.value)} />
      {inputs.map(({ key, label, hint }) => <label key={key} className={`sa-file ${files[key] ? 'on' : ''}`}>
        <input type="file" accept={accept} onChange={(event) => setFiles({ ...files, [key]: event.target.files[0] })} />
        <b>{label}</b><span>{files[key]?.name ?? hint}</span></label>)}
      <button className="btn p" disabled={busy || chosen === 0}>{busy ? 'Uploading…' : 'Run assessment'}</button>
    </form>
    {message && <p className="sa-error" role="alert">{message}</p>}
    <div className="sa-cols">
      <div className="sec sa-list"><div className="sh">Assessments <span>{list.length}</span></div>
        {list.length === 0 && <p className="workbench-empty">No assessments yet. Upload documents or use the demo bank files.</p>}
        {list.map((item) => <button key={item.id} className={`li ${item.id === selected ? 'on' : ''}`} onClick={() => setChosenId(item.id)}>
          <span /><b>{item.name}</b><Tag>{title(item.status)}</Tag>
          <small>{date(item.createdAt)} · {item.status === 'COMPLETED' ? `${item.openFindings} open, ${item.highFindings} high` : item.stage || item.error || ''}</small>
        </button>)}
      </div>
      <div className="sa-detail">{detail ? <><div className="sh sa-title">{detail.name}<span>{title(detail.status)}</span></div><Detail assessment={detail} /></>
        : <p className="workbench-empty">Select an assessment.</p>}</div>
    </div>
  </>
}
