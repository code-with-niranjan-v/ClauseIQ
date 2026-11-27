import { useCallback, useEffect, useState } from 'react'
import CircularList from './CircularProgress.jsx'
import { api } from './api.js'
import FindingReview from './FindingReview.jsx'
import ProcessingControls from './ProcessingControls.jsx'
import { label } from './labels.js'
import Status from './Status.jsx'

const REFRESH_SECONDS = 10

function when(value) {
  if (!value) return 'Never'
  return new Date(value).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

/** Loads one list and keeps the last good value when a refresh fails. */
function useResource(load, tick) {
  const [state, setState] = useState({ data: null, error: null, loading: true })
  useEffect(() => {
    let current = true
    load()
      .then((data) => current && setState({ data, error: null, loading: false }))
      .catch((error) => current && setState((previous) => ({ ...previous, error: error.message, loading: false })))
    return () => {
      current = false
    }
  }, [load, tick])
  return state
}

function Stage({ number, title, does, count, state, empty, controls, children }) {
  const { data, error, loading } = state
  return (
    <section className="stage" aria-labelledby={`stage-${number}`}>
      <div className="stage-marker" aria-hidden="true">{number}</div>
      <header className="stage-header">
        <h2 id={`stage-${number}`}>{title}</h2>
        {count != null && <span className="stage-count">{count}</span>}
        <p>{does}</p>
      </header>
      {controls}
      {error && <p className="notice notice-bad" role="alert">{error}</p>}
      {loading && !data && <p className="notice">Loading…</p>}
      {data && data.length === 0 && !error && <p className="notice">{empty}</p>}
      {data && data.length > 0 && children}
    </section>
  )
}

function mergeCirculars(documents = [], queue = []) {
  const rows = new Map(documents.map((item) => [
    item.documentVersionId,
    {
      ...item,
      status: item.processingStatus === 'FAILED' && item.eventStatus === 'DEAD_LETTERED'
        ? 'DEAD_LETTERED' : item.processingStatus,
    },
  ]))
  for (const item of queue) {
    const existing = rows.get(item.id)
    if (['COMPLETED', 'PROCESSING'].includes(existing?.status)) continue
    rows.set(item.id, {
      ...existing,
      documentVersionId: item.id,
      title: item.title,
      regulator: item.regulator,
      createdAt: existing?.createdAt ?? item.queuedAt,
      status: item.published ? 'QUEUED' : 'WAITING_TO_PUBLISH',
      processingError: null,
      publicationError: item.publicationError,
    })
  }
  return [...rows.values()].sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt))
}

