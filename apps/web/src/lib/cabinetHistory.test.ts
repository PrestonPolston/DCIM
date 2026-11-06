import { describe, expect, it } from 'vitest'
import type { CabinetHistoryEvent } from '../api/cabinetProfiles'
import { changesOf, collapseHistory } from './cabinetHistory'

const ev = (id: number, action: string, at: string, before: Record<string, unknown> | null, after: Record<string, unknown> | null): CabinetHistoryEvent =>
  ({ id, action: `cabinet_profile.${action}`, occurred_at: `2026-11-03T12:00:${at}+00:00`, actor_email: 'a@x', before, after })

describe('cabinet history', () => {
  it('collapses publish/retire/unretire pairs, clone+create, and keeps edits with changed fields', () => {
    const events = [ // newest first
      ev(9, 'unretire', '40', { status: 'retired' }, { status: 'published', change_set_id: 3 }),
      ev(8, 'update', '40', { status: 'retired', retired_at: 'x' }, { status: 'published', retired_at: null }),
      ev(7, 'retire', '30', { status: 'published' }, { status: 'retired' }),
      ev(6, 'update', '30', { status: 'published' }, { status: 'retired' }),
      ev(5, 'image.put', '25', null, { face: 'rear', sha256: 'abc' }),
      ev(4, 'update', '20', { depth_mm: null, rack_unit_width: null, notes: 'a' }, { depth_mm: 1200, rack_unit_width: '23in', notes: 'a' }),
      ev(3, 'publish', '10', { status: 'draft' }, { status: 'published' }),
      ev(2, 'update', '10', { status: 'draft', published_at: null }, { status: 'published', published_at: 'x' }),
      ev(1, 'create', '00', null, { manufacturer: 'APC', width_mm: 600, rail_type: 'square_hole' }),
    ]
    const h = collapseHistory(events)
    expect(h.map((e) => e.title)).toEqual(['Un-retired', 'Retired', 'Rear image uploaded', 'Edited', 'Published', 'Created'])
    expect(h[0].changes).toEqual([{ field: 'status', label: 'Status', from: 'retired', to: 'published' }])
    expect(h[3].changes.map((c) => `${c.label}: ${c.from} → ${c.to}`)).toEqual(['Outer depth: — → 1200 mm', 'Rack-unit width: — → 23 in'])
    expect(h[5].changes.map((c) => c.to)).toEqual(['APC', '600 mm', 'Square hole'])
  })
  it('clone + create of the new row become one entry', () => {
    const h = collapseHistory([ev(12, 'clone', '05', null, { source_id: 1, new_id: 4, image_count: 2 }), ev(11, 'create', '05', null, { name: 'Standard (copy)' })])
    expect(h).toEqual([{ id: 12, at: '2026-11-03T12:00:05+00:00', actor: 'a@x', title: 'Created as a copy of profile #1 (2 images copied)', changes: [] }])
  })
  it('a lone update is an edit; bookkeeping keys are hidden', () => {
    expect(changesOf({ updated_at: 'a', notes: 'x' }, { updated_at: 'b', notes: 'y' })).toEqual([{ field: 'notes', label: 'Notes', from: 'x', to: 'y' }])
    expect(collapseHistory([ev(1, 'update', '00', { status: 'draft' }, { status: 'published' })])[0].title).toBe('Edited')
  })
  it('summarises image uploads without raw pixel diffs', () => {
    const h = collapseHistory([ev(20, 'image.put', '09', { face: 'front', sha256: 'a' }, { face: 'front', sha256: 'b', width_px: 600, height_px: 1990, byte_size: 8216 })])
    expect(h[0].title).toBe('Front image replaced (600 × 1990 px, 8.0 KB)')
    expect(h[0].changes).toEqual([])
  })
})
