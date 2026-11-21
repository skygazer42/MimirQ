import { getDocumentDirection } from './document-direction'
import { normalizeLanguageTag } from './preferred-language'

export const DEFAULT_DOCUMENT_LANGUAGE = 'zh-CN'

type HeaderLookup = {
  get(name: string): string | null
}

function normalizeHeaderLanguageTag(value?: string | null): string | undefined {
  if (typeof value !== 'string') return undefined

  return normalizeLanguageTag(value.split(';', 1)[0])
}

function resolveRequestDocumentLanguage(
  requestHeaders?: HeaderLookup | null,
  fallbackLanguage = DEFAULT_DOCUMENT_LANGUAGE,
): string {
  const headerCandidates = [
    requestHeaders?.get('x-mimirq-lang'),
    requestHeaders?.get('x-app-lang'),
    ...(requestHeaders?.get('accept-language')?.split(',') ?? []),
  ]

  for (const candidate of headerCandidates) {
    const languageTag = normalizeHeaderLanguageTag(candidate)
    if (languageTag !== undefined) return languageTag
  }

  return normalizeHeaderLanguageTag(fallbackLanguage) ?? DEFAULT_DOCUMENT_LANGUAGE
}

export function resolveRequestDocumentSettings(
  requestHeaders?: HeaderLookup | null,
  fallbackLanguage = DEFAULT_DOCUMENT_LANGUAGE,
): { dir: ReturnType<typeof getDocumentDirection>; lang: string } {
  const lang = resolveRequestDocumentLanguage(requestHeaders, fallbackLanguage)
  return {
    dir: getDocumentDirection(lang),
    lang,
  }
}
