import { useState } from 'react'
import { Confidence, Filters, Heading, Table, Tag } from '../components.jsx'
import { severities, severity, title } from '../format.js'

export default function GapsAndMapping({ obligations, findings, details, open }) {
  const [gapFilter, setGapFilter] = useState('All')
  return (
    <><Heading name="Gaps & mapping" description="Each obligation against the policy handbook and control register">
      <Filters options={['All', ...severities]} value={gapFilter} change={setGapFilter} /></Heading>
      <div className="sec"><Table headers={['Clause', 'Obligation', 'Policy', 'Control', 'Coverage', 'Gap', 'Confidence']}>
        {obligations.filter((item) => gapFilter === 'All' || (gapFilter === 'Covered'
          ? item.coverageStatus === 'COVERED' : severity(findings.find(({ id }) => id === item.findingId)) === gapFilter)).map((item) => {
          const detail = details[item.findingId]
          return <tr key={item.id}><td className="cl">{item.regulator} {item.citation?.clauseNumber}</td>
            <td>{item.findingId ? <button className="text-action" onClick={() => open(item.findingId)}>{item.summary}</button> : item.summary}</td>
            <td>{detail?.policies.map((policy) => policy.heading || policy.sectionNumber).join(', ') || '—'}</td>
            <td>{detail?.controls.map((control) => control.name).join(', ') || '—'}</td>
            <td>{title(item.coverageStatus)}</td><td><Tag>{severity(detail ?? findings.find(({ id }) => id === item.findingId))}</Tag></td><td><Confidence value={item.confidence} /></td></tr>
        })}
      </Table></div></>
  )
}
