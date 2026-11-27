export const severities = ['Critical', 'High', 'Medium', 'Low', 'Covered']
export const colors = ['var(--c)', 'var(--h)', 'var(--m)', 'var(--l)', 'var(--ok)']
export const pending = (item) => item.status === 'PENDING_REVIEW'
export const severity = (item) => item?.severity ? title(item.severity) : '—'
export const title = (value) => value ? value.toLowerCase().replaceAll('_', ' ').replace(/^./, (c) => c.toUpperCase()) : '—'
export const percent = (value) => Math.round(value * 100)
export const date = (value) => value ? new Date(value).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }) : '—'
export const isoDate = (value) => /^\d{4}-\d{2}-\d{2}$/.test(value ?? '') && Number.isFinite(Date.parse(value))
export const day = 86400000
