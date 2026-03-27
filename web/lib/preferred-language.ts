import type { AxiosHeaders } from 'axios'

const LANGUAGE_TAG_PATTERN = /^[A-Za-z]{1,8}(?:-[A-Za-z0-9]{1,8})*$/

type NavigatorLike = {
  languages?: readonly string[]
  language?: string
}

function toValidLanguageTag(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined
  const tag = value.trim()
  if (!tag || !LANGUAGE_TAG_PATTERN.test(tag)) return undefined
  return tag
}

export function resolveBrowserPreferredLanguage(navigatorLike: NavigatorLike | undefined = globalThis.navigator): string | undefined {
  if (!navigatorLike) return undefined

  const candidates: unknown[] = []
  if (Array.isArray(navigatorLike.languages)) candidates.push(...navigatorLike.languages)
  candidates.push(navigatorLike.language)

  for (const candidate of candidates) {
    const tag = toValidLanguageTag(candidate)
    if (tag) return tag
  }
  return undefined
}

function hasHeaderIgnoreCase(headers: Record<string, string>, key: string): boolean {
  const lowered = key.toLowerCase()
  return Object.keys(headers).some((headerKey) => headerKey.toLowerCase() === lowered)
}

export function withPreferredLanguageHeader(
  headers: Record<string, string>,
  preferredLanguage: string | undefined = resolveBrowserPreferredLanguage()
): Record<string, string> {
  if (!preferredLanguage) return headers
  if (hasHeaderIgnoreCase(headers, 'Accept-Language')) return headers
  return {
    ...headers,
    'Accept-Language': preferredLanguage,
  }
}

export function applyPreferredLanguageAxiosHeader(
  headers: AxiosHeaders,
  preferredLanguage: string | undefined = resolveBrowserPreferredLanguage()
): void {
  if (!preferredLanguage) return
  if (headers.has('Accept-Language')) return
  headers.set('Accept-Language', preferredLanguage)
}
