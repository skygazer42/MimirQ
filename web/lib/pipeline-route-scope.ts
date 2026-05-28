export const PIPELINE_ROUTE_PREFIXES = [
  '/datasets',
  '/knowledge',
  '/parsing',
  '/chunk-preview',
  '/settings',
  '/data-governance',
] as const

function matchesPipelinePrefix(pathname: string): boolean {
  return PIPELINE_ROUTE_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`)
  )
}

export function normalizePipelinePathname(pathname: string): string {
  const raw = String(pathname || '').trim() || '/'
  if (matchesPipelinePrefix(raw)) return raw

  const segments = raw.split('/').filter(Boolean)
  if (segments.length < 2) return raw

  const withoutLocale = `/${segments.slice(1).join('/')}`
  return matchesPipelinePrefix(withoutLocale) ? withoutLocale : raw
}

export function needsPipelineProvidersForPathname(pathname: string): boolean {
  return matchesPipelinePrefix(normalizePipelinePathname(pathname))
}
