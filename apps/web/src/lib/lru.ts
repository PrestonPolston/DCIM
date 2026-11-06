// Size-and-count capped LRU (row-3d.md §7: ≤ 64 full-size textures, ≤ 48 MB GPU).
// Generic so the three.js texture cache stays a thin wrapper and this is unit-testable.
export class LruCache<V> {
  private map = new Map<string, { value: V; bytes: number }>()
  private total = 0
  private readonly maxItems: number
  private readonly maxBytes: number
  private readonly onEvict: (key: string, value: V) => void
  constructor(maxItems: number, maxBytes: number, onEvict: (key: string, value: V) => void = () => {}) {
    this.maxItems = maxItems; this.maxBytes = maxBytes; this.onEvict = onEvict
  }
  get size() { return this.map.size }
  get bytes() { return this.total }
  has(key: string) { return this.map.has(key) }
  get(key: string): V | undefined {
    const e = this.map.get(key)
    if (!e) return undefined
    this.map.delete(key); this.map.set(key, e) // most recent last
    return e.value
  }
  set(key: string, value: V, bytes: number) {
    const old = this.map.get(key)
    if (old) { this.total -= old.bytes; this.map.delete(key) }
    this.map.set(key, { value, bytes }); this.total += bytes
    while (this.map.size > this.maxItems || (this.total > this.maxBytes && this.map.size > 1)) {
      const [k, e] = this.map.entries().next().value as [string, { value: V; bytes: number }]
      this.map.delete(k); this.total -= e.bytes
      this.onEvict(k, e.value)
    }
  }
  clear() {
    for (const [k, e] of this.map) this.onEvict(k, e.value)
    this.map.clear(); this.total = 0
  }
}

/** GPU bytes for an RGBA texture with a full mip chain (≈ 4/3). */
export const textureBytes = (w: number, h: number) => Math.round(w * h * 4 * 4 / 3)
export const TEXTURE_CAP = { items: 64, bytes: 48 * 1024 * 1024 } as const
