import { Confidence, Filters, Tag } from '../components.jsx'
import { pending, severity } from '../format.js'
import ReviewPane from '../ReviewPane.jsx'

export default function ReviewWorkbench({ visible, current, filter, setFilter, setSelected, details, roles, onSaved, detailError }) {
  return (
    <div className="wb">
      <div className="sec workbench-list"><div className="sh workbench-sticky"><div className="findings-label">Findings <span>{visible.length}</span></div>
        <Filters options={['All', 'Pending', 'Critical', 'High']} value={filter} change={setFilter} /></div>
        {visible.map((item) => <button key={item.id} className={`li ${current?.id === item.id ? 'on' : ''}`} onClick={() => setSelected(item.id)}>
          <span className={`st ${pending(item) ? 'pen' : item.status === 'REJECTED' ? 'rej' : 'app'}`}>{pending(item) ? '○' : item.status === 'REJECTED' ? '✕' : '✓'}</span>
          <b>{item.title}</b><Tag>{severity(item)}</Tag><small><span className="cl">{item.regulator} {item.clauseNumber}</span><Confidence value={item.confidence} /></small>
        </button>)}
        {!visible.length && <p className="workbench-empty">No findings match this filter.</p>}
      </div>
      <div className="review-content" key={current?.id}>
        {current && details[current.id] ? <ReviewPane finding={details[current.id]} roles={roles}
          onSaved={onSaved} /> :
          <div className="doc"><p className="workbench-empty">{current ? detailError || 'Loading finding evidence…' : 'Select a finding to review its evidence.'}</p></div>}
      </div>
      </div>
  )
}
