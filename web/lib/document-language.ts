import { getDocumentDirection } from './document-direction'

export const DEFAULT_DOCUMENT_LANGUAGE = 'zh-CN'

const LANGUAGE_TAG_PATTERN = /^[A-Za-z]{1,8}(?:-[A-Za-z0-9]{1,8})*$/

type HeaderLookup = {
  get(name: string): string | null
}

function normalizeLanguageTag(value?: string | null): string | undefined {
  if (typeof value !== 'string') return undefined

  const candidate = value
    .trim()
    .split(';', 1)[0]
    ?.trim()

  if (!candidate || !LANGUAGE_TAG_PATTERN.test(candidate)) return undefined
  return candidate
}

export function resolveRequestDocumentLanguage(
  requestHeaders?: HeaderLookup | null,
  fallbackLanguage = DEFAULT_DOCUMENT_LANGUAGE
): string {
  const headerCandidates = [
    requestHeaders?.get('x-mimirq-lang'),
    requestHeaders?.get('x-app-lang'),
    ...(requestHeaders?.get('accept-language')?.split(',') ?? []),
  ]

  for (const candidate of headerCandidates) {
    const languageTag = normalizeLanguageTag(candidate)
    if (languageTag) return languageTag
  }

  return normalizeLanguageTag(fallbackLanguage) ?? DEFAULT_DOCUMENT_LANGUAGE
}

export function resolveRequestDocumentSettings(
  requestHeaders?: HeaderLookup | null,
  fallbackLanguage = DEFAULT_DOCUMENT_LANGUAGE
): { dir: ReturnType<typeof getDocumentDirection>; lang: string } {
  const lang = resolveRequestDocumentLanguage(requestHeaders, fallbackLanguage)
  return {
    dir: getDocumentDirection(lang),
    lang,
  }
}
