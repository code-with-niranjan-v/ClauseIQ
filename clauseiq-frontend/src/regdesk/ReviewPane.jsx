import { useEffect, useState } from 'react'
import { api } from '../api.js'

export default function ReviewPane({ finding, roles, onSaved }) {
  const { id, obligation, recommendation } = finding
  const citation = obligation.citation
  const [reviewer, setReviewer] = useState(() => localStorage.getItem('regdesk-reviewer') || '')
  const [mode, setMode] = useState('')
  const [comment, setComment] = useState('')
  const [title, setTitle] = useState(finding.title)
  const [draft, setDraft] = useState(recommendation?.draftPolicyText ?? '')
  const [owner, setOwner] = useState(recommendation?.assignedRole ?? '')
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const pending = finding.status === 'PENDING_REVIEW'
  const level = finding.severity.toLowerCase().replace(/^./, (c) => c.toUpperCase())
  const confidence = Math.round(finding.confidence * 100)
  const status = pending ? 'pending sign-off' : finding.status.toLowerCase().replaceAll('_', ' ')

  useEffect(() => {
    if (!pending || busy) return
    function shortcut(event) {
      if (event.ctrlKey || event.metaKey || event.altKey || event.target.closest('input,textarea,select,[contenteditable],.slide') || document.querySelector('.slide')) return
      if (['a', 'e', 'r'].includes(event.key)) setMode({ a: 'approve', e: 'edit', r: 'reject' }[event.key])
    }
    window.addEventListener('keydown', shortcut)
    return () => window.removeEventListener('keydown', shortcut)
  }, [pending, busy])

  async function submit(event) {
    event.preventDefault()
    if (!reviewer.trim() || (mode === 'reject' && !comment.trim())) return
    const body = { reviewer: reviewer.trim(), comment: comment.trim() }
    setBusy(true)
    setNotice('')
    try {
      if (mode === 'edit') {
        if (title.trim() !== finding.title) body.title = title.trim()
        if (recommendation && draft.trim() !== (recommendation.draftPolicyText ?? '')) body.draftPolicyText = draft.trim()
        if (recommendation && owner !== (recommendation.assignedRole ?? '')) body.assignedRole = owner
        if (Object.keys(body).length === 2) { setNotice('Change the wording, draft or owner before submitting.'); return }
        await api.editAndApprove(id, body)
      } else if (mode === 'reject') await api.reject(id, body)
      else await api.approve(id, body)
      localStorage.setItem('regdesk-reviewer', body.reviewer)
      setMode('')
      setComment('')
      setNotice('Decision recorded.')
      onSaved()
    } catch (error) {
      setNotice(error.message)
    } finally {
      setBusy(false)
    }
  }

  const policy = finding.policySection || finding.policies.map((item) => item.heading || item.sectionNumber).join(', ')
  const controls = finding.controls.map((item) => item.name).join(', ')
  const ref = [obligation.regulator, citation?.clauseNumber].filter(Boolean).join(' ')
  return <>
    <header className="review-heading">
      <div className="review-heading-status"><span className={`review-status ${pending ? 'pending' : finding.status === 'REJECTED' ? 'rejected' : 'approved'}`}>{status}</span>
        <span className={`tag ${level}`}>{level}</span><span className="cl" title={id}>{id.slice(0, 8)}</span></div>
      <h1>{finding.title}</h1>
      <p>{obligation.summary}</p>
    </header>
    <div className="doc"><div className="paper">
      <h4>{obligation.regulator} · {obligation.documentTitle}{citation ? ` · PAGE ${citation.pageNumber}` : ''}</h4>
      <p className="hit"><span className="no">{citation?.clauseNumber || '—'}</span>{citation?.quotedText || 'No source quote available.'}
        <br /><span className="anno">▲ obligation {obligation.id} · confidence {Math.round(obligation.confidence * 100)}%</span></p>
    </div></div>
    <section className="insp sec" aria-label="Finding inspector">
      <div className="sh">Finding details</div>
      <div className="ib"><dl>
        <dt>Cited</dt><dd className="cl">{ref}{citation && `, p.${citation.pageNumber}`}</dd>
        <dt>Confidence</dt><dd><span className={`cf ${confidence < 80 ? 'lo' : ''}`}><i><b style={{ width: `${confidence}%` }} /></i>{confidence}</span></dd>
        <dt>Owner</dt><dd>{recommendation?.assignedRole || '—'}</dd>
        <dt>Deadline</dt><dd className="mono">{obligation.deadline || recommendation?.suggestedDeadline || '—'}</dd>
      </dl></div>
      <div className="sh">Mapping</div>
      <div className="ib"><div className="map"><span>{ref || 'Citation'}</span><i /><span className={policy ? '' : 'x'}>{policy || 'No policy match'}</span></div>
        <div className="map"><span className={controls ? '' : 'x'}>{controls || 'No control match'}</span></div>
        {finding.explanation && <p className="muted">{finding.explanation}</p>}</div>
      {recommendation && <><div className="sh">Drafted change</div><div className="ib"><div className="diff">
        {finding.policyQuote && <div className="r">− {finding.policyQuote}</div>}
        <div className="a">+ {recommendation.draftPolicyText}</div>
      </div></div></>}
      {notice && <p className="ib" role="status">{notice}</p>}
      {pending && (mode ? <form onSubmit={submit}>
        <div className="ib review-fields">
          <label>Reviewer<input className="f" value={reviewer} onChange={(event) => setReviewer(event.target.value)} required autoFocus /></label>
          <label>{mode === 'reject' ? 'Reason for rejection' : 'Comment'}<textarea className="f" value={comment} onChange={(event) => setComment(event.target.value)} required={mode === 'reject'} /></label>
          {mode === 'edit' && <>
            <label className="review-field-wide">Finding wording<textarea className="f" value={title} required onChange={(event) => setTitle(event.target.value)} /></label>
            {recommendation && <><label className="review-field-wide">Draft policy<textarea className="f" rows={4} value={draft} required onChange={(event) => setDraft(event.target.value)} /></label>
              <label>Owner<select className="f" value={owner} onChange={(event) => setOwner(event.target.value)}>
                <option value="" disabled>Choose a role</option>{[...new Set([owner, ...roles].filter(Boolean))].map((role) =>
                  <option key={role}>{role}</option>)}</select></label></>}
          </>}
        </div>
        <div className="dec"><button className="btn p" disabled={busy}>{mode === 'edit' ? 'Save & approve' : mode === 'reject' ? 'Confirm rejection' : 'Confirm approval'}</button>
          <button type="button" className="btn" disabled={busy} onClick={() => setMode('')}>Cancel</button></div>
      </form> : <div className="dec">
        <button className="btn p" onClick={() => setMode('approve')}>Approve <kbd>A</kbd></button>
        <button className="btn" onClick={() => setMode('edit')}>Edit <kbd>E</kbd></button>
        <button className="btn" onClick={() => setMode('reject')}>Reject <kbd>R</kbd></button>
      </div>)}
    </section>
  </>
}
