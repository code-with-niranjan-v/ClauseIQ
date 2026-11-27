import { useEffect, useState } from 'react'
import { api } from '../../api.js'
import { useAuth } from '../../authContext.js'
import { Heading, Table, Tag } from '../components.jsx'
import { date, title } from '../format.js'

const roles = ['VIEWER', 'REVIEWER', 'ADMIN']
const roleHelp = {
  VIEWER: 'reads everything and asks Policy Q&A',
  REVIEWER: 'also reviews findings, scans, uploads and confirms circular changes',
  ADMIN: 'also manages users and the processing queue',
}
const blank = { username: '', displayName: '', role: 'REVIEWER', password: '' }

export default function Users() {
  const me = useAuth()
  const [users, setUsers] = useState([])
  const [form, setForm] = useState(blank)
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [revision, setRevision] = useState(0)

  useEffect(() => {
    let active = true
    api.users().then((list) => { if (active) setUsers(list) }, (error) => { if (active) setMessage(error.message) })
    return () => { active = false }
  }, [revision])

  async function act(operation, done) {
    setBusy(true)
    setMessage('')
    try {
      await operation()
      setMessage(done)
      setRevision((value) => value + 1)
      return true
    } catch (error) { setMessage(error.message); return false } finally { setBusy(false) }
  }

  function resetPassword(user) {
    const password = window.prompt(`New password for ${user.username} (at least 10 characters)`)
    if (password) act(() => api.updateUser(user.id, { password }), `Password changed for ${user.username}.`)
  }

  return <><Heading name="Users" description="Accounts and roles. Decisions are recorded against the signed-in user." />
    <form className="strip sa-form" onSubmit={(event) => {
      event.preventDefault()
      act(() => api.createUser(form), `Created ${form.username.trim().toLowerCase()}.`).then((ok) => { if (ok) setForm(blank) })
    }}>
      <input className="f us-in" aria-label="Username" placeholder="username" required value={form.username}
        onChange={(event) => setForm({ ...form, username: event.target.value })} />
      <input className="f us-in" aria-label="Display name" placeholder="Display name" value={form.displayName}
        onChange={(event) => setForm({ ...form, displayName: event.target.value })} />
      <select className="f us-in" aria-label="Role" value={form.role} onChange={(event) => setForm({ ...form, role: event.target.value })}>
        {roles.map((role) => <option key={role} value={role}>{title(role)}</option>)}</select>
      <input className="f us-in" type="password" aria-label="Initial password" placeholder="Initial password (10+ characters)"
        autoComplete="new-password" required minLength={10} value={form.password}
        onChange={(event) => setForm({ ...form, password: event.target.value })} />
      <button className="btn p" disabled={busy}>Add user</button>
    </form>
    <p className="muted qa-note">{roles.map((role) => `${title(role)} ${roleHelp[role]}`).join('. ')}.</p>
    {message && <p className="cc-msg" role="status">{message}</p>}
    <div className="sec"><Table headers={['User', 'Role', 'Status', 'Last sign-in', 'Actions']}>
      {users.map((user) => <tr key={user.id}>
        <td><b>{user.displayName}</b><div className="mono muted">{user.username}{user.username === me.username ? ' (you)' : ''}</div></td>
        <td><select className="f us-role" aria-label={`Role of ${user.username}`} value={user.role} disabled={busy}
          onChange={(event) => act(() => api.updateUser(user.id, { role: event.target.value }), `${user.username} is now ${title(event.target.value)}.`)}>
          {roles.map((role) => <option key={role} value={role}>{title(role)}</option>)}</select></td>
        <td><Tag>{user.enabled ? 'Enabled' : 'Disabled'}</Tag></td>
        <td className="mono">{date(user.lastLoginAt)}</td>
        <td className="cc-actions">
          <button className="btn" disabled={busy} onClick={() => act(() => api.updateUser(user.id, { enabled: !user.enabled }),
            `${user.username} ${user.enabled ? 'disabled' : 'enabled'}.`)}>{user.enabled ? 'Disable' : 'Enable'}</button>
          <button className="btn" disabled={busy} onClick={() => resetPassword(user)}>Reset password</button></td>
      </tr>)}</Table></div>
  </>
}
