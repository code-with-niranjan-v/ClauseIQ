import { useRef, useState } from 'react'
import { api } from './api.js'
import Status from './Status.jsx'

const processingLabels = {
  STARTING: 'Processing is starting.',
  RUNNING: 'Processing is running.',
  PAUSING: 'Pausing after the current PDF finishes.',
  PAUSED: 'Processing is paused. New PDFs stay queued.',
  DEGRADED: 'The processing worker is reconnecting.',
  STOPPED: 'The processing worker is stopped.',
}

export default function ProcessingControls({ processing, refresh }) {
  const picker = useRef(null)
  const [changing, setChanging] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [controlError, setControlError] = useState(null)
  const [clearMessage, setClearMessage] = useState(null)
  const [clearedBefore, setClearedBefore] = useState(null)
  const [uploadMessage, setUploadMessage] = useState(null)
  const { data, error } = processing
  const workerUnavailable = !data || Boolean(error) || data.state === 'STOPPED'

  async function toggleProcessing() {
    setChanging(true)
    setControlError(null)
    try {
      await api.setPaused(!data.paused)
      refresh()
    } catch (error) {
      setControlError(error.message)
    } finally {
      setChanging(false)
    }
  }

  async function clearQueue() {
    if (!window.confirm('Clear all waiting PDFs and pause processing? The current PDF can finish. Completed results are kept. Upload any cleared PDFs again before resuming.')) return
    setChanging(true)
    setControlError(null)
    setClearMessage(null)
    try {
      const result = await api.clearQueue()
      setClearedBefore(result.clearedBefore)
      setUploadMessage(null)
      setClearMessage('Queue cleared. Upload the PDFs you want, then resume processing.')
    } catch (error) {
      setControlError(error.message)
    } finally {
      refresh()
      setChanging(false)
    }
  }

  async function upload(event) {
    const files = Array.from(event.currentTarget.files)
    event.currentTarget.value = ''
    if (!files.length) return
    setUploading(true)
    setUploadMessage(null)
    let queued = 0
    let duplicates = 0
    const failures = []
    const cutoff = data?.clearedBefore || clearedBefore
    try {
      // Save one file at a time so uploads use the scanner's existing source lock.
      for (const file of files) {
        if (file.size > 30 * 1024 * 1024) {
          failures.push(`${file.name} exceeds 30 MiB.`)
          continue
        }
        try {
          const result = await api.uploadPdf(file, cutoff)
          if (result.added) queued++
          else duplicates++
        } catch (error) {
          failures.push(`${file.name}: ${error.message}`)
        }
      }
      setUploadMessage({
        tone: failures.length ? 'bad' : 'good',
        text: `${queued} queued, ${duplicates} already uploaded, ${failures.length} failed.`,
        failures,
      })
    } finally {
      refresh()
      setUploading(false)
    }
  }

  return (
    <div className="processing-controls">
      <div className="worker-status" role="status">
        <strong>Worker</strong>
        {data && <Status value={data.state} />}
        <span>{error ? 'Worker status could not be refreshed.' : data
          ? processingLabels[data.state] ?? 'The worker reported an unknown state.'
          : 'Checking worker status…'}</span>
      </div>
      <div className="buttons">
        <input ref={picker} type="file" accept=".pdf,application/pdf" multiple onChange={upload} hidden />
        <button type="button" className="button button-primary" disabled={uploading || changing}
          onClick={() => picker.current.click()}>
          {uploading ? 'Uploading…' : 'Upload PDFs'}
        </button>
        <button type="button" className="button" disabled={workerUnavailable || changing}
          onClick={toggleProcessing}>
          {data?.paused ? 'Resume processing' : 'Pause processing'}
        </button>
      </div>
      <details className="queue-management">
        <summary>Queue management</summary>
        <p className="sub">Clearing the queue removes waiting PDFs and pauses the worker. The current PDF can finish.</p>
        <button type="button" className="button button-danger" disabled={workerUnavailable || changing || uploading}
          onClick={clearQueue}>Clear queue</button>
      </details>
      {(controlError || error) && <p className="notice notice-bad" role="alert">{controlError || error}</p>}
      {clearMessage && <p className="notice notice-good" role="status">{clearMessage}</p>}
      {uploadMessage && (
        <div className={`notice notice-${uploadMessage.tone}`} role={uploadMessage.tone === 'bad' ? 'alert' : 'status'}>
          <p>{uploadMessage.text}</p>
          {uploadMessage.failures.length > 0 && (
            <ul>{uploadMessage.failures.map((failure, index) => <li key={index}>{failure}</li>)}</ul>
          )}
        </div>
      )}
    </div>
  )
}
