import { Heading, Table, Tag } from '../components.jsx'
import { severity, title } from '../format.js'

export default function ActionPlan({ details, open }) {
  const actions = Object.values(details).filter((item) => item.recommendation)
  const owners = [...new Set(actions.map((item) => item.recommendation.assignedRole || 'Unassigned'))]
  return <><Heading name="Action plan" description="Drafted tasks per control owner. Task delivery is unavailable."><button className="btn p" disabled>Send approved tasks</button></Heading>
    <div className="sec"><Table headers={['Task', 'Finding', 'Gap', 'Due', 'Status', 'Delivery']}>{owners.flatMap((owner) => [
      <tr key={owner} className="gr"><td colSpan="6">{owner}</td></tr>,
      ...actions.filter((item) => (item.recommendation.assignedRole || 'Unassigned') === owner).map((item) => <tr key={item.id}>
        <td>{item.recommendation.recommendedAction}</td><td><button className="text-action" onClick={() => open(item.id)}>{item.title}</button></td>
        <td><Tag>{severity(item)}</Tag></td><td className="mono">{item.recommendation.suggestedDeadline || '—'}</td>
        <td><Tag>{title(item.status)}</Tag></td><td><button className="btn" disabled>Send</button></td></tr>),
    ])}</Table></div>
  </>
}
