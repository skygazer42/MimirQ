import type { AxiosHeaders } from 'axios'

const LANGUAGE_TAG_PATTERN = /^[A-Za-z]{1,8}(?:-[A-Za-z0-9]{1,8})*$/

type NavigatorLike = {
  languages?: readonly string[]
  language?: string
}

export function normalizeLanguageTag(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined
  const tag = value.trim()
  return LANGUAGE_TAG_PATTERN.test(tag) ? tag : undefined
}

export function resolveBrowserPreferredLanguage(
  navigatorLike: NavigatorLike | undefined = globalThis.navigator,
): string | undefined {
  if (navigatorLike === undefined) return undefined
  if (Array.isArray(navigatorLike.languages)) {
    for (const candidate of navigatorLike.languages) {
      const tag = normalizeLanguageTag(candidate)
      if (tag !== undefined) return tag
    }
  }
  return normalizeLanguageTag(navigatorLike.language)
}

export function withPreferredLanguageHeader(
  headers: Record<string, string>,
  preferredLanguage: string | undefined = resolveBrowserPreferredLanguage(),
): Record<string, string> {
  if (!preferredLanguage) return headers
  if (Object.keys(headers).some((name) => name.toLowerCase() === 'accept-language')) return headers
  return {
    ...headers,
    'Accept-Language': preferredLanguage,
  }
}

export function applyPreferredLanguageAxiosHeader(
  headers: AxiosHeaders,
  preferredLanguage: string | undefined = resolveBrowserPreferredLanguage(),
): void {
  if (!preferredLanguage) return
  if (headers.has('Accept-Language')) return
  headers.set('Accept-Language', preferredLanguage)
}
