import { useCallback, useEffect, useState } from 'react'
import { api, UNAUTHORIZED } from './api.js'
import { AuthContext } from './authContext.js'

const styles = `
.signin{min-height:100vh;display:grid;place-items:center;background:#e8ecf0;font:14px/1.45 'IBM Plex Sans',system-ui,sans-serif;color:#131c2e;padding:16px}
.signin form{width:min(360px,100%);background:#fff;border:1px solid #d3dae3;border-radius:8px;padding:28px;display:grid;gap:14px;box-shadow:0 10px 30px #101a2e1a}
.signin h1{font-size:20px;margin:0}.signin p{margin:0;color:#46526a;font-size:13px}
.signin label{display:grid;gap:4px;font-size:12.5px;font-weight:600}
.signin input{font:inherit;padding:8px 10px;border:1px solid #c5cee0;border-radius:5px}
.signin input:focus{outline:2px solid #e4572e;outline-offset:-1px;border-color:#e4572e}
.signin button{font:inherit;font-weight:600;padding:9px;border:0;border-radius:5px;background:#e4572e;color:#fff;cursor:pointer}
.signin button[disabled]{opacity:.5;cursor:default}
.signin .error{color:#b3261e;font-size:13px;margin:0}
.signin .logo{width:36px;height:36px;border-radius:6px;background:#e4572e;color:#fff;display:grid;place-items:center;font-weight:700}
`

function SignIn({ onSignedIn, expired }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      onSignedIn(await api.login(username.trim(), password))
    } catch (failure) {
      setError(failure.message)
      setPassword('')
    } finally {
      setBusy(false)
    }
  }

  return <main className="signin"><style>{styles}</style>
    <form onSubmit={submit} aria-labelledby="signin-title">
      <div className="logo" aria-hidden="true">CQ</div>
      <h1 id="signin-title">Sign in to ClauseIQ</h1>
      <p>{expired ? 'Your session ended. Sign in again to continue.' : 'Use the account your administrator gave you.'}</p>
      <label>Username<input autoFocus autoComplete="username" value={username} required
        onChange={(event) => setUsername(event.target.value)} /></label>
      <label>Password<input type="password" autoComplete="current-password" value={password} required
        onChange={(event) => setPassword(event.target.value)} /></label>
      {error && <p className="error" role="alert">{error}</p>}
      <button disabled={busy || !username.trim() || !password}>{busy ? 'Signing in…' : 'Sign in'}</button>
    </form>
  </main>
}

export function AuthGate({ children }) {
  const [user, setUser] = useState(undefined)   // undefined while checking, null when signed out
  const [expired, setExpired] = useState(false)

  useEffect(() => {
    let active = true
    api.me().then((me) => { if (active) setUser(me) }, () => { if (active) setUser(null) })
    function signedOut() {
      setUser((current) => {
        if (current) setExpired(true)
        return null
      })
    }
    window.addEventListener(UNAUTHORIZED, signedOut)
    return () => { active = false; window.removeEventListener(UNAUTHORIZED, signedOut) }
  }, [])

  const signOut = useCallback(async () => {
    try { await api.logout() } finally { setExpired(false); setUser(null) }
  }, [])

  if (user === undefined) return null
  if (user === null) return <SignIn expired={expired} onSignedIn={(me) => { setExpired(false); setUser(me) }} />
  const value = { ...user, signOut, can: { review: user.role !== 'VIEWER', admin: user.role === 'ADMIN' } }
  // Remount the app for a different user so no state carries over between accounts.
  return <AuthContext.Provider value={value} key={user.username}>{children}</AuthContext.Provider>
}
