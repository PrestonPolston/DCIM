import '@testing-library/jest-dom/vitest'
import { afterEach, beforeEach } from 'vitest'
import { cleanup } from '@testing-library/react'
import { CABINET_PROFILE_API, resetCabinetMock } from '../api/cabinetProfiles'
import { HOME_API } from '../api/home'

// The app talks to the real /cabinet-profiles (live = true); unit tests use the in-memory mock that
// mirrors the same contract. Start each test empty so device-profile tests see no cabinet rows;
// cabinet tests seed CABINET_FIXTURES themselves.
beforeEach(() => { CABINET_PROFILE_API.live = false; HOME_API.live = false; resetCabinetMock({ rows: [] }) })
afterEach(() => cleanup())
