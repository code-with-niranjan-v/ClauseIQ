import { useEffect, useState } from 'react'
import { api } from '../../api.js'
import { Filters, Heading, Table, Tag } from '../components.jsx'
import { date, title } from '../format.js'

const pct = (value) => value === null || value === undefined ? '—' : `${Math.round(value * 100)}%`

export default function ExtractionQuality() {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [filter, setFilter] = useState('Flagged')

  useEffect(() => {
    let active = true
    api.quality().then((value) => { if (active) setData(value) }, (failure) => { if (active) setError(failure.message) })
    return () => { active = false }
  }, [])

  if (error) return <p className="sa-error">{error}</p>
  if (!data) return <p className="workbench-empty">Loading…</p>
  const { summary, circulars } = data
  const shown = (filter === 'Flagged' ? circulars.filter((item) => item.flags.length) : circulars)
    .toSorted((a, b) => b.flags.length - a.flags.length || (b.rejectionRate ?? 0) - (a.rejectionRate ?? 0))
  const limits = summary.thresholds
  return <><Heading name="Extraction quality" description="Where obligation extraction from circulars is weak and needs a human look.">
    <Filters options={['Flagged', 'All']} value={filter} change={setFilter} /></Heading>
    <div className="rib">{[['Circulars', summary.circulars], ['Flagged', summary.flagged], ['Failed', summary.failed],
      ['Quotes rejected', pct(summary.rejectionRate)], ['Mean confidence', pct(summary.meanConfidence)],
      [`Below ${pct(limits.lowConfidenceBelow)} confidence`, pct(summary.lowConfidenceShare)],
      ['Repeated obligations', summary.duplicates]].map(([label, value]) =>
      <div key={label}><small>{label}</small><b>{value}</b></div>)}</div>
    <p className="muted qa-note">A circular is flagged when more than {pct(limits.rejectionRate)} of quotes fail the citation check,
      more than {pct(limits.lowConfidenceShare)} of obligations have low confidence, more than {pct(limits.duplicateShare)} repeat
      each other, extraction found nothing, processing failed, or OCR was needed.
      {summary.ocrUnknown > 0 && ` OCR use is unknown for ${summary.ocrUnknown} circulars processed before it was recorded.`}</p>
    <div className="sec"><Table headers={['Circular', 'Status', 'Obligations', 'Quotes rejected', 'Confidence', 'Low confidence', 'Repeated', 'OCR pages', 'Flags']}
      empty={filter === 'Flagged' ? 'No circulars are flagged.' : 'No circulars yet.'}>
      {shown.map((item) => <tr key={item.documentVersionId}>
        <td className="sa-wrap"><b>{/^https?:\/\//i.test(item.sourceUrl ?? '')
          ? <a className="text-action" href={item.sourceUrl} target="_blank" rel="noreferrer">{item.title}</a> : item.title}</b>
          <div className="muted">{item.regulator} · {item.pages ?? '—'} pages · {date(item.processedAt)}{item.method ? ` · ${item.method}` : ''}</div>
          {item.lastError && item.flags.includes('Processing failed') && <div className="sa-quote">{item.lastError}</div>}</td>
        <td><Tag>{title(item.status)}</Tag></td>
        <td>{item.obligations}{item.withDeadline > 0 && <div className="muted">{item.withDeadline} with deadline</div>}</td>
        <td>{pct(item.rejectionRate)}<div className="muted">{item.rejected} rejected</div></td>
        <td>{pct(item.meanConfidence)}</td><td>{pct(item.lowConfidenceShare)}</td>
        <td>{item.duplicates}</td><td>{item.ocrPages ?? '—'}</td>
        <td className="sa-wrap">{item.flags.map((flag) => <span key={flag} className="qf">{flag}</span>)}</td></tr>)}</Table></div>
  </>
}
