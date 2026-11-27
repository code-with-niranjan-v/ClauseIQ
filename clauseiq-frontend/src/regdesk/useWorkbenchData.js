import { useEffect, useState } from 'react'
import { api } from '../api.js'

export function useCatalog() {
  const [data, setData] = useState({})
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  useEffect(() => {
    let active = true
    let loading = false
    async function load() {
      if (loading) return
      loading = true
      const keys = ['documents', 'obligations', 'findings', 'sources', 'processing', 'queue', 'roles']
      const results = await Promise.allSettled(keys.map((key) => api[key]()))
      if (active) {
        const values = Object.fromEntries(keys.flatMap((key, i) => results[i].status === 'fulfilled' ? [[key, results[i].value]] : []))
        setData((previous) => ({ ...previous, ...values }))
        setError(results.flatMap((result, i) => result.status === 'rejected' ? [`${keys[i]}: ${result.reason.message}`] : []).join(' · '))
      }
      loading = false
    }
    load()
    const timer = setInterval(load, 10000)
    return () => { active = false; clearInterval(timer) }
  }, [revision])
  return { data, error, refresh: () => setRevision((value) => value + 1) }
}

export function useDetails(ids, revision) {
  const [result, setResult] = useState({ entries: {}, error: '' })
  useEffect(() => {
    let active = true
    async function load() {
      const keys = ids ? ids.split(',') : []
      const entries = {}
      let error = ''
      for (let i = 0; active && i < keys.length; i += 8) {
        const batch = keys.slice(i, i + 8)
        const values = await Promise.allSettled(batch.map(api.finding))
        values.forEach((value, index) => {
          if (value.status === 'fulfilled') entries[batch[index]] = value.value
          else error = value.reason.message
        })
      }
      if (active) setResult({ entries, error })
    }
    load()
    return () => { active = false }
  }, [ids, revision])
  return result
}
