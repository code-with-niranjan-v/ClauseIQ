import { useCallback, useEffect, useState } from 'react'
import { api } from './api.js'
import FindingReview from './FindingReview.jsx'
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

function Stage({ number, title, does, count, state, empty, children }) {
  const { data, error, loading } = state
  return (
    <section className="stage" aria-labelledby={`stage-${number}`}>
      <div className="stage-marker" aria-hidden="true">{number}</div>
      <header className="stage-header">
        <h2 id={`stage-${number}`}>{title}</h2>
        {count != null && <span className="stage-count">{count}</span>}
        <p>{does}</p>
      </header>
      {error && <p className="notice notice-bad" role="alert">{error}</p>}
      {loading && !data && <p className="notice">Loading…</p>}
      {data && data.length === 0 && !error && <p className="notice">{empty}</p>}
      {data && data.length > 0 && children}
    </section>
  )
}

export default function App() {
  const [tick, setTick] = useState(0)
  const [updated, setUpdated] = useState(null)
  const [documentVersion, setDocumentVersion] = useState(null)
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
  const documents = useResource(api.documents, tick)
  const obligations = useResource(api.obligations, tick)
  const findings = useResource(api.findings, tick)

  const inDocument = (item) => !documentVersion || item.documentVersionId === documentVersion
  const shownObligations = obligations.data?.filter(inDocument) ?? null
  const shownFindings = findings.data?.filter(inDocument) ?? null
  const selected = documents.data?.find((item) => item.documentVersionId === documentVersion)
  const pending = shownFindings?.filter((item) => item.status === 'PENDING_REVIEW').length

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

      {selected && (
        <p className="filter">
          Showing stages 3 to 5 for <strong>{selected.title}</strong>.{' '}
          <button type="button" className="link" onClick={() => setDocumentVersion(null)}>Show all documents</button>
        </p>
      )}

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
                {sources.data?.map((source) => (
                  <tr key={source.id}>
                    <td>
                      <strong>{source.name}</strong>
                      <span className="sub">{source.regulator}{source.enabled ? '' : ', disabled'}</span>
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
                        {scanning === source.id ? 'Scanning…' : 'Scan now'}
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
          count={documents.data ? plural(documents.data.length, 'document') : null}
          state={documents}
          empty="No circular has reached the worker yet. Run a scan in stage 1."
        >
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Circular</th><th>Processing</th><th className="number">Pages</th>
                  <th className="number">Obligations</th><th className="number">Findings</th>
                  <th><span className="sr-only">Filter</span></th>
                </tr>
              </thead>
              <tbody>
                {documents.data?.map((item) => (
                  <tr key={item.documentVersionId} className={item.documentVersionId === documentVersion ? 'selected' : ''}>
                    <td>
                      <strong>{item.title || 'Untitled circular'}</strong>
                      <span className="sub">
                        {item.regulator}, received {when(item.createdAt)}
                        {item.sourceUrl?.startsWith('http') && (
                          <>, <a href={item.sourceUrl} target="_blank" rel="noreferrer">source</a></>
                        )}
                      </span>
                    </td>
                    <td><Status value={item.processingStatus} /></td>
                    <td className="number">{item.pageCount ?? ''}</td>
                    <td className="number">{item.obligationCount ?? ''}</td>
                    <td className="number">
                      {item.findingCount}
                      {item.pendingFindingCount > 0 && <span className="sub">{item.pendingFindingCount} pending</span>}
                    </td>
                    <td className="action">
                      <button
                        type="button"
                        className="link"
                        onClick={() => setDocumentVersion(
                          item.documentVersionId === documentVersion ? null : item.documentVersionId)}
                      >
                        {item.documentVersionId === documentVersion ? 'Show all' : 'Show only this'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Stage>

        <Stage
          number={3}
          title="Extract obligations with citations"
          does="The model lists what the circular requires. An obligation is kept only if its quote is found word for word on the cited page."
          count={shownObligations ? plural(shownObligations.length, 'obligation') : null}
          state={{ ...obligations, data: shownObligations }}
          empty="No obligations have been extracted yet."
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
          empty="Nothing has been compared yet."
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
          count={shownFindings ? `${plural(shownFindings.length, 'finding')}, ${pending} pending` : null}
          state={{ ...findings, data: shownFindings }}
          empty="No gaps were found, so there is nothing to review."
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

function plural(count, noun) {
  return `${count} ${noun}${count === 1 ? '' : 's'}`
}

function coverageCount(obligations) {
  const covered = obligations.filter((item) => item.coverageStatus === 'COVERED').length
  return `${covered} of ${obligations.length} covered`
}
