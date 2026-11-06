// Lazy chunk (React.lazy): the three.js canvas plus its HTML label overlay.
// Everything three.js lives behind this module boundary.
import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react'
import { faceOutline, layoutLabels, labelSpecs, type LabelSpec } from '../../lib/labels'
import type { Face3D, RowScene } from '../../lib/row3d'
import { RowRenderer } from './RowRenderer'

export interface Row3DHandle {
  flip(): void
  setSide(side: Face3D): void
  preset(kind: 'front' | 'rear' | 'reset' | 'fit'): void
  focusCabinet(index: number): void
  zoom(factor: number): void
  stats(): ReturnType<RowRenderer['stats']> | null
}
export interface Label { id: number; text: string }
interface Props {
  scene: RowScene
  selectedId: number | null
  highlight: 'none' | 'status'
  /** Initial camera: a cabinet index to focus, else the side preset. */
  initial: { side: Face3D; cabinet: number | null }
  reducedMotion: boolean
  /** Row name shown at the row's end (with the cabinet names). */
  rowName?: string
  /** The selected device's name tag (device names are never always-on), or null. */
  tag: Label | null
  /** Labels toggle: row + cabinet names. */
  cabinetLabels: boolean
  /** Selected device id: draws the ◢ corner marker (non-colour selection cue). */
  marker: number | null
  onPick: (id: number | null) => void
  onHover: (id: number | null, x: number, y: number, rect?: { left: number; top: number; right: number; bottom: number } | null) => void
  onFocusCabinet: (index: number) => void
  onView: (side: Face3D) => void
  onFatal: (err: Error) => void
}


const Row3DView = forwardRef<Row3DHandle, Props>(function Row3DView(p, ref) {
  const hostRef = useRef<HTMLDivElement | null>(null)
  const r = useRef<RowRenderer | null>(null)
  const cb = useRef(p)
  useEffect(() => { cb.current = p })
  const layer = useRef<HTMLDivElement | null>(null)
  const overlay = useRef(new Overlay())

  useEffect(() => {
    const host = hostRef.current
    if (!host) return
    // A fresh canvas per mount: dispose() force-loses the context, so a canvas is never reused
    // (StrictMode remounts, row switches).
    const canvas = document.createElement('canvas')
    canvas.className = 'r3d-canvas'
    canvas.setAttribute('aria-hidden', 'true') // pixels only; the selection line + List are the accessible path
    host.prepend(canvas)
    let rr: RowRenderer
    try {
      rr = new RowRenderer(canvas, {
        onPick: (id) => cb.current.onPick(id),
        onHover: (id, x, y, rect) => cb.current.onHover(id, x, y, rect),
        onFocusCabinet: (i) => cb.current.onFocusCabinet(i),
        onView: (s) => cb.current.onView(s),
        onFatal: (e) => cb.current.onFatal(e),
        // Synchronous, inside the render frame (after controls.update + render): no lag, no React state.
        onFrame: () => { if (layer.current) overlay.current.paint(layer.current, rr, cb.current) },
      }, cb.current.reducedMotion)
    } catch (e) {
      canvas.remove()
      cb.current.onFatal(e instanceof Error ? e : new Error(String(e)))
      return
    }
    r.current = rr
    if (import.meta.env.DEV) (window as unknown as { __row3d?: RowRenderer }).__row3d = rr // perf checks only
    const ro = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(() => rr.resize())
    ro?.observe(canvas)
    rr.resize()
    return () => { ro?.disconnect(); rr.dispose(); canvas.remove(); r.current = null }
  }, [])

  useEffect(() => {
    const rr = r.current
    if (!rr) return
    rr.setData(p.scene)
    if (!rr.posed) {
      rr.posed = true
      const { side, cabinet } = cb.current.initial
      rr.preset(side, true)
      if (cabinet != null) rr.focusCabinet(cabinet, true)
    }
  }, [p.scene])
  useEffect(() => { r.current?.setSelected(p.selectedId) }, [p.selectedId, p.scene])
  useEffect(() => { r.current?.setHighlight(p.highlight) }, [p.highlight, p.scene])
  useEffect(() => { r.current?.invalidate() }, [p.tag, p.cabinetLabels, p.marker, p.rowName])

  useImperativeHandle(ref, () => ({
    flip: () => r.current?.flip(),
    setSide: (s) => r.current?.setSide(s),
    preset: (k) => r.current?.preset(k),
    focusCabinet: (i) => r.current?.focusCabinet(i),
    zoom: (f) => r.current?.zoom(f),
    stats: () => r.current?.stats() ?? null,
  }), [])

  return (
    <div className="r3d-stage" ref={hostRef}>
      {/* Children are managed imperatively by Overlay (one span per label key). */}
      <div className="r3d-labels" aria-hidden="true" ref={layer}>
        {/* Selection outline (design-system --select: 2 px #ffb000 + glow), points written per frame. */}
        <svg className="r3d-sel-svg" width="100%" height="100%"><polygon className="r3d-sel-outline" points="" /></svg>
      </div>
    </div>
  )
})
export default Row3DView

/** Imperative label layer: spans keyed by label, transforms written in the render frame. */
class Overlay {
  private spans = new Map<string, { el: HTMLSpanElement; w: number; h: number; text: string }>()
  private visible = new Set<string>()

  paint(root: HTMLElement, rr: RowRenderer, p: Props) {
    const scene = rr.sceneData
    const specs: LabelSpec[] = scene ? labelSpecs(scene, { rowName: p.rowName, names: p.cabinetLabels, side: rr.currentSide, tag: p.tag, marker: p.marker, box: (id) => rr.box(id) }) : []
    const live = new Set(specs.map((s) => s.key))
    for (const [k, s] of this.spans) if (!live.has(k)) { s.el.remove(); this.spans.delete(k); this.visible.delete(k) }
    const anchors = specs.map((spec) => {
      let s = this.spans.get(spec.key)
      if (!s || s.text !== spec.text) {
        s?.el.remove()
        const el = document.createElement('span')
        el.className = spec.cls
        el.textContent = spec.text
        root.appendChild(el)
        s = { el, w: el.offsetWidth, h: el.offsetHeight, text: spec.text } // measured once, unscaled
        this.spans.set(spec.key, s)
      }
      return { ...spec, w: s.w, h: s.h }
    })
    const { width, height } = rr.viewport
    const poly = root.querySelector<SVGPolygonElement>('.r3d-sel-outline')
    const b = p.marker != null && scene ? rr.box(p.marker) : undefined
    const pts = b ? faceOutline(b, rr.currentSide, rr.viewProj.elements, width, height) : null
    if (poly) {
      poly.setAttribute('points', pts ? pts.map((q) => `${q.x.toFixed(1)},${q.y.toFixed(1)}`).join(' ') : '')
      poly.style.visibility = pts ? 'visible' : 'hidden'
    }
    const { placements, visible } = layoutLabels(anchors, rr.viewProj.elements, width, height, this.visible)
    this.visible = visible
    for (const pl of placements) {
      const el = this.spans.get(pl.key)!.el
      el.style.transform = `translate3d(${pl.x.toFixed(1)}px, ${pl.y.toFixed(1)}px, 0) translate(-50%, -50%) scale(${pl.scale.toFixed(3)})`
      el.style.visibility = pl.visible ? 'visible' : 'hidden'
    }
  }
}
