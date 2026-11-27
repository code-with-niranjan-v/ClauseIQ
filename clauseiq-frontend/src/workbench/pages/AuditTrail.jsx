import { Heading, Table, Tag } from '../components.jsx'
import { title } from '../format.js'

export default function AuditTrail({ audit, open }) {
  return (
    <><Heading name="Audit trail" description="Recorded human review decisions"><button className="btn" disabled={!audit.length} onClick={() => exportAudit(audit)}>Export CSV</button></Heading>
      <div className="sec"><Table headers={['Time', 'Actor', 'Action', 'Item', 'Detail']}>{audit.map((entry) => <tr key={entry.id}>
        <td className="mono">{new Date(entry.decidedAt).toLocaleString()}</td><td>{entry.reviewer}</td><td><Tag>{title(entry.decision)}</Tag></td>
        <td><button className="text-action" onClick={() => open(entry.item.id)}>{entry.item.title}</button></td><td>{entry.comment || '—'}</td>
      </tr>)}</Table></div></>
  )
}

function exportAudit(entries) {
  function cell(value) {
    const text = String(value ?? '')
    const safe = /^[\t\r\n]|^\s*[=+@-]/.test(text) ? "'" + text : text
    return '"' + safe.replaceAll('"', '""') + '"'
  }
  const rows = [['Time', 'Actor', 'Action', 'Item', 'Detail'], ...entries.map((entry) => [
    entry.decidedAt, entry.reviewer, entry.decision, entry.item.title, entry.comment,
  ])]
  const url = URL.createObjectURL(new Blob([rows.map((row) => row.map(cell).join(',')).join('\r\n')], { type: 'text/csv;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = 'clauseiq-audit.csv'
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
