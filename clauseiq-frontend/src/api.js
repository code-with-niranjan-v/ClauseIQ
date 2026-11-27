async function request(path, options) {
  let response
  try {
    response = await fetch(path, options)
  } catch {
    throw new Error('The backend is not reachable.')
  }
  const text = await response.text()
  let body
  try {
    body = text ? JSON.parse(text) : null
  } catch {
    body = null
  }
  if (!response.ok) {
    throw new Error(body?.message || `The request failed with HTTP ${response.status}.`)
  }
  return body
}

function post(path, body) {
  return request(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body ?? {}),
  })
}

export const api = {
  summary: () => request('/api/summary'),
  sources: () => request('/api/admin/sources'),
  scan: (id) => post(`/api/admin/sources/${encodeURIComponent(id)}/scan`),
  processing: () => request('/api/admin/processing'),
  queue: () => request('/api/admin/sources/queue-entries'),
  setPaused: (paused) => request('/api/admin/processing', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ paused }),
  }),
  clearQueue: () => post('/api/admin/processing/clear'),
  uploadPdf: (file, clearedBefore) => {
    const body = new FormData()
    body.append('file', file)
    if (clearedBefore) body.append('clearedBefore', clearedBefore)
    return request('/api/admin/sources/upload-pdf', { method: 'POST', body })
  },
  documents: () => request('/api/documents'),
  obligations: () => request('/api/obligations'),
  findings: () => request('/api/findings'),
  finding: (id) => request(`/api/findings/${id}`),
  roles: () => request('/api/roles'),
  approve: (id, body) => post(`/api/findings/${id}/approve`, body),
  editAndApprove: (id, body) => post(`/api/findings/${id}/edit-and-approve`, body),
  reject: (id, body) => post(`/api/findings/${id}/reject`, body),
}
