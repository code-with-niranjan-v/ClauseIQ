import axios from 'axios'

const http = axios.create({ baseURL: '/api' })

http.interceptors.response.use(
  (response) => response.data,
  (error) => Promise.reject(new Error(
    error.response?.data?.message || (error.response
      ? `The request failed with HTTP ${error.response.status}.`
      : 'The backend is not reachable.'),
  )),
)

const source = '/admin/sources'
const processing = '/admin/processing'
const finding = (id) => `/findings/${encodeURIComponent(id)}`

export const api = {
  summary: () => http.get('/summary'),
  sources: () => http.get(source),
  scan: (id) => http.post(`${source}/${encodeURIComponent(id)}/scan`, {}),
  processing: () => http.get(processing),
  queue: () => http.get(`${source}/queue-entries`),
  setPaused: (paused) => http.put(processing, { paused }),
  clearQueue: () => http.post(`${processing}/clear`, {}),
  uploadPdf: (file, clearedBefore) => {
    const body = new FormData()
    body.append('file', file)
    if (clearedBefore) body.append('clearedBefore', clearedBefore)
    return http.post(`${source}/upload-pdf`, body)
  },
  documents: () => http.get('/documents'),
  obligations: () => http.get('/obligations'),
  findings: () => http.get('/findings'),
  finding: (id) => http.get(finding(id)),
  roles: () => http.get('/roles'),
  approve: (id, body) => http.post(`${finding(id)}/approve`, body),
  editAndApprove: (id, body) => http.post(`${finding(id)}/edit-and-approve`, body),
  reject: (id, body) => http.post(`${finding(id)}/reject`, body),
  ask: (question) => http.post('/chat', { question }),
}
