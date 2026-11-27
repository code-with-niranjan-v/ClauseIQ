import { useState } from 'react'
import { api } from '../../api.js'
import { Heading, Table, Tag } from '../components.jsx'
import { date, title } from '../format.js'

export default function Ingest({ data, refresh }) {
  const { sources = [], documents = [], processing, queue = [] } = data
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [dragging, setDragging] = useState(false)
  async function perform(operation, started) {
    if (busy) return
    setBusy(true)
    setMessage(started)
    try { setMessage(await operation()) }
    catch (error) { setMessage(error.message) }
    finally { setBusy(false); refresh() }
  }
  function upload(fileList) {
    const files = Array.from(fileList ?? [])
    if (!files.length) return
    perform(async () => {
      let queued = 0
      let duplicates = 0
      const failures = []
      // One file at a time, so uploads take the scanner's source lock in turn.
      for (const file of files) {
        if (!file.name.toLowerCase().endsWith('.pdf')) { failures.push(`${file.name} is not a PDF`); continue }
        if (file.size > 30 * 1024 * 1024) { failures.push(`${file.name} exceeds 30 MiB`); continue }
        try {
          const result = await api.uploadPdf(file, processing?.clearedBefore)
          if (result?.added) queued++
          else duplicates++
        } catch (error) {
          failures.push(`${file.name}: ${error.message}`)
        }
      }
      const summary = `${queued} queued, ${duplicates} already uploaded, ${failures.length} failed.`
      return failures.length ? `${summary} ${failures.join('; ')}` : summary
    }, `Uploading ${files.length} PDF${files.length === 1 ? '' : 's'}…`)
  }
  return <><Heading name="Ingest" description="Upload PDFs or pull from regulator sites." />
    <div className="strip"><label className={`drop ${dragging ? 'o' : ''}`} onDragOver={(event) => { event.preventDefault(); setDragging(true) }}
      onDragLeave={() => setDragging(false)} onDrop={(event) => { event.preventDefault(); setDragging(false); upload(event.dataTransfer.files) }}>
      <input type="file" accept=".pdf,application/pdf" multiple disabled={busy} onChange={(event) => { upload(event.target.files); event.target.value = '' }} />
      ⬆ Drop PDFs here or click to upload</label>
      <button className="btn" disabled={busy || !processing} onClick={() => perform(async () => {
        await api.setPaused(!processing.paused)
        return processing.paused ? 'Processing resumed.' : 'Processing paused.'
      }, 'Updating processing…')}>{processing?.paused ? 'Resume' : 'Pause'}</button>
      <button className="btn" disabled={busy || !processing} onClick={() => {
        if (window.confirm('Clear waiting ingestion jobs?')) perform(async () => { await api.clearQueue(); return 'Ingestion queue cleared.' }, 'Clearing queue…')
      }}>Clear queue</button></div>
    <div className="sec"><div className="pipe">{['Parse PDF', 'Extract obligations', 'Map to policies', 'Gap analysis', 'Draft actions'].map((stage, index) =>
      <div key={stage}><u>{index + 1}</u>{stage}</div>)}</div>
      <div className="pb"><b className={busy ? 'working' : undefined} /></div>
      <div className="term" role="status"><div>{message || 'Waiting for a document'}</div>
        <div>Consumer · {title(processing?.state ?? processing?.consumer?.state)}</div>
        {queue.slice(0, 5).map((entry) => <div key={entry.id}>› {entry.title} · {entry.published ? 'published' : 'waiting'}</div>)}</div></div>
    <div className="cols"><div className="sec"><div className="sh">Circulars <span>{documents.length} documents</span></div>
      <Table headers={['Reg.', 'Title', 'Discovered', 'Pages', 'Obligations', 'Status']}>{documents.map((item) => <tr key={item.documentVersionId}>
        <td className="cl">{item.regulator}</td><td>{/^https?:\/\//i.test(item.sourceUrl ?? '') ? <a className="text-action" href={item.sourceUrl} target="_blank" rel="noreferrer">{item.title}</a> : item.title}</td>
        <td className="mono">{date(item.createdAt)}</td><td>{item.pageCount ?? '—'}</td><td>{item.obligationCount ?? '—'}</td><td><Tag>{title(item.processingStatus)}</Tag></td></tr>)}</Table>
    </div><div className="sec"><div className="sh">Regulator watcher <span>{sources.length} sources</span></div>
      <Table headers={['Status', 'Source', 'Scan']}>{sources.map((item) => <tr key={item.id}>
        <td><Tag>{title(item.lastRunStatus)}</Tag></td><td>{item.name}<div className="muted">{item.regulator} · {date(item.lastRunAt)}</div></td>
        <td><button className="btn" disabled={busy || item.enabled === false} onClick={() => perform(async () => {
          const result = await api.scan(item.id)
          return `${item.name} · ${title(result.lastRunStatus)} · ${result.lastNewDocuments ?? 0} new${result.lastError ? ` · ${result.lastError}` : ''}`
        }, `Scanning ${item.name}…`)}>{item.id === 'rbi' ? 'Scan RBI' : 'Ingest'}</button></td></tr>)}</Table></div></div>
  </>
}