export default function App() {
  const [tick, setTick] = useState(0)
  const [updated, setUpdated] = useState(null)
  const [documentVersion, setDocumentVersion] = useState(null)
  const [reviewStatus, setReviewStatus] = useState('')
  const [openFinding, setOpenFinding] = useState(null)
  const [scanning, setScanning] = useState(null)
  const [scanMessage, setScanMessage] = useState(null)

  const refresh = useCallback(() => {
    setTick((value) => value + 1)
    setUpdated(new Date())
  }, [])

  useEffect(() => {
    const timer = setInterval(refresh, REFRESH_SECONDS * 1000)
    return () => clearInterval(timer)
  }, [refresh])

  const sources = useResource(api.sources, tick)
  const orderedSources = sources.data?.toSorted((a, b) => Number(b.id === 'rbi') - Number(a.id === 'rbi'))
  const documents = useResource(api.documents, tick)
  const processing = useResource(api.processing, tick)
  const queue = useResource(api.queue, tick)
  const obligations = useResource(api.obligations, tick)
  const findings = useResource(api.findings, tick)

  const inDocument = (item) => !documentVersion || item.documentVersionId === documentVersion
  const shownObligations = obligations.data?.filter(inDocument) ?? null
  const scopedFindings = findings.data?.filter(inDocument) ?? null
  const shownFindings = scopedFindings?.filter((item) => !reviewStatus || item.status === reviewStatus) ?? null
  const circulars = mergeCirculars(documents.data ?? [], queue.data ?? [])
  const selected = circulars.find((item) => item.documentVersionId === documentVersion)
  const pending = scopedFindings?.filter((item) => item.status === 'PENDING_REVIEW').length
  const pipelineState = {
    data: circulars.length || (documents.data && queue.data) ? circulars : null,
    loading: documents.loading || queue.loading,
    error: [documents.error && `Processing results: ${documents.error}`, queue.error && `Pending queue: ${queue.error}`]
      .filter(Boolean).join(' '),
  }

  function selectCircular(id) {
    setDocumentVersion(id)
    setOpenFinding(null)
    setReviewStatus('')
    if (id) document.getElementById('circular-results')?.scrollIntoView({ block: 'start' })
  }

  async function scan(source) {
    setScanning(source.id)
    setScanMessage(null)
    try {
      const result = await api.scan(source.id)
      setScanMessage({
        tone: result.lastRunStatus === 'FAILED' ? 'bad' : 'good',
        text: `${source.name}: ${label(result.lastRunStatus).toLowerCase()}, ${result.lastNewDocuments} new of `
          + `${result.lastDiscovered} found.${result.lastError ? ` ${result.lastError}` : ''}`,
      })
    } catch (error) {
      setScanMessage({ tone: 'bad', text: `${source.name}: ${error.message}` })
    } finally {
      setScanning(null)
      refresh()
    }
  }

  return (
    <div className="page">
      <header className="masthead">
        <div>
          <h1>ClauseIQ</h1>
          <p>From a regulator's circular to a reviewed compliance finding, one stage at a time.</p>
        </div>
        <div className="refresh">
          <button type="button" className="button" onClick={refresh}>Refresh</button>
          <span>
            {updated ? `Updated ${updated.toLocaleTimeString()}` : 'Live'}, every {REFRESH_SECONDS} seconds
          </span>
        </div>
      </header>

      <main className="stages">
        <Stage
          number={1}
          title="Scan regulator sources"
          does="The scanner checks each regulator's listing page, downloads new circulars to MinIO and publishes a Kafka event for each."
          count={sources.data ? plural(sources.data.length, 'source') : null}
          state={sources}
          empty="No sources are configured in the scanner."
        >
          {scanMessage && <p className={`notice notice-${scanMessage.tone}`} role="status">{scanMessage.text}</p>}
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Source</th><th>Last scan</th><th>Result</th>
                  <th className="number">Found</th><th className="number">New</th><th><span className="sr-only">Action</span></th>
                </tr>
              </thead>
              <tbody>
                {orderedSources?.map((source) => (
                  <tr key={source.id}>
                    <td>
                      <strong>{source.name}</strong>
                      <span className="sub">
                        {source.regulator}{source.enabled ? '' : ', disabled'}
                        {source.listingUrl?.startsWith('https://') && (
                          <>, <a href={source.listingUrl} target="_blank" rel="noreferrer">listing</a></>
                        )}
                      </span>
                    </td>
                    <td>{when(source.lastRunAt)}</td>
                    <td>
                      <Status value={source.lastRunStatus} />
                      {source.lastError && <span className="sub">{source.lastError}</span>}
                    </td>
                    <td className="number">{source.lastDiscovered}</td>
                    <td className="number">{source.lastNewDocuments}</td>
                    <td className="action">
                      <button
                        type="button"
                        className="button"
                        disabled={!source.enabled || scanning !== null}
                        onClick={() => scan(source)}
                      >
                        {scanning === source.id ? 'Scanning…' : source.id === 'rbi' ? 'Scan RBI' : 'Scan now'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Stage>

        <Stage
          number={2}
          title="Read each circular"
          does="The ingestion worker takes one event at a time, fetches the PDF and extracts its text page by page."
          count={pipelineState.data ? plural(circulars.length, 'circular') : null}
          state={pipelineState}
          empty="No circulars yet. Scan a regulator or upload a PDF."
          controls={<ProcessingControls processing={processing} refresh={refresh} />}
        >
          <CircularList items={circulars} selectedId={documentVersion} select={selectCircular} when={when} />
        </Stage>

        <div id="circular-results" className={documentVersion ? 'selected-circular' : undefined}>
          {documentVersion && <>
            <div>
              <strong>{selected?.title ?? 'Selected circular'}</strong>
              {selected && <span className="sub">{selected.regulator} ? <Status value={selected.status} /></span>}
              {(selected?.publicationError || (['FAILED', 'DEAD_LETTERED'].includes(selected?.status) && selected?.processingError)) &&
                <span className="sub circular-error">{selected.publicationError ?? selected.processingError}</span>}
              {!selected && <span className="sub">This circular is no longer in the queue or processing results.</span>}
            </div>
            <button type="button" className="button" onClick={() => selectCircular(null)}>Show all circulars</button>
          </>}
        </div>

        <Stage
          number={3}
          title="Extract obligations with citations"
          does="The model lists what the circular requires. An obligation is kept only if its quote is found word for word on the cited page."
          count={shownObligations ? plural(shownObligations.length, 'obligation') : null}
          state={{ ...obligations, data: shownObligations }}
          empty={resultsEmpty(selected, documentVersion, 'No obligations were extracted.', 'No obligations have been extracted yet.')}
        >
          <ol className="obligations">
            {shownObligations?.map((item) => (
              <li key={item.id}>
                <div className="reference">
                  <span>{item.citation.clauseNumber ? `Clause ${item.citation.clauseNumber}` : 'No clause number'}</span>
                  <span>Page {item.citation.pageNumber}</span>
                </div>
                <div>
                  <blockquote>{item.citation.quotedText}</blockquote>
                  <p className="summary">{item.summary}</p>
                  <p className="sub">
                    {!documentVersion && `${item.documentTitle}. `}
                    {item.deadline ? `Deadline: ${item.deadline}. ` : ''}
                    Confidence {Math.round(item.confidence * 100)}%.
                  </p>
                </div>
              </li>
            ))}
          </ol>
        </Stage>

        <Stage
          number={4}
          title="Compare with policies and controls"
          does="Each obligation is checked against the policy handbook and control register. Covered means the documents cover it, not that it is done in practice."
          count={shownObligations ? coverageCount(shownObligations) : null}
          state={{ ...obligations, data: shownObligations }}
          empty={resultsEmpty(selected, documentVersion, 'No obligations were available for comparison.', 'Nothing has been compared yet.')}
        >
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Obligation</th><th>Coverage</th><th>Why</th></tr>
              </thead>
              <tbody>
                {shownObligations?.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <strong>{item.citation.clauseNumber ? `Clause ${item.citation.clauseNumber}` : `Page ${item.citation.pageNumber}`}</strong>
                      <span className="sub">{item.summary}</span>
                    </td>
                    <td><Status value={item.coverageStatus} /></td>
                    <td className="wide">{item.coverageExplanation ?? 'Not assessed yet.'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Stage>

        <Stage
          number={5}
          title="Review findings"
          does="Every gap becomes a finding with a drafted fix and an owner. Nothing is final until a reviewer accepts, edits or rejects it."
          count={scopedFindings ? `${plural(scopedFindings.length, 'finding')}, ${pending} pending` : null}
          state={{ ...findings, data: shownFindings }}
          empty={reviewStatus && scopedFindings?.length ? 'No findings match the selected review status.'
            : resultsEmpty(selected, documentVersion, 'Processing completed without findings.', 'No findings are available yet.')}
          controls={scopedFindings?.length > 0 && <div className="dashboard-filters">
            <label>Review status<select value={reviewStatus} onChange={(event) => setReviewStatus(event.target.value)}>
              <option value="">All review statuses</option>
              {['PENDING_REVIEW', 'APPROVED', 'APPROVED_WITH_CHANGES', 'REJECTED'].map((status) =>
                <option key={status} value={status}>{label(status)}</option>)}
            </select></label>
          </div>}
        >
          <ul className="findings">
            {shownFindings?.map((item) => {
              const open = openFinding === item.id
              return (
                <li key={item.id} className={open ? 'open' : ''}>
                  <button
                    type="button"
                    className="finding-row"
                    aria-expanded={open}
                    onClick={() => setOpenFinding(open ? null : item.id)}
                  >
                    <Status value={item.severity} />
                    <span className="finding-title">
                      <strong>{item.title}</strong>
                      <span className="sub">
                        {label(item.findingType)}
                        {item.clauseNumber ? `, clause ${item.clauseNumber}` : ''}
                        {item.assignedRole ? `, assigned to ${item.assignedRole}` : ''}
                      </span>
                    </span>
                    <Status value={item.status} />
                    <span className="chevron" aria-hidden="true">{open ? '−' : '+'}</span>
                  </button>
                  {open && <FindingReview id={item.id} onDecided={refresh} />}
                </li>
              )
            })}
          </ul>
        </Stage>
      </main>
    </div>
  )
}

function resultsEmpty(selected, selectedId, completed, general) {
  if (!selectedId) return general
  if (!selected) return 'Results are unavailable for this circular.'
  if (selected.status === 'COMPLETED') return completed
  if (['FAILED', 'DEAD_LETTERED'].includes(selected.status)) return 'Processing failed before results were available.'
  if (selected.status === 'PROCESSING') return 'Processing is underway. Results will appear here when it completes.'
  return 'Waiting for the worker to start processing this circular.'
}

function plural(count, noun) {
  return `${count} ${noun}${count === 1 ? '' : 's'}`
}

function coverageCount(obligations) {
  const covered = obligations.filter((item) => item.coverageStatus === 'COVERED').length
  return `${covered} of ${obligations.length} covered`
}
