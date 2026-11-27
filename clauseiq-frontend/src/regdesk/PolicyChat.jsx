import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'

const examples = [
  'How long must audit logs be retained?',
  'Can customer personal data be stored in a development tool?',
  'How quickly must a security incident be reported?',
]

function Citation({ item }) {
  const label = item.type === 'POLICY_UPDATE'
    ? `Approved update${item.sectionNumber ? ` · §${item.sectionNumber}` : ''}`
    : `Policy §${item.sectionNumber ?? '—'}${item.heading ? ` ${item.heading}` : ''}`
  const circular = item.circular
  return <li className="qa-cite"><b>{label}</b>
    {item.type === 'POLICY_UPDATE' && item.heading && <span className="muted"> · {item.heading}</span>}
    <q>{item.excerpt}</q>
    {circular?.title && <small>From {circular.regulator ? `${circular.regulator} ` : ''}
      {/^https?:\/\//i.test(circular.sourceUrl ?? '')
        ? <a className="text-action" href={circular.sourceUrl} target="_blank" rel="noreferrer">{circular.title}</a>
        : circular.title}</small>}</li>
}

function Answer({ result }) {
  if (result.status !== 'ANSWERED') return <p>{result.answer}</p>
  return <>
    {result.domain && <div className="qa-domain">{result.domain}</div>}
    <p>{result.answer}</p>
    {result.conditions.length > 0 && <><div className="qa-label">Conditions</div>
      <ul className="qa-list">{result.conditions.map((item, index) => <li key={index}>{item}</li>)}</ul></>}
    {result.warning && <p className="qa-warn" role="note">⚠ {result.warning}</p>}
    <div className="qa-label">Approved sources</div>
    <ul className="qa-list qa-cites">{result.citations.map((item) => <Citation key={item.id} item={item} />)}</ul>
  </>
}

export default function PolicyChat({ messages, setMessages }) {
  const [question, setQuestion] = useState('')
  const [busy, setBusy] = useState(false)
  const end = useRef(null)
  useEffect(() => { end.current?.scrollIntoView({ block: 'end' }) }, [messages, busy])

  async function ask(text) {
    const value = text.trim()
    if (!value || busy) return
    setQuestion('')
    setBusy(true)
    setMessages((list) => [...list, { role: 'user', text: value }])
    try {
      const result = await api.ask(value)
      setMessages((list) => [...list, { role: 'bot', result }])
    } catch (error) {
      setMessages((list) => [...list, { role: 'error', text: error.message }])
    } finally {
      setBusy(false)
    }
  }

  return <>
    <div className="chat" aria-live="polite">
      <p className="m b">I answer only from approved policy: handbook sections, and policy updates a reviewer approved
        in response to a circular. I do not use draft or pending findings.</p>
      {messages.length === 0 && <div className="qa-examples">{examples.map((item) =>
        <button key={item} className="btn" onClick={() => ask(item)}>{item}</button>)}</div>}
      {messages.map((item, index) => item.role === 'user'
        ? <p key={index} className="m u">{item.text}</p>
        : <div key={index} className={`m b ${item.role === 'error' || item.result?.status !== 'ANSWERED' ? 'qa-refused' : ''}`}>
          {item.role === 'error' ? <p>{item.text}</p> : <Answer result={item.result} />}</div>)}
      {busy && <p className="m b muted">Searching approved policies…</p>}
      <div ref={end} />
    </div>
    <form className="qa-input" onSubmit={(event) => { event.preventDefault(); ask(question) }}>
      <input autoFocus className="f" aria-label="Policy question" placeholder="Ask a policy question" maxLength={1000}
        value={question} onChange={(event) => setQuestion(event.target.value)} disabled={busy} />
      <button className="btn p" disabled={busy || !question.trim()}>Ask</button>
    </form>
  </>
}
