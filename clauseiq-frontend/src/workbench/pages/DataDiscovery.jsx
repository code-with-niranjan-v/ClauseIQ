import { useEffect, useState } from 'react'
import { api } from '../../api.js'
import { useAuth } from '../../authContext.js'
import { Heading, Table, Tag } from '../components.jsx'
import { date, title } from '../format.js'

export default function DataDiscovery() {
  const user = useAuth()
  const [targets, setTargets] = useState([])
  const [target, setTarget] = useState('')
  const [scans, setScans] = useState([])
  const [chosenId, setChosenId] = useState(null)
  const [loaded, setLoaded] = useState(null)
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [revision, setRevision] = useState(0)
  const selected = chosenId ?? scans[0]?.id ?? null
  const scan = loaded?.id === selected ? loaded : null

  useEffect(() => {
    let active = true
    Promise.all([api.scanTargets(), api.dataScans()]).then(([found, list]) => {
      if (!active) return
      setTargets(found)
      setScans(list)
    }, (error) => { if (active) setMessage(error.message) })
    return () => { active = false }
  }, [revision])

  useEffect(() => {
    if (!selected) return undefined
    let active = true
    api.dataScan(selected).then((value) => { if (active) setLoaded(value) }, (error) => { if (active) setMessage(error.message) })
    return () => { active = false }
  }, [selected])

  async function run() {
    const name = target || targets[0]?.name
    if (!name) return
    setBusy(true)
    setMessage('')
    try {
      const result = await api.runDataScan(name)
      setChosenId(result.id)
      setRevision((value) => value + 1)
    } catch (error) { setMessage(error.message) } finally { setBusy(false) }
  }

  const fields = scan?.fields ?? []
  return <><Heading name="Data discovery" description="Scan a configured database's schema for sensitive fields. Metadata only: no row values are read.">
    {targets.length > 0 && <select className="f dd-target" aria-label="Database" value={target || targets[0].name} onChange={(event) => setTarget(event.target.value)}>
      {targets.map((item) => <option key={item.name}>{item.name}</option>)}</select>}
    {user.can.review && <button className="btn p" disabled={busy || targets.length === 0} onClick={run}>{busy ? 'Scanning…' : 'Run scan'}</button>}</Heading>
    {targets.length === 0 && <p className="workbench-empty">No scan targets are configured. Set SCAN_TARGETS for the ingestion worker.</p>}
    {message && <p className="sa-error" role="alert">{message}</p>}
    <div className="sa-cols">
      <div className="sec sa-list"><div className="sh">Scans <span>{scans.length}</span></div>
        {scans.length === 0 && <p className="workbench-empty">No scans yet.</p>}
        {scans.map((item) => <button key={item.id} className={`li ${item.id === selected ? 'on' : ''}`} onClick={() => setChosenId(item.id)}>
          <span /><b>{item.target}</b><Tag>{title(item.status)}</Tag>
          <small>{date(item.createdAt)} · {item.status === 'COMPLETED' ? `${item.sensitiveFields} sensitive, ${item.unprotectedHigh} unprotected high` : item.error}</small>
        </button>)}
      </div>
      <div className="sa-detail">{!scan ? <p className="workbench-empty">{scans.length ? 'Loading…' : 'Run a scan to see results.'}</p> : scan.status === 'FAILED'
        ? <p className="sa-error">{scan.error}</p> : <>
          <div className="rib sa-rib">{[['Tables', scan.tables], ['Columns', scan.columns], ['Sensitive fields', fields.length],
            ['High sensitivity', fields.filter((item) => item.sensitivity === 'HIGH').length],
            ['Unprotected high', fields.filter((item) => item.sensitivity === 'HIGH' && !item.protected).length],
            ['Read by model', fields.filter((item) => item.method === 'AI').length]].map(([label, value]) =>
            <div key={label}><small>{label}</small><b>{value}</b></div>)}</div>
          <div className="sec"><div className="sh">{scan.database} <span>scanned {date(scan.createdAt)}{scan.requestedBy ? ` by ${scan.requestedBy}` : ''}{scan.usedAi ? ' · ambiguous columns read by the model' : ''}</span></div>
            <Table headers={['Field', 'Detected as', 'Sensitivity', 'Protected', 'Why', 'Recommended control']} empty="No sensitive fields found.">
              {fields.map((item) => <tr key={item.id}>
                <td className="mono">{item.table}.{item.column}<div className="muted">{item.dataType}</div></td>
                <td>{title(item.classification)}{item.method === 'AI' && <div className="muted">model, {Math.round(item.confidence * 100)}%</div>}</td>
                <td><Tag>{title(item.sensitivity)}</Tag></td>
                <td>{item.protected ? 'Yes' : <b className="dd-no">No</b>}</td>
                <td className="sa-wrap">{item.reason}</td>
                <td className="sa-wrap">{item.recommendedControl}</td></tr>)}</Table></div></>}
      </div>
    </div>
  </>
}
