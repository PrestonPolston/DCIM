/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL?: string
  /** Set to 'false' to use the in-memory job-intake mock (wizard screenshots / local demo). */
  readonly VITE_JOB_INTAKE_LIVE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
