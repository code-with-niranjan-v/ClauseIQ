/** Word-level diff (longest common subsequence). Returns [{ type: 'same' | 'add' | 'del', text }]. */
export function wordDiff(before = '', after = '') {
  const a = before.split(/(\s+)/).filter(Boolean)
  const b = after.split(/(\s+)/).filter(Boolean)
  if (a.length * b.length > 250000) return [{ type: 'del', text: before }, { type: 'add', text: after }]
  const table = Array.from({ length: a.length + 1 }, () => new Uint16Array(b.length + 1))
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      table[i][j] = a[i] === b[j] ? table[i + 1][j + 1] + 1 : Math.max(table[i + 1][j], table[i][j + 1])
    }
  }
  const parts = []
  const push = (type, text) => {
    const last = parts[parts.length - 1]
    if (last?.type === type) last.text += text
    else parts.push({ type, text })
  }
  let i = 0
  let j = 0
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) { push('same', a[i]); i++; j++ }
    else if (table[i + 1][j] >= table[i][j + 1]) push('del', a[i++])
    else push('add', b[j++])
  }
  while (i < a.length) push('del', a[i++])
  while (j < b.length) push('add', b[j++])
  return parts
}
