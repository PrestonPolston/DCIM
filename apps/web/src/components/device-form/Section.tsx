import type { ReactNode } from 'react'

/** Collapsible form group (native <details>, 44px summary). */
export default function Section({ title, defaultOpen = true, children }: { title: string; defaultOpen?: boolean; children: ReactNode }) {
  return (
    <details className="form-section" open={defaultOpen}>
      <summary>{title}</summary>
      <div className="form-section-body">{children}</div>
    </details>
  )
}
