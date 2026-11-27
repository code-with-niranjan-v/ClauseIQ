import { useState } from 'react'
import Status from './Status.jsx'
import { label } from './labels.js'

const stages = ['Discovered', 'Queued', 'Processing', 'Results']

export function CircularProgress({ item }) {
  const failed = ['FAILED', 'DEAD_LETTERED'].includes(item.status)
  const step = { WAITING_TO_PUBLISH: 1, QUEUED: 1, PROCESSING: 2, FAILED: 2, DEAD_LETTERED: 2, COMPLETED: 3 }[item.status] ?? 0
  return <>
    <Status value={item.status} />
    <ol className="circular-progress" aria-label="Circular progress">
      {stages.map((stage, index) => (
        <li key={stage} className={index < step || item.status === 'COMPLETED' ? 'done' : index === step ? (failed ? 'failed' : 'current') : ''}
          aria-current={index === step ? 'step' : undefined}>{stage}</li>
      ))}
    </ol>
    {item.publicationError && <span className="sub circular-error">{item.publicationError}</span>}
    {failed && <span className="sub circular-error">{item.processingError || 'The worker did not report an error detail.'}
      {item.processingAttempts > 0 && ` (${item.processingAttempts} ${item.processingAttempts === 1 ? 'attempt' : 'attempts'})`}</span>}
  </>
}

export default function CircularList({ items, selectedId, select, when }) {
  const [search, setSearch] = useState('')
  const [regulator, setRegulator] = useState('')
  const [status, setStatus] = useState('')
  const regulators = [...new Set(items.map((item) => item.regulator))].sort()
  const visible = items.filter((item) =>
    (!regulator || item.regulator === regulator) &&
    (!status || item.status === status) &&
    (!search.trim() || `${item.title} ${item.regulator}`.toLowerCase().includes(search.trim().toLowerCase())),
  )
  return <>
    <div className="dashboard-filters">
      <label>Search circulars<input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Title or regulator" /></label>
      <label>Regulator<select value={regulator} onChange={(event) => setRegulator(event.target.value)}>
        <option value="">All regulators</option>
        {regulators.map((item) => <option key={item}>{item}</option>)}
      </select></label>
      <label>Pipeline status<select value={status} onChange={(event) => setStatus(event.target.value)}>
        <option value="">All statuses</option>
        {['WAITING_TO_PUBLISH', 'QUEUED', 'PROCESSING', 'COMPLETED', 'FAILED', 'DEAD_LETTERED'].map((item) =>
          <option value={item} key={item}>{label(item)}</option>)}
      </select></label>
      {(search || regulator || status) && <button type="button" className="button" onClick={() => {
        setSearch(''); setRegulator(''); setStatus('')
      }}>Reset filters</button>}
    </div>
    <p className="sub results-count" role="status">Showing {visible.length} of {items.length} circulars</p>
    {!visible.length ? <p className="notice">No circulars match the current filters.</p> :
      <div className="table-wrap dashboard-scroll">
        <table aria-label="Circular pipeline">
          <thead><tr>
            <th>Circular</th><th>Pipeline</th><th className="number">Pages</th>
            <th className="number">Obligations</th><th className="number">Findings</th><th><span className="sr-only">Filter</span></th>
          </tr></thead>
          <tbody>{visible.map((item) => (
            <tr key={item.documentVersionId} className={item.documentVersionId === selectedId ? 'selected' : ''}>
              <td>
                <strong>{item.title || 'Untitled circular'}</strong>
                <span className="sub">
                  {item.regulator}, received {when(item.createdAt)}
                  {/^https?:\/\//i.test(item.sourceUrl ?? '') && <>, <a href={item.sourceUrl} target="_blank" rel="noreferrer">source</a></>}
                </span>
              </td>
              <td><CircularProgress item={item} /></td>
              <td className="number">{item.pageCount ?? '—'}</td>
              <td className="number">{item.obligationCount ?? '—'}</td>
              <td className="number">
                {item.findingCount ?? '—'}
                {item.pendingFindingCount > 0 && <span className="sub">{item.pendingFindingCount} pending</span>}
              </td>
              <td className="action"><button type="button" className="link"
                onClick={() => select(item.documentVersionId === selectedId ? null : item.documentVersionId)}>
                {item.documentVersionId === selectedId ? 'Show all' : 'Show only this'}
              </button></td>
            </tr>
          ))}</tbody>
        </table>
      </div>}
  </>
}
