// Imperative three.js renderer for one row (row-3d.md, ROW_3D_SPIKE.md). Imported only
// from the lazy Row3DView chunk, so three.js costs nothing until a row opens in 3D.
// Draw calls: frames (1) + RU voids (1) + floor (1) + 3 per face-texture group (shared
// across every device of the same profile images) + selection/hover rings.
import * as THREE from 'three'
import { contextProblem } from '../../lib/webgl'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import {
  BASE_Y, CAB_D, CAB_W, cabinetPose, flipPose, groupBoxes, isGenericKey, orbitPose, presetPose, RAIL_F, RAIL_R, ROOF_H, RU_M,
  sideOf, STATUS_TINT, lerpPose, type Box3D, type CameraPose, type Face3D, type RowScene, type V3,
  closeUpCabinets,
} from '../../lib/row3d'
import { LruCache, TEXTURE_CAP, textureBytes } from '../../lib/lru'
import { genericArt } from './genericArt'

export interface RendererEvents {
  onPick: (deviceId: number | null) => void
  /** rect: the hovered cabinet's screen box in client px (the hover card must not cover it). */
  onHover: (deviceId: number | null, x: number, y: number, rect?: { left: number; top: number; right: number; bottom: number } | null) => void
  onFocusCabinet: (index: number) => void
  onView: (side: Face3D) => void
  /** Fired after every rendered frame (labels overlay re-projects). */
  onFrame?: () => void
  onFatal: (err: Error) => void
}

const SELECT = 0xffb000 // --focus / --select (design-system.md)
const HOVER = 0xffffff
const SIDE = 0x3a3f47
const FRAME = 0x23272e
const BG = 0x2a3038
const ANIM_MS = 900

function unitBox() {
  // Groups: 0 = sides/top/bottom, 1 = +z face, 2 = −z face → 3 draw calls per instanced group.
  const g = new THREE.BoxGeometry(1, 1, 1)
  g.clearGroups()
  g.addGroup(0, 24, 0)
  g.addGroup(24, 6, 1)
  g.addGroup(30, 6, 2)
  return g
}

function voidTexture() {
  const cv = document.createElement('canvas'); cv.width = 64; cv.height = 53 * 8
  const g = cv.getContext('2d')!
  g.fillStyle = '#0d0f12'; g.fillRect(0, 0, 64, cv.height); g.fillStyle = '#262b33'
  for (let i = 0; i <= 53; i++) g.fillRect(0, i * 8, 64, 1)
  const t = new THREE.CanvasTexture(cv); t.colorSpace = THREE.SRGBColorSpace
  return t
}

export class RowRenderer {
  private renderer: THREE.WebGLRenderer
  private scene = new THREE.Scene()
  private camera = new THREE.PerspectiveCamera(40, 1, 0.05, 80)
  private controls: OrbitControls
  private root = new THREE.Group()
  private boxGeo = unitBox()
  private sideMat = new THREE.MeshLambertMaterial({ color: SIDE })
  private mats = new Map<string, THREE.MeshLambertMaterial>()
  private thumbs = new Map<string, THREE.Texture>()
  private originals: LruCache<THREE.Texture>
  private loader = new THREE.TextureLoader()
  private meshes: THREE.InstancedMesh[] = []
  private data: RowScene | null = null
  private byId = new Map<number, Box3D>()
  private selected: number | null = null
  private hovered: number | null = null
  private selRing: THREE.Group
  private hoverRing: THREE.LineSegments
  private highlight: 'none' | 'status' = 'none'
  private anim: { from: CameraPose; to: CameraPose; t0: number; orbit: boolean } | null = null
  private dirty = true
  private disposed = false
  private side: Face3D = 'front'
  private down: { x: number; y: number; t: number } | null = null
  private hoverRaf = 0
  private ray = new THREE.Raycaster()
  /** Set by the view once the initial camera (deep link / side) is applied. */
  posed = false

  private canvas: HTMLCanvasElement
  private ev: RendererEvents
  private reducedMotion: boolean

