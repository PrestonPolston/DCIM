// Generic device fronts by category (row-front.md §5): six inline SVG
// <symbol>s defined once per page and drawn with <use>, repeated per RU.
import type { Category } from '../../lib/rowFront'

const ACCENT: Record<Category, string> = {
  server: 'var(--type-server)', switch: 'var(--type-network)', patch: 'var(--type-patch)',
  pdu: 'var(--type-power)', cable: 'var(--type-other)', other: 'var(--type-other)', unknown: 'var(--border)',
}

/** Render once inside the row view; FallbackFront references these by id. */
export function FallbackSymbols() {
  return (
    <svg width="0" height="0" style={{ position: 'absolute' }} aria-hidden="true" focusable="false">
      <defs>
        <symbol id="ff-server" viewBox="0 0 100 10" preserveAspectRatio="none">
          <rect x="2" y="1" width="3" height="8" rx="1" fill="currentColor" opacity=".5" />
          <rect x="95" y="1" width="3" height="8" rx="1" fill="currentColor" opacity=".5" />
          {[8, 18, 28, 38, 48, 58].map((x) => <rect key={x} x={x} y="2" width="8" height="6" rx=".5" fill="none" stroke="currentColor" strokeWidth=".6" />)}
          {[70, 74, 78, 82, 86].map((x) => <rect key={x} x={x} y="2" width="1.5" height="6" fill="currentColor" opacity=".35" />)}
          <circle cx="91" cy="5" r="1" fill="var(--status-active)" />
        </symbol>
        <symbol id="ff-switch" viewBox="0 0 100 10" preserveAspectRatio="none">
          {Array.from({ length: 24 }, (_, i) => <rect key={i} x={6 + i * 3.1} y={i % 2 ? 5.5 : 2} width="2.4" height="2.6" fill="currentColor" opacity=".6" />)}
          {[84, 88, 92].map((x) => <rect key={x} x={x} y="3" width="3" height="4" fill="none" stroke="currentColor" strokeWidth=".6" />)}
          <rect x="2" y="8.5" width="96" height=".6" fill="currentColor" opacity=".4" />
        </symbol>
        <symbol id="ff-patch" viewBox="0 0 100 10" preserveAspectRatio="none">
          {Array.from({ length: 24 }, (_, i) => <circle key={i} cx={6 + i * 3.8} cy="4.5" r="1.2" fill="none" stroke="currentColor" strokeWidth=".5" />)}
          <rect x="4" y="7.5" width="92" height="1" fill="currentColor" opacity=".4" />
        </symbol>
        <symbol id="ff-pdu" viewBox="0 0 100 10" preserveAspectRatio="none">
          <rect x="4" y="2.5" width="12" height="5" fill="currentColor" opacity=".3" />
          {Array.from({ length: 8 }, (_, i) => <rect key={i} x={22 + i * 8} y="3" width="5" height="4" rx=".8" fill="none" stroke="currentColor" strokeWidth=".6" />)}
          <rect x="90" y="3" width="4" height="4" fill="currentColor" opacity=".6" />
        </symbol>
 <symbol id="ff-cable" viewBox="0 0 100 10" preserveAspectRatio="none">
          <rect x="2" y="1" width="96" height="8" fill="currentColor" opacity=".15" />
          {Array.from({ length: 16 }, (_, i) => <rect key={i} x={5 + i * 5.8} y="1" width="2.6" height="8" fill="currentColor" opacity=".55" />)}
        </symbol>
        <symbol id="ff-other" viewBox="0 0 100 10" preserveAspectRatio="none">
          <circle cx="4" cy="5" r="1" fill="currentColor" opacity=".5" />
          <circle cx="96" cy="5" r="1" fill="currentColor" opacity=".5" />
        </symbol>
        <symbol id="ff-unknown" viewBox="0 0 100 10" preserveAspectRatio="none">
          <rect x=".5" y=".5" width="99" height="9" fill="none" stroke="currentColor" strokeDasharray="2 1.5" strokeWidth=".5" />
        </symbol>
      </defs>
    </svg>
  )
}

export default function FallbackFront({ category, units }: { category: Category; units: number }) {
  const n = category === 'unknown' ? 1 : Math.max(1, units)
  return (
    <span className={`ff ff-${category}`} style={{ ['--ff-accent' as string]: ACCENT[category] }} data-testid="fallback-front" data-category={category}>
      <svg className="ff-svg" viewBox={`0 0 100 ${n * 10}`} preserveAspectRatio="none" aria-hidden="true" focusable="false">
        {Array.from({ length: n }, (_, i) => <use key={i} href={`#ff-${category}`} y={i * 10} width="100" height="10" />)}
      </svg>
      {category === 'unknown' && <span className="ff-q" aria-hidden="true">?</span>}
    </span>
  )
}
