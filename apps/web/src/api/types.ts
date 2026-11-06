// Mirrors docs/API.md v0.1 and apps/api/openapi.json.

export type Face = 'front' | 'rear'

export interface DeviceCreate {
  host_name: string
  /** Legacy free-text rack label (optional). */
  rack?: string | null
  status?: string
  /** Vendor serial or asset tag; unique when set. */
  serial_number?: string | null
  device_type_id?: number | null
  /** Specific profile of the device type; null = the type's default profile. */
  profile_id?: number | null
  rack_id?: number | null
  /** Lowest occupied U, 1-based. Requires rack_id and device_type_id. */
  position_u?: number | null
  face?: Face
}

/** Why a placed device is flagged (D31/D32): e.g. 'placed_without_profile', 'profile_not_published'. */
export interface NeedsReview {
  needs_review?: boolean | null
  needs_review_reason?: string | null
}

export interface Device extends DeviceCreate, NeedsReview {
  id: number
  status: string
}

/** PATCH body; `recommission: true` is required to move a Decom device back to Install/Active. */
export type DeviceUpdate = Partial<DeviceCreate> & { status?: string; recommission?: boolean }

/** API Site = UI "Building" (docs/API.md aliases building_id). */
export interface Site { id: number; name: string; address?: string | null; is_default?: boolean }
export interface Hall { id: number; site_id: number; name: string }
export interface Row { id: number; hall_id: number; name: string }
export interface Rack {
  id: number; row_id: number; name: string; u_height: number
  /** Read-only, = its row's hall (P1-10, f2dab41). */
  hall_id?: number
  pos_x?: number | null; pos_y?: number | null; orientation?: Orientation | null
  /** Rack orientation, falling back to its row's. */
  effective_orientation?: Orientation | null
}
export interface DeviceType { id: number; manufacturer: string; name: string; u_height: number; is_full_depth: boolean }

/** A page of a list endpoint; total comes from X-Total-Count. */
export interface Page<T> { items: T[]; total: number }

export interface ListParams { limit?: number; offset?: number; q?: string }
export interface DeviceListParams extends ListParams { rack_id?: number; device_type_id?: number; status?: string; unplaced?: boolean; needs_review?: boolean }

export type Orientation = 'N' | 'E' | 'S' | 'W'

/** GET /halls/{id}/layout */
export interface HallLayoutRack {
  id: number; row_id: number; name: string; u_height: number
  pos_x: number | null; pos_y: number | null; orientation: Orientation | null
  effective_orientation?: Orientation | null
  device_count: number; u_used: number; u_free: number
}
export interface HallLayoutRow {
  id: number; hall_id: number; name: string
  pos_x: number | null; pos_y: number | null; orientation: Orientation | null
  racks: HallLayoutRack[]
}
export interface HallLayout {
  id: number; site_id: number; name: string; rows: HallLayoutRow[]
  /** Hall plan hints (null = none): aisle runs along x or y; odd rows on the low/high side. */
  aisle_axis?: 'x' | 'y' | null; odd_side?: 'low' | 'high' | null
}

/** GET /racks/{id}/elevation */
export interface ElevationApiDevice extends NeedsReview {
  id: number; host_name: string; status: string; serial_number: string | null
  position_u: number; top_u: number; face: Face
  /** Null for a pre-policy device placed without a type/profile (drawn 1U, both faces). */
  device_type: DeviceType | null
  profile_id?: number | null
  serial_unavailable?: boolean | null
  serial_note?: string | null
  effective_asset_type?: string | null
  connection_count?: number
  /** {url, thumb_url} | null; read only via api/profiles.ts frontImageOf(). */
  effective_front_image?: { url: string; thumb_url: string } | null
}
export interface RackElevationResponse {
  id: number; row_id: number; name: string; u_height: number; u_used: number; u_free: number
  orientation?: Orientation | null; effective_orientation?: Orientation | null
  devices: ElevationApiDevice[]
}

export type Role = 'admin' | 'technician' | 'read-only'
/** GET /auth/me, POST /auth/login, POST /auth/change-password */
export interface Me {
  id: number; email: string; display_name: string | null; role: Role | string
  must_change_password: boolean; csrf_token: string
}
export interface AuthProvider { id: string; kind: string; name: string }

/** GET /device-types/{id}/profiles (subset used by the UI). */
export interface DeviceProfile { id: number; device_type_id: number; name: string; is_default: boolean; u_height: number; is_full_depth?: boolean }
