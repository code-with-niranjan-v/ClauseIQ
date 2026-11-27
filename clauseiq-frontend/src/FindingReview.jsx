import { useEffect, useState } from 'react'
import { api } from './api.js'
import { label } from './labels.js'
import Status from './Status.jsx'

const REVIEWER_KEY = 'clauseiq.reviewer'

function savedReviewer() {
  try {
    return localStorage.getItem(REVIEWER_KEY) ?? ''
  } catch {
    return ''
  }
}

export default function FindingReview({ id, onDecided }) {
  const [finding, setFinding] = useState(null)
  const [roles, setRoles] = useState([])
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [reviewer, setReviewer] = useState(savedReviewer)
  const [comment, setComment] = useState('')
  const [draft, setDraft] = useState('')
  const [action, setAction] = useState('')
  const [role, setRole] = useState('')

  function show(detail) {
    setFinding(detail)
    setDraft(detail.recommendation?.draftPolicyText ?? '')
    setAction(detail.recommendation?.recommendedAction ?? '')
    setRole(detail.recommendation?.assignedRole ?? '')
  }

  useEffect(() => {
    let current = true
    Promise.all([api.finding(id), api.roles()])
      .then(([detail, roleList]) => {
        if (!current) return
        show(detail)
        setRoles(roleList)
      })
      .catch((failure) => current && setError(failure.message))
    return () => {
      current = false
    }
  }, [id])

  if (error && !finding) return <p className="notice notice-bad" role="alert">{error}</p>
  if (!finding) return <p className="notice">Loading…</p>

  const recommendation = finding.recommendation
  const obligation = finding.obligation
  const pending = finding.status === 'PENDING_REVIEW'
  const edits = {}
  if (recommendation) {
    if (draft.trim() !== recommendation.draftPolicyText) edits.draftPolicyText = draft
    if (action.trim() !== recommendation.recommendedAction) edits.recommendedAction = action
    if (role !== recommendation.assignedRole) edits.assignedRole = role
  }
  const edited = Object.keys(edits).length > 0

  async function decide(send) {
    if (!reviewer.trim()) {
      setError('Enter your name before you record a decision.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      localStorage.setItem(REVIEWER_KEY, reviewer.trim())
    } catch {
      // The name is only remembered as a convenience.
    }
    try {
      show(await send({ reviewer: reviewer.trim(), comment: comment.trim() || undefined }))
      setComment('')
      onDecided()
    } catch (failure) {
      setError(failure.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="review">
      <p className="explanation">{finding.explanation}</p>

      <div className="evidence">
        <section>
          <h3>What the circular requires</h3>
          {obligation && (
            <>
              <blockquote>{obligation.citation.quotedText}</blockquote>
              <p className="sub">
                {obligation.documentTitle}, page {obligation.citation.pageNumber}
                {obligation.citation.clauseNumber ? `, clause ${obligation.citation.clauseNumber}` : ''}
              </p>
            </>
          )}
        </section>
        <section>
          <h3>What our policy says</h3>
          {finding.policies.length === 0 && <p>No policy section addresses this obligation.</p>}
          {finding.policies.map((policy) => (
            <div key={policy.sectionNumber} className="policy">
              <blockquote>{finding.policyQuote && policy.sectionNumber === finding.policySection
                ? finding.policyQuote : policy.content}</blockquote>
              <p className="sub">Handbook section {policy.sectionNumber}, {policy.heading}</p>
            </div>
          ))}
          <h3>Controls</h3>
          {finding.controls.length === 0 && <p>No control operates this obligation.</p>}
          <ul className="controls">
            {finding.controls.map((control) => (
              <li key={control.id}>
                <strong>{control.id}</strong> {control.name}
                <span className="sub">
                  {control.ownerRole ? `Owned by ${control.ownerRole}` : 'No owner'}
                  {control.frequency ? `, ${control.frequency.toLowerCase()}` : ''}
                </span>
              </li>
            ))}
          </ul>
        </section>
      </div>

      {recommendation && (
        <section className="draft">
          <h3>Drafted fix</h3>
          <p className="sub">
            Written by the model. Coverage: {label(finding.coverageStatus).toLowerCase()}.
            {recommendation.suggestedDeadline ? ` Suggested deadline: ${recommendation.suggestedDeadline}.` : ''}
          </p>
          <label>
            Proposed policy wording
            <textarea rows={3} value={draft} disabled={!pending || busy} onChange={(event) => setDraft(event.target.value)} />
          </label>
          <label>
            Recommended action
            <textarea rows={2} value={action} disabled={!pending || busy} onChange={(event) => setAction(event.target.value)} />
          </label>
          <label>
            Assigned role
            <select value={role} disabled={!pending || busy} onChange={(event) => setRole(event.target.value)}>
              {!roles.includes(role) && <option value={role}>{role}</option>}
              {roles.map((name) => <option key={name} value={name}>{name}</option>)}
            </select>
          </label>
          {recommendation.requiredEvidence?.length > 0 && (
            <p className="sub">Evidence to ask for: {recommendation.requiredEvidence.join('; ')}.</p>
          )}
        </section>
      )}

      {pending ? (
        <section className="decision">
          <h3>Your decision</h3>
          <div className="decision-fields">
            <label>
              Your name
              <input type="text" value={reviewer} disabled={busy} onChange={(event) => setReviewer(event.target.value)} />
            </label>
            <label>
              Comment (needed to reject)
              <input type="text" value={comment} disabled={busy} onChange={(event) => setComment(event.target.value)} />
            </label>
          </div>
          {error && <p className="notice notice-bad" role="alert">{error}</p>}
          <div className="buttons">
            {edited ? (
              <button
                type="button"
                className="button button-primary"
                disabled={busy}
                onClick={() => decide((body) => api.editAndApprove(id, { ...body, ...edits }))}
              >
                Approve with my edits
              </button>
            ) : (
              <button
                type="button"
                className="button button-primary"
                disabled={busy}
                onClick={() => decide((body) => api.approve(id, body))}
              >
                Approve
              </button>
            )}
            <button
              type="button"
              className="button button-danger"
              disabled={busy}
              onClick={() => {
                if (!comment.trim()) {
                  setError('Add a comment that says why you are rejecting this finding.')
                  return
                }
                decide((body) => api.reject(id, body))
              }}
            >
              Reject
            </button>
            {edited && (
              <button type="button" className="link" disabled={busy} onClick={() => show(finding)}>Undo my edits</button>
            )}
          </div>
        </section>
      ) : (
        <section className="decision">
          <h3>Decision</h3>
          {finding.decisions.map((decision) => (
            <p key={decision.id}>
              <Status value={decision.decision} /> by {decision.reviewer} on{' '}
              {new Date(decision.decidedAt).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}
              {decision.comment ? `. “${decision.comment}”` : '.'}
              {decision.editedValue && ` Changed: ${Object.keys(decision.editedValue).map(fieldName).join(', ')}.`}
            </p>
          ))}
        </section>
      )}
    </div>
  )
}

function fieldName(key) {
  return {
    draftPolicyText: 'policy wording',
    recommendedAction: 'recommended action',
    assignedRole: 'assigned role',
    suggestedDeadline: 'deadline',
    requiredEvidence: 'evidence',
    title: 'title',
    severity: 'severity',
  }[key] ?? key
}
