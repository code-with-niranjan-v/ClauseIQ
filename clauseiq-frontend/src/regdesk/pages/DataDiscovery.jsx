import { Heading, Table } from '../components.jsx'

export default function DataDiscovery() {
  return (
    <><Heading name="Data discovery" description="Schema-level sensitive-field discovery"><button className="btn p" disabled>Run scan</button></Heading>
      <div className="sec"><div className="sh">Data discovery <span>Unavailable</span></div>
        <Table headers={['Field', 'Detected as', 'Sensitivity', 'DPDP link', 'Sample', 'Encrypted']} empty="The backend has no schema scanning endpoint." /></div></>
  )
}
