export type DocumentDirection = 'ltr' | 'rtl'

const RTL_LANGUAGE_FAMILIES = new Set(['ar', 'fa', 'he', 'iw', 'ps', 'sd', 'ug', 'ur', 'yi'])

export function getDocumentDirection(languageTag?: string | null): DocumentDirection {
  const primaryLanguage = String(languageTag || '')
    .trim()
    .toLowerCase()
    .split(/[-_]/)[0]

  return RTL_LANGUAGE_FAMILIES.has(primaryLanguage) ? 'rtl' : 'ltr'
}
