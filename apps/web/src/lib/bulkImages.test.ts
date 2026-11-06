import { describe, expect, it } from 'vitest'
import { expectedName, matchFiles, parseManifest, parseName, runQueue, type MatchProfile } from './bulkImages'

const P: MatchProfile[] = [
  { id: 1, deviceTypeId: 1, manufacturer: 'Dell', model: 'R650', name: 'Default', isDefault: true, uHeight: 1 },
  { id: 2, deviceTypeId: 1, manufacturer: 'Dell', model: 'R650', name: 'GPU', isDefault: false, uHeight: 1 },
  { id: 3, deviceTypeId: 2, manufacturer: 'Cisco', model: 'Nexus 93180YC-FX3', name: 'Port front', isDefault: false, uHeight: 1 },
  { id: 4, deviceTypeId: 2, manufacturer: 'Cisco', model: 'Nexus 93180YC-FX3', name: 'Power front', isDefault: false, uHeight: 1 },
]

describe('bulk image matching', () => {
  it('parses face suffixes (front/rear/back) with any separator', () => {
    expect(parseName('Dell_R650_front.jpg')).toEqual({ stem: 'Dell_R650', face: 'front' })
    expect(parseName('dell r650-BACK.webp')).toEqual({ stem: 'dell r650', face: 'rear' })
    expect(parseName('photo.png').face).toBeNull()
  })
  it('matches model → default profile, variant names exactly, and flags problems', () => {
    const rows = matchFiles([
      'Dell_R650_front.jpg', 'dell-r650-gpu_rear.png', 'Cisco_Nexus-93180YC-FX3_front.jpg',
      'Cisco_Nexus-93180YC-FX3_Power-front_rear.jpg', 'Acme_X_front.jpg', 'Dell_R650_front.png', 'IMG_0001.jpg',
    ], P)
    expect(rows.map((r) => [r.profileId, r.face, r.error])).toEqual([
      [1, 'front', null],
      [2, 'rear', null],
      [null, 'front', 'Several profiles match: add the variant name'],
      [4, 'rear', null],
      [null, 'front', 'No matching profile'],
      [1, 'front', 'Duplicate: another file has this profile and face'],
      [null, null, 'Name must end in _front or _rear'],
    ])
  })
  it('a manifest overrides filename matching', () => {
    const m = parseManifest('filename,profile_id,face\nIMG_0001.jpg,3,front\nIMG_0002.jpg,99,rear\n')
    const rows = matchFiles(['IMG_0001.jpg', 'IMG_0002.jpg'], P, m)
    expect(rows[0]).toMatchObject({ profileId: 3, face: 'front', error: null })
    expect(rows[1].error).toMatch(/99 not found/)
  })
  it('runs at most N tasks at once', async () => {
    let live = 0, peak = 0
    await runQueue([1, 2, 3, 4, 5, 6, 7], 3, async () => { live++; peak = Math.max(peak, live); await new Promise((r) => setTimeout(r, 5)); live-- })
    expect(peak).toBe(3)
  })
  it('suggests file names', () => {
    expect(expectedName(P[3], 'rear')).toBe('Cisco_Nexus-93180YC-FX3_Power-front_rear.jpg')
    expect(expectedName(P[0], 'front')).toBe('Dell_R650_front.jpg')
  })
})
