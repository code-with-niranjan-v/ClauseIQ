import axios from 'axios'

const http = axios.create({ baseURL: '/api' })

// The session expired or was never there: let the app show the sign-in page.
export const UNAUTHORIZED = 'clauseiq:unauthorized'

http.interceptors.response.use(
  (response) => response.data,
  (error) => {
    if (error.response?.status === 401 && !error.config?.url?.startsWith('/auth/')) {
      window.dispatchEvent(new Event(UNAUTHORIZED))
    }
    return Promise.reject(new Error(
    error.response?.data?.message || (error.response
      ? `The request failed with HTTP ${error.response.status}.`
      : 'The backend is not reachable.'),
    ))
  },
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
  systemAssessments: () => http.get('/system-assessments'),
  systemAssessment: (id) => http.get(`/system-assessments/${encodeURIComponent(id)}`),
  createSystemAssessment: (form) => http.post('/system-assessments', form),
  me: () => http.get('/auth/me'),
  login: (username, password) => http.post('/auth/login', { username, password }),
  logout: () => http.post('/auth/logout', {}),
  users: () => http.get('/admin/users'),
  createUser: (user) => http.post('/admin/users', user),
  updateUser: (id, change) => http.patch(`/admin/users/${encodeURIComponent(id)}`, change),
  circularLinks: () => http.get('/lineage/links'),
  refreshLineage: () => http.post('/lineage/refresh', {}),
  decideLink: (id, confirm) => http.post(`/lineage/links/${encodeURIComponent(id)}/decision`, { confirm }),
  linkDiff: (id) => http.get(`/lineage/links/${encodeURIComponent(id)}/diff`),
  quality: () => http.get('/quality'),
  scanTargets: () => http.get('/data-scans/targets'),
  dataScans: () => http.get('/data-scans'),
  dataScan: (id) => http.get(`/data-scans/${encodeURIComponent(id)}`),
  runDataScan: (target) => http.post('/data-scans', { target }),
}

/** Report downloads are plain links: the session cookie authorises them. */
export const reportUrl = {
  posture: (format) => `/api/reports/posture.${format}`,
  system: (id, format) => `/api/reports/system-assessments/${encodeURIComponent(id)}.${format}`,
}
