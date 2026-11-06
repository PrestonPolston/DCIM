import { useCallback, useState } from 'react'
import { DEFAULT_SETTINGS, type HallSettings } from '../../lib/hallLayout'

// Per-hall plan settings, browser-local until the API stores a hall default.
const keyFor = (hallId: number) => `dcim.hall.${hallId}.layout`

function read(hallId: number): HallSettings {
  try {
    const raw = localStorage.getItem(keyFor(hallId))
    return raw ? { ...DEFAULT_SETTINGS, ...(JSON.parse(raw) as Partial<HallSettings>) } : DEFAULT_SETTINGS
  } catch {
    return DEFAULT_SETTINGS
  }
}

export function useHallSettings(hallId: number) {
  const [state, setState] = useState(() => ({ hallId, settings: read(hallId) }))
  const settings = state.hallId === hallId ? state.settings : read(hallId)
  const update = useCallback(
    (patch: Partial<HallSettings> | null) => {
      const next = patch === null ? DEFAULT_SETTINGS : { ...settings, ...patch }
      if (patch === null) localStorage.removeItem(keyFor(hallId))
      else localStorage.setItem(keyFor(hallId), JSON.stringify(next))
      setState({ hallId, settings: next })
    },
    [hallId, settings],
  )
  return [settings, update] as const
}
