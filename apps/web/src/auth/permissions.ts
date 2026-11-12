// Role → UI capability map, mirroring the API's require_role() checks
// (apps/api: ADMIN / TECH / ANY_ROLE). The API stays authoritative (403).
export type Action =
  | 'device.write' // create, edit, move/place devices
  | 'device.delete' // soft delete (admin only; hard delete is off)
  | 'device.import'
  | 'device.export'
  | 'deviceType.create'
  | 'profile.publish' // publish, retire, new version, delete (admin)
  | 'rack.move'
  | 'cabinetProfile.write' // create, edit, publish, retire, un-retire, clone, delete cabinet profiles (admin only, admin-setup.md §1)
  | 'job.write' // start, close, and reopen a job; intake uploads; fill-later queue actions (tech or admin)
  | 'admin' // /users, /audit-events, locations CRUD

const MATRIX: Record<string, Action[]> = {
  admin: ['device.write', 'device.delete', 'profile.publish', 'device.import', 'device.export', 'deviceType.create', 'rack.move', 'cabinetProfile.write', 'job.write', 'admin'],
  technician: ['device.write', 'device.import', 'device.export', 'deviceType.create', 'rack.move', 'job.write'],
  'read-only': ['device.export'],
}

export function can(role: string | undefined | null, action: Action): boolean {
  return !!role && (MATRIX[role] ?? []).includes(action)
}

export function roleLabel(role: string): string {
  return role === 'read-only' ? 'Read-only' : role[0].toUpperCase() + role.slice(1)
}
