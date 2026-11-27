import { Fragment, useEffect, useState } from 'react'
import { api } from '../../api.js'
import { useAuth } from '../../authContext.js'
import { Heading, Table, Tag } from '../components.jsx'
import { wordDiff } from '../diff.js'
import { date, title } from '../format.js'

const relationText = {
  SUPERSEDES: 'supersedes', WITHDRAWS: 'withdraws', AMENDS: 'amends', REFERS_TO: 'refers to',
}

function Circular({ item }) {
  const label = `${item.regulator}: ${item.title}`
  return /^https?:\/\//i.test(item.sourceUrl ?? '')
    ? <a className="text-action" href={item.sourceUrl} target="_blank" rel="noreferrer">{label}</a> : label
}

function Words({ before, after }) {
  return <span className="cc-words">{wordDiff(before, after).map((part, index) =>
    part.type === 'same' ? <span key={index}>{part.text}</span>
      : part.type === 'add' ? <ins key={index}>{part.text}</ins> : <del key={index}>{part.text}</del>)}</span>
}

function Diff({ link }) {
  const [diff, setDiff] = useState(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    api.linkDiff(link.id).then((value) => { if (active) setDiff(value) }, (failure) => { if (active) setError(failure.message) })
    return () => { active = false }
  }, [link.id])
  if (error) return <p className="sa-error">{error}</p>
  if (!diff) return <p className="workbench-empty">Comparing obligations…</p>
  if (!diff.available) return <p className="workbench-empty">{diff.message}</p>
  const { counts, changes } = diff
  return <div className="cc-diff">
    <p className="muted">Obligations of the earlier circular (before) paired with the new one (after) by meaning.
      {' '}{counts.NEW} new · {counts.MODIFIED} modified · {counts.REMOVED} no longer stated · {counts.UNCHANGED} unchanged</p>
    <Table headers={['Change', 'Before', 'After']}>{changes.filter((item) => item.change !== 'UNCHANGED').map((item, index) =>
      <tr key={index}><td><span className={`cc-change ${item.change}`}>{title(item.change)}</span></td>
        <td className="sa-wrap">{item.before ? item.before.summary : '—'}</td>
        <td className="sa-wrap">{item.change === 'MODIFIED' ? <Words before={item.before.summary} after={item.after.summary} />
          : item.after ? item.after.summary : '—'}</td></tr>)}</Table>
  </div>
}

export default function CircularChanges({ onChanged }) {
  const user = useAuth()
  const [links, setLinks] = useState(null)
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState('')
  const [open, setOpen] = useState(null)
  const [revision, setRevision] = useState(0)

  useEffect(() => {
    let active = true
    api.circularLinks().then((items) => { if (active) setLinks(items) }, (error) => { if (active) setMessage(error.message) })
    return () => { active = false }
  }, [revision])

  async function act(key, operation, done) {
    setBusy(key)
    setMessage('')
    try {
      setMessage(done(await operation()))
      setRevision((value) => value + 1)
      onChanged?.()
    } catch (error) { setMessage(error.message) } finally { setBusy('') }
  }

  const list = links ?? []
  const proposed = list.filter((item) => item.status === 'PROPOSED')
  return <><Heading name="Circular changes" description="Supersessions, withdrawals and amendments detected in circular text. Confirmed supersessions retire the earlier circular's obligations.">
    {user.can.review && <button className="btn" disabled={!!busy} onClick={() => act('refresh', api.refreshLineage,
      (result) => `Checked ${result.circulars} circulars: ${result.links} references to other circulars found.`)}>
      {busy === 'refresh' ? 'Checking…' : 'Re-detect changes'}</button>}</Heading>
    {message && <p className="cc-msg" role="status">{message}</p>}
    <div className="rib sa-rib">{[['Awaiting confirmation', proposed.length],
      ['Supersessions and withdrawals', list.filter((item) => item.retires && item.status !== 'DISMISSED').length],
      ['Amendments', list.filter((item) => item.relation === 'AMENDS' && item.status !== 'DISMISSED').length],
      ['Citing circulars not ingested', list.filter((item) => !item.target && item.status !== 'DISMISSED').length],
      ['Confirmed', list.filter((item) => item.status === 'CONFIRMED').length],
      ['Obligations retired', list.reduce((sum, item) => sum + (item.retiredObligations || 0), 0)]].map(([label, value]) =>
      <div key={label}><small>{label}</small><b>{value}</b></div>)}</div>
    <div className="sec"><Table headers={['Status', 'Change', 'Evidence', 'Action']} empty={links ? 'No changes detected yet. Re-detect after ingesting circulars.' : 'Loading…'}>
      {list.map((link) => <Fragment key={link.id}>
        <tr>
          <td><Tag>{title(link.status)}</Tag>{link.decidedBy && <div className="muted">{link.decidedBy} · {date(link.decidedAt)}</div>}</td>
          <td className="sa-wrap"><Circular item={link.source} /> <b className={`cc-rel ${link.relation}`}>{relationText[link.relation]}</b>{' '}
            {link.target ? <Circular item={link.target} /> : <span className="mono">{link.citedIdentifier}</span>}
            {!link.target && <div className="muted">The cited circular has not been ingested.</div>}
            {link.target && link.retires && link.status === 'PROPOSED' && <div className="muted">Confirming retires its {link.target.activeObligations} active obligations and closes their pending findings.</div>}
            {link.status === 'CONFIRMED' && link.retiredObligations > 0 && <div className="muted">{link.retiredObligations} obligations retired.</div>}</td>
          <td className="sa-wrap"><q className="sa-quote">{link.evidence}</q><span className="muted">{link.pageNumber ? `Page ${link.pageNumber}` : ''}</span></td>
          <td className="cc-actions">
            {link.target && <button className="btn" onClick={() => setOpen(open === link.id ? null : link.id)} aria-expanded={open === link.id}>What changed</button>}
            {link.status === 'PROPOSED' && user.can.review && <>
              <button className="btn p" disabled={!!busy} onClick={() => act(link.id, () => api.decideLink(link.id, true),
                (result) => result.retiredObligations ? `Confirmed. ${result.retiredObligations} obligations retired.` : 'Confirmed.')}>Confirm</button>
              <button className="btn" disabled={!!busy} onClick={() => act(link.id, () => api.decideLink(link.id, false), () => 'Dismissed.')}>Dismiss</button></>}
          </td>
        </tr>
        {open === link.id && <tr className="sa-more"><td colSpan="4"><Diff link={link} /></td></tr>}
      </Fragment>)}</Table></div>
  </>
}
