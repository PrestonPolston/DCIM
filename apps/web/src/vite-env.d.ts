/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL?: string
  /** Set to 'false' to use the in-memory job-intake mock (wizard screenshots / local demo). */
  readonly VITE_JOB_INTAKE_LIVE?: string
  /** Set to 'true' when Backend ships open-item write routes. */
  readonly VITE_JOB_INTAKE_ITEM_WRITES?: string
  /** Set to 'true' when Backend ships CSV import / preview / commit routes. */
  readonly VITE_JOB_INTAKE_IMPORTS?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
