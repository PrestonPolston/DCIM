import type { Device, DeviceCreate, DeviceType, Face, Rack } from '../../api/types'
import { DEFAULT_STATUS } from '../../lib/status'

/** Form state as strings (inputs); converted to the API body in toBody(). Add new fields here. */
export interface FormValues {
  host_name: string
  status: string
  serial_number: string
  device_type_id: string
  profile_id: string
  rack_id: string
  position_u: string
  face: Face
  rack: string
  /** UI-only until the API adds serial_unavailable / serial_note (not sent). */
  serial_unavailable: boolean
  serial_note: string
}

export type FormErrors = Partial<Record<keyof FormValues | 'placement', string>>

export interface SectionProps {
  values: FormValues
  set: (patch: Partial<FormValues>) => void
  errors: FormErrors
  touch: (field: keyof FormValues) => void
  lookups: { deviceTypes: DeviceType[]; racks: Rack[]; rackLabel: (r: Rack) => string }
  /** Location is fixed by the caller (e.g. a drop on an RU); shown as text. */
  locationText?: string
  /** Profile chosen up front (palette drop / Choose profile): hide the Model and Profile pickers. */
  profileLocked?: boolean
  /** The device's current profile (edit mode): stays selectable even if it's no longer usable. */
  initialProfileId?: number | null
}

export function initialValues(start: Partial<Device | DeviceCreate>): FormValues {
  const str = (v: unknown) => (v == null ? '' : String(v))
  return {
    host_name: start.host_name ?? '',
    status: start.status ?? DEFAULT_STATUS,
    serial_number: start.serial_number ?? '',
    device_type_id: str(start.device_type_id),
    profile_id: str(start.profile_id),
    rack_id: str(start.rack_id),
    position_u: str(start.position_u),
    face: start.face ?? 'front',
    rack: start.rack ?? '',
    serial_unavailable: false,
    serial_note: '',
  }
}

const num = (v: string) => (v.trim() === '' ? null : Number(v))
const text = (v: string) => v.trim() || null

export function toBody(v: FormValues): DeviceCreate {
  return {
    host_name: v.host_name.trim(),
    status: v.status,
    serial_number: v.serial_unavailable ? null : text(v.serial_number),
    device_type_id: num(v.device_type_id),
    profile_id: v.device_type_id ? num(v.profile_id) : null,
    rack_id: num(v.rack_id),
    position_u: v.rack_id ? num(v.position_u) : null,
    face: v.face,
    rack: text(v.rack),
  }
}

/**
 * Only host_name is required; placing in a cabinet also needs a profile. The placement check mirrors the API's own rule
 * (a racked device needs position_u and device_type_id; position needs a cabinet),
 * so we surface it before the API returns 422.
 */
export function validate(v: FormValues): FormErrors {
  const e: FormErrors = {}
  if (!v.host_name.trim()) e.host_name = 'Hostname is required.'
  // Placement needs a profile (API 422 profile_required). device_type_id alone = its default profile.
  if (v.rack_id && !v.device_type_id && !v.profile_id) e.device_type_id = 'Choose a profile to place this device in a cabinet.'
  if (v.rack_id && !v.position_u) e.placement = 'To put a device in a cabinet, also choose a position (RU), or leave the cabinet empty.'
  else if (!v.rack_id && v.position_u) e.placement = 'Choose a cabinet for this position, or clear the position.'
  if (v.position_u && !(Number(v.position_u) >= 1)) e.position_u = 'Position must be 1 or higher.'
  return e
}
