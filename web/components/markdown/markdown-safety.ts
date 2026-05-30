import { toAbsoluteBackendUrl } from '@/lib/env'
import {
  isBlockedMarkdownImageTarget,
} from '@/lib/markdown-image-proxy'

const SAFE_LINK_PROTOCOLS = new Set(['http', 'https', 'mailto', 'tel'])
const SAFE_IMAGE_PROTOCOLS = new Set(['http', 'https', 'blob'])
const DATA_IMAGE_PREFIX_RE = /^data:image\/[a-z0-9.+-]+(?:;[a-z0-9=:+-]+)*,/i

function normalizeMarkdownUrl(value: string | null | undefined): string {
  return typeof value === 'string' ? value.trim() : ''
}

function getMarkdownUrlScheme(value: string): string | null {
  let scheme = ''

  for (const char of value) {
    if (char === ':') {
      return scheme ? scheme.toLowerCase() : null
    }

    if (
      char === '/' ||
      char === '?' ||
      char === '#' ||
      char === '&'
    ) {
      return null
    }

    if (
      (char >= 'a' && char <= 'z') ||
      (char >= 'A' && char <= 'Z') ||
      (char >= '0' && char <= '9') ||
      char === '+' ||
      char === '-' ||
      char === '.'
    ) {
      scheme += char
      continue
    }

    return null
  }

  return null
}

function isSafeRelativeMarkdownHref(value: string): boolean {
  return (
    value.startsWith('#') ||
    value.startsWith('?') ||
    value.startsWith('./') ||
    value.startsWith('../') ||
    (value.startsWith('/') && !value.startsWith('//'))
  )
}

function isSafeRelativeMarkdownImageSrc(value: string): boolean {
  return (
    value.startsWith('./') ||
    value.startsWith('../') ||
    (value.startsWith('/') && !value.startsWith('//'))
  )
}

export function sanitizeMarkdownHref(value: string | null | undefined): string {
  const normalized = normalizeMarkdownUrl(value)
  if (!normalized) return ''
  if (isSafeRelativeMarkdownHref(normalized)) return normalized

  const scheme = getMarkdownUrlScheme(normalized)
  return scheme && SAFE_LINK_PROTOCOLS.has(scheme) ? normalized : ''
}

export function resolveMarkdownImageSrc(value: string | null | undefined): string | null {
  const normalized = normalizeMarkdownUrl(value)
  if (!normalized) return null
  if (DATA_IMAGE_PREFIX_RE.test(normalized)) return normalized
  if (isSafeRelativeMarkdownImageSrc(normalized)) {
    return toAbsoluteBackendUrl(normalized)
  }

  const scheme = getMarkdownUrlScheme(normalized)
  if (!scheme || !SAFE_IMAGE_PROTOCOLS.has(scheme)) return null
  if (scheme === 'blob') return normalized
  if (isBlockedMarkdownImageTarget(normalized)) return null
  return normalized
}
