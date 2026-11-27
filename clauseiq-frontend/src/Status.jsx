import { TONES, label } from './labels.js'

export default function Status({ value }) {
  return <span className={`status status-${TONES[value] ?? 'plain'}`}>{label(value)}</span>
}
