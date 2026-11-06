import { useEffect, useRef, type ReactNode } from 'react'

interface Props {
  title: string
  children: ReactNode
  confirmLabel: string
  danger?: boolean
  busy?: boolean
  error?: string | null
  onConfirm: () => void
  onCancel: () => void
}

// Small centered confirm (mobile.md §2: the only non-page overlay), 2 buttons.
export default function ConfirmDialog({ title, children, confirmLabel, danger, busy, error, onConfirm, onCancel }: Props) {
  const cancel = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    cancel.current?.focus()
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onCancel()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onCancel])
  return (
    <div className="dialog-backdrop" role="dialog" aria-modal="true" aria-label={title}>
      <div className="card form confirm-dialog">
        <h2>{title}</h2>
        <div>{children}</div>
        {error && <p className="error" role="alert">{error}</p>}
        <div className="actions">
          <button type="button" ref={cancel} onClick={onCancel} disabled={busy}>Cancel</button>
          <button type="button" className={danger ? 'danger solid' : 'primary'} onClick={onConfirm} disabled={busy}>
            {busy ? 'Saving…' : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
