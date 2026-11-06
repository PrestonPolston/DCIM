// Minimal RFC 4180 CSV parse/serialize (quotes, commas, newlines in fields).
export function parseCsv(text: string): string[][] {
  const rows: string[][] = []
  let row: string[] = []
  let field = ''
  let q = false
  for (let i = 0; i < text.length; i++) {
    const c = text[i]
    if (q) {
      if (c === '"' && text[i + 1] === '"') { field += '"'; i++ }
      else if (c === '"') q = false
      else field += c
    } else if (c === '"') q = true
    else if (c === ',') { row.push(field); field = '' }
    else if (c === '\n' || c === '\r') {
      if (c === '\r' && text[i + 1] === '\n') i++
      row.push(field); rows.push(row); row = []; field = ''
    } else field += c
  }
  if (field !== '' || row.length) { row.push(field); rows.push(row) }
  return rows
}

export function toCsv(rows: string[][]): string {
  return rows.map((r) => r.map((f) => (/[",\r\n]/.test(f) ? `"${f.replace(/"/g, '""')}"` : f)).join(',')).join('\r\n') + '\r\n'
}

/** Keep the header plus rows whose `column` is empty. */
export function filterEmptyColumn(text: string, column: string): string {
  const rows = parseCsv(text)
  if (!rows.length) return text
  const idx = rows[0].indexOf(column)
  if (idx < 0) return text
  return toCsv([rows[0], ...rows.slice(1).filter((r) => !(r[idx] ?? '').trim())])
}