  constructor(canvas: HTMLCanvasElement, ev: RendererEvents, reducedMotion = false) {
    this.canvas = canvas; this.ev = ev; this.reducedMotion = reducedMotion
    // Create + check the context ourselves: three.js dereferences getShaderPrecisionFormat() without
    // a null check, which is the "reading 'precision'" crash on a lost/blocked context.
    const attrs: WebGLContextAttributes = { antialias: true, powerPreference: 'high-performance', alpha: false }
    const gl = (canvas.getContext('webgl2', attrs) ?? canvas.getContext('webgl', attrs)) as WebGL2RenderingContext | null
    const problem = contextProblem(gl)
    if (problem) throw new Error(problem)
    this.renderer = new THREE.WebGLRenderer({ canvas, context: gl!, antialias: true, powerPreference: 'high-performance' })
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
    this.renderer.outputColorSpace = THREE.SRGBColorSpace
    this.loader.setCrossOrigin('use-credentials')
    this.originals = new LruCache<THREE.Texture>(TEXTURE_CAP.items, TEXTURE_CAP.bytes, (key, tex) => {
      const thumb = this.thumbs.get(key)
      const m = this.mats.get(key)
      if (m && thumb) { m.map = thumb; m.needsUpdate = true; this.dirty = true }
      tex.dispose()
    })
    this.scene.background = new THREE.Color(BG)
    this.scene.fog = new THREE.Fog(BG, 16, 44)
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x556070, 2.6))
    const sun = new THREE.DirectionalLight(0xffffff, 1.4); sun.position.set(3, 6, 5); this.scene.add(sun)
    const back = new THREE.DirectionalLight(0xffffff, 1.0); back.position.set(-3, 5, -6); this.scene.add(back)
    this.scene.add(this.root)

    const edges = new THREE.EdgesGeometry(new THREE.BoxGeometry(1, 1, 1))
    this.selRing = new THREE.Group()
    this.selRing.add(new THREE.LineSegments(edges, new THREE.LineBasicMaterial({ color: SELECT, depthTest: false, transparent: true })))
    // Additive halo carries the visibility (WebGL lines are always 1 px).
    this.selRing.add(new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshBasicMaterial({
      color: SELECT, transparent: true, opacity: 0.28, depthWrite: false, blending: THREE.AdditiveBlending,
    })))
    this.selRing.visible = false
    this.selRing.renderOrder = 10
    this.hoverRing = new THREE.LineSegments(edges, new THREE.LineBasicMaterial({ color: HOVER, transparent: true, opacity: 0.7, depthTest: false }))
    this.hoverRing.visible = false
    this.scene.add(this.selRing, this.hoverRing)

    this.controls = new OrbitControls(this.camera, canvas)
    this.controls.enableDamping = !reducedMotion
    this.controls.dampingFactor = 0.08
    this.controls.minDistance = 0.6
    this.controls.maxDistance = 22
    this.controls.maxPolarAngle = (89 * Math.PI) / 180
    this.controls.screenSpacePanning = true
    this.controls.addEventListener('change', () => { this.dirty = true })

    canvas.addEventListener('webglcontextlost', this.onLost)
    canvas.addEventListener('pointerdown', this.onDown)
    canvas.addEventListener('pointerup', this.onUp)
    canvas.addEventListener('pointermove', this.onMove)
    canvas.addEventListener('pointerleave', this.onLeave)
    canvas.addEventListener('dblclick', this.onDbl)
    this.renderer.setAnimationLoop(this.tick)
  }

  // ---- data -----------------------------------------------------------------
  setData(data: RowScene) {
    this.clearRow()
    this.data = data
    this.byId = new Map(data.boxes.map((b) => [b.deviceId, b]))
    this.buildCabinets(data)
    const m = new THREE.Matrix4(), q = new THREE.Quaternion(), p = new THREE.Vector3(), s = new THREE.Vector3()
    for (const [, list] of groupBoxes(data.boxes)) {
      const mesh = new THREE.InstancedMesh(this.boxGeo, [this.sideMat, this.material(list[0].plusZ), this.material(list[0].minusZ)], list.length)
      list.forEach((b, i) => { mesh.setMatrixAt(i, m.compose(p.set(b.cx, b.cy, b.cz), q, s.set(b.w, b.h, b.d))) })
      mesh.userData.ids = list.map((b) => b.deviceId)
      mesh.userData.boxes = list
      this.root.add(mesh)
      this.meshes.push(mesh)
    }
    this.applyHighlight()
    this.setSelected(this.selected)
    this.dirty = true
  }

  private buildCabinets(data: RowScene) {
    // Frame pieces (plinth, roof, 4 posts, 2 side panels) for every cabinet → ONE instanced mesh.
    const pieces: [V3, V3][] = []
    for (const c of data.cabinets) {
      const top = c.height
      pieces.push([[c.x, BASE_Y / 2, 0], [CAB_W, BASE_Y, CAB_D]])
      pieces.push([[c.x, top - ROOF_H / 2, 0], [CAB_W, ROOF_H, CAB_D]])
      for (const sx of [-1, 1]) for (const sz of [-1, 1]) pieces.push([[c.x + sx * (CAB_W / 2 - 0.02), top / 2, sz * (CAB_D / 2 - 0.02)], [0.04, top, 0.04]])
      for (const sx of [-1, 1]) pieces.push([[c.x + sx * (CAB_W / 2 - 0.004), top / 2, 0], [0.008, top - 0.02, CAB_D - 0.06]])
    }
    const frame = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshLambertMaterial({ color: FRAME }), pieces.length)
    const m = new THREE.Matrix4(), q = new THREE.Quaternion(), p = new THREE.Vector3(), s = new THREE.Vector3()
    pieces.forEach(([pos, size], i) => frame.setMatrixAt(i, m.compose(p.set(...pos), q, s.set(...size))))
    frame.userData.frame = true
    this.root.add(frame)
    // RU void planes at both rails (front faces +z, rear faces −z) → ONE instanced mesh.
    const voidMat = new THREE.MeshBasicMaterial({ map: voidTexture(), side: THREE.DoubleSide })
    const voids = new THREE.InstancedMesh(new THREE.PlaneGeometry(1, 1), voidMat, data.cabinets.length * 2)
    data.cabinets.forEach((c, i) => {
      const h = c.uHeight * RU_M
      voids.setMatrixAt(i * 2, m.compose(p.set(c.x, BASE_Y + h / 2, RAIL_F - 0.001), q, s.set(CAB_W - 0.09, h, 1)))
      voids.setMatrixAt(i * 2 + 1, m.compose(p.set(c.x, BASE_Y + h / 2, RAIL_R + 0.001), q, s.set(CAB_W - 0.09, h, 1)))
    })
    this.root.add(voids)
    // Floor tiles (600 mm) under the row only.
    const cv = document.createElement('canvas'); cv.width = cv.height = 64
    const g = cv.getContext('2d')!; g.fillStyle = '#4b525c'; g.fillRect(0, 0, 64, 64); g.strokeStyle = '#3c424a'; g.lineWidth = 2; g.strokeRect(0, 0, 64, 64)
    const ft = new THREE.CanvasTexture(cv); ft.wrapS = ft.wrapT = THREE.RepeatWrapping; ft.colorSpace = THREE.SRGBColorSpace
    const fw = data.width + 6, fd = 8
    ft.repeat.set(fw / 0.6, fd / 0.6)
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(fw, fd), new THREE.MeshLambertMaterial({ map: ft }))
    floor.rotation.x = -Math.PI / 2
    this.root.add(floor)
  }

  /** One shared material per face texture key (profile image thumb or generic art). */
  private material(key: string) {
    let mat = this.mats.get(key)
    if (mat) return mat
    mat = new THREE.MeshLambertMaterial({ color: 0xffffff })
    this.mats.set(key, mat)
    if (isGenericKey(key)) {
      const [, face, asset] = key.split(':')
      const t = new THREE.CanvasTexture(genericArt(asset, face as Face3D))
      t.colorSpace = THREE.SRGBColorSpace
      this.thumbs.set(key, t)
      mat.map = t
    } else {
      // Thumb first; until it arrives the face is a neutral grey box.
      mat.color.set(0x6a707a)
      this.loader.load(key, (t) => {
        if (this.disposed) { t.dispose(); return }
        t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4
        this.thumbs.set(key, t)
        mat!.map = t; mat!.color.set(0xffffff); mat!.needsUpdate = true; this.dirty = true
      }, undefined, () => { /* keep the grey box: a missing thumb never breaks the row */ })
    }
    return mat
  }

  /** Upgrade the focused cabinet and its neighbours to close-up textures (tex_url; LRU: 64 textures / 48 MB). */
  private upgrade(cabIndex: number) {
    if (!this.data) return
    const keys = new Set<string>()
    // Neighbours first, focused last: LRU recency then evicts neighbours before the focused cabinet.
    for (const ci of closeUpCabinets(cabIndex, this.data.cabinets.length).reverse())
      for (const b of this.data.boxes) if (b.cabIndex === ci) { keys.add(b.plusZ); keys.add(b.minusZ) }
    for (const key of keys) {
      const url = this.data.full[key]
      if (!url) continue
      const hit = this.originals.get(key)
      if (hit) continue
      this.loader.load(url, (t) => {
        if (this.disposed) { t.dispose(); return }
        t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4
        const img = t.image as { width?: number; height?: number }
        this.originals.set(key, t, textureBytes(img.width ?? 1024, img.height ?? 189))
        const m = this.mats.get(key)
        if (m && this.originals.has(key)) { m.map = t; m.needsUpdate = true; this.dirty = true }
      }, undefined, () => {})
    }
  }

  // ---- selection / highlight -----------------------------------------------
  setSelected(id: number | null) {
    this.selected = id
    const b = id == null ? undefined : this.byId.get(id)
    this.selRing.visible = !!b
    if (b) { this.selRing.position.set(b.cx, b.cy, b.cz); this.selRing.scale.set(b.w + 0.008, b.h + 0.006, b.d + 0.008) }
    this.dirty = true
  }

  private setHovered(id: number | null) {
    if (id === this.hovered) return
    this.hovered = id
    const b = id == null || id === this.selected ? undefined : this.byId.get(id)
    this.hoverRing.visible = !!b
    if (b) { this.hoverRing.position.set(b.cx, b.cy, b.cz); this.hoverRing.scale.set(b.w + 0.004, b.h + 0.003, b.d + 0.004) }
    this.dirty = true
  }

  /** Status highlight via per-instance colour: no texture reloads, one small buffer upload. */
  setHighlight(mode: 'none' | 'status') { this.highlight = mode; this.applyHighlight() }
  private applyHighlight() {
    const c = new THREE.Color()
    for (const mesh of this.meshes) {
      const boxes = mesh.userData.boxes as Box3D[]
      boxes.forEach((b, i) => {
        if (this.highlight === 'status') c.setHex(STATUS_TINT[b.status] ?? 0x8a919c).lerp(new THREE.Color(0xffffff), 0.35)
        else c.setHex(0xffffff)
        mesh.setColorAt(i, c)
      })
      if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true
    }
    this.dirty = true
  }

  // ---- camera ---------------------------------------------------------------
  private pose(): CameraPose {
    const p = this.camera.position, t = this.controls.target
    return { position: [p.x, p.y, p.z], target: [t.x, t.y, t.z] }
  }
  private goTo(to: CameraPose, orbit = false) {
    if (this.reducedMotion) { this.apply(to); return }
    this.anim = { from: this.pose(), to, t0: performance.now(), orbit }
  }
  private apply(p: CameraPose) {
    this.camera.position.set(...p.position)
    this.controls.target.set(...p.target)
    this.controls.update()
    this.dirty = true
    const s = sideOf(p)
    if (s !== this.side) { this.side = s; this.ev.onView(s) }
  }
  preset(kind: 'front' | 'rear' | 'reset' | 'fit', instant = false) {
    if (!this.data) return
    const to = presetPose(kind === 'fit' ? this.side : kind, this.data, this.aspect())
    if (instant) this.apply(to); else this.goTo(to)
  }
  /** Flip to rear/front: an animated 180° orbit about the current target (row-3d.md §3). */
  flip() { this.goTo(flipPose(this.pose()), true) }
  setSide(side: Face3D) { if (side !== this.side) this.flip() }
  focusCabinet(index: number, instant = false) {
    const cab = this.data?.cabinets[index]
    if (!cab) return
    const to = cabinetPose(cab, this.side, this.aspect())
    if (instant) this.apply(to); else this.goTo(to)
    this.upgrade(index)
  }
  get currentSide() { return this.side }
  /** Keyboard +/-: dolly toward/away from the target (clamped by the controls). */
  zoom(factor: number) {
    const t = this.controls.target
    const off = this.camera.position.clone().sub(t).multiplyScalar(factor)
    const len = Math.min(this.controls.maxDistance, Math.max(this.controls.minDistance, off.length()))
    this.camera.position.copy(t).add(off.setLength(len))
    this.controls.update(); this.dirty = true
  }

  private aspect() { return this.canvas.clientWidth / Math.max(1, this.canvas.clientHeight) }
  resize() {
    const w = this.canvas.clientWidth, h = this.canvas.clientHeight
    if (!w || !h) return
    this.renderer.setSize(w, h, false)
    this.camera.aspect = w / h
    this.camera.updateProjectionMatrix()
    this.size = { w, h }
    this.dirty = true
  }
  private size = { w: 0, h: 0 }

  /** View-projection matrix of the last rendered frame (column-major). */
  readonly viewProj = new THREE.Matrix4()
  get viewport() { return { width: this.canvas.clientWidth, height: this.canvas.clientHeight } }
  get sceneData() { return this.data }
  /** Ask for a render (and thus an overlay pass) on the next animation frame. */
  invalidate() { this.dirty = true }
  /** World → CSS px in the canvas (for the HTML label/card overlay). null when behind the camera. */
  project(x: number, y: number, z: number): { x: number; y: number } | null {
    const v = new THREE.Vector3(x, y, z).project(this.camera)
    if (v.z > 1) return null
    return { x: (v.x + 1) / 2 * this.canvas.clientWidth, y: (1 - v.y) / 2 * this.canvas.clientHeight }
  }
  box(id: number) { return this.byId.get(id) }
  /** Screen bounding box (client px) of a cabinet's frame, from its 8 corners. */
  cabinetRect(index: number) {
    const c = this.data?.cabinets[index]
    if (!c) return null
    const r = this.canvas.getBoundingClientRect()
    let l = Infinity, t = Infinity, rt = -Infinity, b = -Infinity
    for (const x of [c.x - CAB_W / 2, c.x + CAB_W / 2]) for (const y of [0, c.height]) for (const z of [-CAB_D / 2, CAB_D / 2]) {
      const p = this.project(x, y, z)
      if (!p) continue
      l = Math.min(l, p.x); rt = Math.max(rt, p.x); t = Math.min(t, p.y); b = Math.max(b, p.y)
    }
    return Number.isFinite(l) ? { left: l + r.left, top: t + r.top, right: rt + r.left, bottom: b + r.top } : null
  }
  stats() {
    const i = this.renderer.info
    return { calls: i.render.calls, triangles: i.render.triangles, textures: i.memory.textures, geometries: i.memory.geometries, groups: this.meshes.length, originals: this.originals.size, originalBytes: this.originals.bytes }
  }

  // ---- loop / input -----------------------------------------------------------
  private tick = () => {
    if (this.anim) {
      const t = Math.min(1, (performance.now() - this.anim.t0) / ANIM_MS)
      this.apply(this.anim.orbit ? orbitPose(this.anim.from, t) : lerpPose(this.anim.from, this.anim.to, t))
      if (t >= 1) { this.apply(this.anim.to); this.anim = null }
    }
    if (this.controls.enableDamping) this.controls.update()
    // Size check in the frame itself (ResizeObserver fires after rAF, one frame late).
    if (this.canvas.clientWidth !== this.size.w || this.canvas.clientHeight !== this.size.h) this.resize()
    if (!this.dirty) return // render on demand
    this.dirty = false
    const s = sideOf(this.pose())
    if (s !== this.side) { this.side = s; this.ev.onView(s) }
    this.renderer.render(this.scene, this.camera)
    // Same frame, same camera as the pixels just drawn: the overlay re-projects synchronously.
    this.viewProj.multiplyMatrices(this.camera.projectionMatrix, this.camera.matrixWorldInverse)
    this.ev.onFrame?.()
  }

  private pickAt(clientX: number, clientY: number): { id: number | null; cab: number | null } {
    const r = this.canvas.getBoundingClientRect()
    const ndc = new THREE.Vector2(((clientX - r.left) / r.width) * 2 - 1, -((clientY - r.top) / r.height) * 2 + 1)
    this.ray.setFromCamera(ndc, this.camera)
    const hits = this.ray.intersectObjects(this.root.children, false)
    for (const h of hits) {
      const ids = h.object.userData.ids as number[] | undefined
      if (ids && h.instanceId != null) return { id: ids[h.instanceId], cab: this.byId.get(ids[h.instanceId])?.cabIndex ?? null }
      if (h.object.userData.frame || h.object instanceof THREE.InstancedMesh) {
        // Cabinet frame/void: nearest cabinet by x.
        const x = h.point.x
        const cabs = this.data?.cabinets ?? []
        const ci = cabs.reduce((best, c, i) => (Math.abs(c.x - x) < Math.abs(cabs[best].x - x) ? i : best), 0)
        return { id: null, cab: cabs.length ? ci : null }
      }
    }
    return { id: null, cab: null }
  }
  private onDown = (e: PointerEvent) => { this.down = { x: e.clientX, y: e.clientY, t: performance.now() } }
  private onUp = (e: PointerEvent) => {
    const d = this.down; this.down = null
    if (!d || e.button !== 0) return
    if (Math.hypot(e.clientX - d.x, e.clientY - d.y) > 6 || performance.now() - d.t > 600) return // orbit, not a tap
    this.ev.onPick(this.pickAt(e.clientX, e.clientY).id)
  }
  private onDbl = (e: MouseEvent) => {
    const { cab } = this.pickAt(e.clientX, e.clientY)
    if (cab != null) this.ev.onFocusCabinet(cab)
  }
  private onMove = (e: PointerEvent) => {
    if (e.pointerType !== 'mouse' || e.buttons) return
    const x = e.clientX, y = e.clientY
    cancelAnimationFrame(this.hoverRaf)
    this.hoverRaf = requestAnimationFrame(() => {
      const id = this.pickAt(x, y).id
      this.setHovered(id)
      const cab = id != null ? this.byId.get(id)?.cabIndex : undefined
      this.ev.onHover(id, x, y, cab != null ? this.cabinetRect(cab) : null)
    })
  }
  private onLeave = () => { cancelAnimationFrame(this.hoverRaf); this.setHovered(null); this.ev.onHover(null, 0, 0) }
  private onLost = (e: Event) => { e.preventDefault(); this.ev.onFatal(new Error('WebGL context lost')) }

  private clearRow() {
    for (const o of [...this.root.children]) {
      this.root.remove(o)
      const mesh = o as THREE.Mesh
      if (mesh.geometry && mesh.geometry !== this.boxGeo) mesh.geometry.dispose()
      const mats = Array.isArray(mesh.material) ? mesh.material : mesh.material ? [mesh.material] : []
      for (const m of mats) {
        if (m === this.sideMat || [...this.mats.values()].includes(m as THREE.MeshLambertMaterial)) continue
        ;(m as THREE.MeshBasicMaterial).map?.dispose(); m.dispose()
      }
      if (o instanceof THREE.InstancedMesh) o.dispose()
    }
    this.meshes = []
  }

  dispose() {
    this.disposed = true
    this.renderer.setAnimationLoop(null)
    cancelAnimationFrame(this.hoverRaf)
    const c = this.canvas
    c.removeEventListener('webglcontextlost', this.onLost)
    c.removeEventListener('pointerdown', this.onDown)
    c.removeEventListener('pointerup', this.onUp)
    c.removeEventListener('pointermove', this.onMove)
    c.removeEventListener('pointerleave', this.onLeave)
    c.removeEventListener('dblclick', this.onDbl)
    this.controls.dispose()
    this.clearRow()
    this.originals.clear()
    for (const t of this.thumbs.values()) t.dispose()
    for (const m of this.mats.values()) m.dispose()
    this.sideMat.dispose(); this.boxGeo.dispose()
    this.selRing.traverse((o) => { const m = o as THREE.Mesh; m.geometry?.dispose(); (m.material as THREE.Material | undefined)?.dispose() })
    ;(this.hoverRing.material as THREE.Material).dispose()
    this.renderer.dispose()
    this.renderer.forceContextLoss()
  }
}
