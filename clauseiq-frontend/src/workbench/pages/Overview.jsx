import { Fragment, useState } from 'react'
import { reportUrl } from '../../api.js'
import { Confidence, Heading, Table, Tag } from '../components.jsx'
import { colors, date, day, isoDate, pending, percent, severities, severity, title } from '../format.js'

export default function Overview({ documents, obligations, findings, details, audit, sources, open, navigate }) {
  const [now] = useState(Date.now)
  const end = now + 154 * day
  const gaps = findings.filter((item) => !['REJECTED', 'SUPERSEDED'].includes(item.status))
  const dated = gaps.map((item) => ({ ...item, due: details[item.id]?.obligation.deadline }))
    .filter((item) => isoDate(item.due)).sort((a, b) => a.due.localeCompare(b.due))
  const owners = [...new Set(dated.map((item) => item.assignedRole || 'Unassigned'))]
  const regulators = [...new Set([...sources, ...obligations].map((item) => item.regulator))]
  const awaiting = findings.filter(pending).length
  const deadline = dated[0]
  const stats = [['Circulars', documents.length], ['Obligations', obligations.length], ['Open gaps', gaps.length],
    ['Critical', gaps.filter((item) => severity(item) === 'Critical').length, 'var(--c)'],
    ['Mean confidence', obligations.length
      ? `${percent(obligations.reduce((sum, item) => sum + item.confidence, 0) / obligations.length)}%` : '—']]
  return <><Heading name="Overview" description={`Regulatory change position as of ${new Date(now).toLocaleDateString('en-GB')}`}>
    <a className="btn" href={reportUrl.posture('pdf')} download>Board report PDF</a>
    <a className="btn" href={reportUrl.posture('docx')} download>Word</a>
    <button className="btn" onClick={() => navigate(1)}>Ingest circular</button><button className="btn p" onClick={() => navigate(2)}>Start review</button></Heading>
    <div className="overview-priorities">
      <section className="priority priority-review">
        <h2>Awaiting sign-off</h2>
        <strong>{awaiting}</strong>
        <p>{awaiting === 1 ? 'Finding awaiting a decision' : 'Findings awaiting a decision'}</p>
      </section>
      <section className="priority">
        <h2>Next deadline</h2>
        <strong>{date(deadline?.due)}</strong>
        {deadline ? <button className="text-action" onClick={() => open(deadline.id)}>{deadline.title}</button>
          : <p>No open findings with a calendar deadline.</p>}
      </section>
    </div>
    <div className="rib">{stats.map(([label, value, color]) => <div key={label}><small>{label}</small><b style={{ color }}>{value}</b></div>)}</div>
    <div className="cols"><div className="sec"><div className="sh">Deadline runway <span>gaps by owner · to {date(end)}</span>
      <span className="r mono">{severities.slice(0, 4).map((level, i) => <Fragment key={level}><i className="d" style={{ background: colors[i], marginLeft: 8 }} />{level}</Fragment>)}</span></div>
      <div className="tl"><div className="axis">{[0, 38, 77, 115, 154].map((offset) => <span key={offset}>{date(now + offset * day)}</span>)}</div>
        {owners.length > 0 && <div className="today" />}
        {owners.map((owner) => <div className="lane" key={owner}><span title={owner}>{owner}</span><div>{dated.filter((item) => (item.assignedRole || 'Unassigned') === owner).map((item) =>
          <button key={item.id} className="mk" title={`${item.title} · ${date(item.due)}`} aria-label={item.title}
            style={{ left: `calc(${Math.max(1, Math.min(97, (Date.parse(item.due) - now) / (end - now) * 100))}% - 5px)`, background: colors[severities.indexOf(severity(item))] }}
            onClick={() => open(item.id)} />)}</div></div>)}
        {!owners.length && <p className="workbench-empty">No open findings with a calendar deadline.</p>}</div>
    </div><div className="sec"><div className="sh">Severity by regulator</div>
      <div className="mx"><div />{severities.map((level) => <div key={level} className="h">{level}</div>)}
        {regulators.map((regulator) => <Fragment key={regulator}><div className="rl">{regulator}</div>{severities.map((level, i) => {
          const count = level === 'Covered' ? obligations.filter((item) => item.regulator === regulator && item.coverageStatus === 'COVERED').length
            : findings.filter((item) => item.regulator === regulator && severity(item) === level).length
          return <button key={level} className="z" aria-label={`${regulator} ${level}: ${count}`} onClick={() => navigate(3)}
            style={{ background: count ? `color-mix(in srgb, ${colors[i]} ${Math.min(count * 28, 85)}%, transparent)` : 'transparent' }}>{count || '·'}</button>
        })}</Fragment>)}</div>
      <div className="sh">Needs a human <span>critical or confidence under 75</span></div>
      {findings.filter((item) => pending(item) && (severity(item) === 'Critical' || percent(item.confidence) < 75)).map((item) =>
        <button className="triage" key={item.id} onClick={() => open(item.id)}><Tag>{severity(item)}</Tag><span>{item.title}</span><Confidence value={item.confidence} /></button>)}
    </div></div>
    <div className="cols"><div className="sec"><div className="sh">Next to fall due <button className="text-action r" onClick={() => navigate(3)}>all gaps</button></div>
      <Table headers={['Clause', 'Obligation', 'Owner', 'Gap', 'Due']}>{dated.slice(0, 6).map((item) => <tr key={item.id}>
        <td className="cl">{item.regulator} {item.clauseNumber}</td><td><button className="text-action" onClick={() => open(item.id)}>{item.title}</button></td>
        <td>{item.assignedRole || '—'}</td><td><Tag>{severity(item)}</Tag></td><td className="mono">{date(item.due)}</td></tr>)}</Table>
    </div><div className="sec feed"><div className="sh">Agent activity <span>recorded reviews</span></div>
      {audit.length ? audit.slice(0, 6).map((entry) => <div className="ln" key={entry.id}><time>{date(entry.decidedAt)}</time>
        <span><b>{entry.reviewer}</b> {title(entry.decision).toLowerCase()} <button className="text-action" onClick={() => open(entry.item.id)}>{entry.item.title}</button></span></div>)
        : <p className="workbench-empty">No recorded reviews yet.</p>}</div></div>
  </>
}
