// Generic front/rear art per asset type for missing photos (canvas, client-side only, D28).
// Temporary placeholders, never a substitute for a published photo.
const TINT: Record<string, string> = {
  server: '#4a5566', switch: '#2f5d50', patch_panel: '#3d4450', pdu: '#5a4a3a', router: '#3b4a6b',
  firewall: '#6b3b3b', storage: '#4b3f63', blank: '#22262c', shelf: '#3a3f47', cable_manager: '#2b2f36', other: '#4a4f57',
}

export function genericArt(asset: string, face: 'front' | 'rear'): HTMLCanvasElement {
  const cv = document.createElement('canvas'); cv.width = 512; cv.height = 64
  const g = cv.getContext('2d')
  if (!g) return cv
  const base = TINT[asset] ?? TINT.other
  g.fillStyle = face === 'rear' ? shade(base, -0.25) : base
  g.fillRect(0, 0, 512, 64)
  g.fillStyle = 'rgba(0,0,0,.35)'
  if (asset === 'blank') { for (let x = 16; x < 496; x += 24) g.fillRect(x, 28, 12, 8) }
  else if (asset === 'cable_manager') { for (let x = 24; x < 488; x += 28) g.fillRect(x, 8, 16, 48) }
  else if (face === 'rear') {
    for (let x = 40; x < 300; x += 14) g.fillRect(x, 16, 8, 32) // vents
    g.fillStyle = '#1b1e23'; g.fillRect(380, 12, 50, 40); g.fillRect(440, 12, 50, 40) // PSUs
  } else if (asset === 'switch' || asset === 'patch_panel' || asset === 'router') {
    g.fillStyle = '#c9ced6'
    for (let i = 0; i < 24; i++) g.fillRect(40 + i * 18, 22, 12, 10)
  } else { for (let x = 30; x < 480; x += 60) g.fillRect(x, 10, 50, 44) }
  g.fillStyle = 'rgba(255,255,255,.55)'; g.font = 'bold 14px system-ui, sans-serif'
  g.fillText(`${asset.replace('_', ' ').toUpperCase()}${face === 'rear' ? ' · GENERIC REAR' : ''}`, 10, 58)
  return cv
}

function shade(hex: string, f: number) {
  const n = parseInt(hex.slice(1), 16)
  const c = (v: number) => Math.max(0, Math.min(255, Math.round(v * (1 + f))))
  return `rgb(${c(n >> 16)}, ${c((n >> 8) & 255)}, ${c(n & 255)})`
}
