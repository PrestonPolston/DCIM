// mobile.md §3: identifiers (host names, serials) must not be auto-capitalized,
// auto-corrected or auto-filled by iOS Safari.
export const ID_INPUT = {
  autoCapitalize: 'off',
  autoCorrect: 'off',
  autoComplete: 'off',
  spellCheck: false,
  inputMode: 'text',
} as const

// RU / position fields: numeric keypad.
export const RU_INPUT = { inputMode: 'numeric', pattern: '[0-9]*' } as const
