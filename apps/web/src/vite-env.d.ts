/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL?: string
  /** Set to 'false' to use the in-memory job-intake mock (wizard screenshots / local demo). */
  readonly VITE_JOB_INTAKE_LIVE?: string
  /** Set to 'false' to disable open-item writes against a live API that has the routes. */
  readonly VITE_JOB_INTAKE_ITEM_WRITES?: string
  /** Set to 'false' to disable ePIF import against a live API that has the routes. */
  readonly VITE_JOB_INTAKE_IMPORTS?: string
  /** Set to 'true' when Backend ships cable-matrix import. */
  readonly VITE_JOB_INTAKE_CABLE_IMPORTS?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
