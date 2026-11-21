import { toAbsoluteBackendUrl } from '@/lib/env'
import { isBlockedMarkdownImageTarget } from '@/lib/markdown-image-proxy'

const SAFE_LINK_PROTOCOLS = new Set(['http', 'https', 'mailto', 'tel'])
const SAFE_IMAGE_PROTOCOLS = new Set(['http', 'https', 'blob'])
const DATA_IMAGE_PREFIX_RE = /^data:image\/[a-z0-9.+-]+(?:;[a-z0-9=:+-]+)*,/i
const URL_SCHEME_RE = /^([a-z][a-z0-9+.-]*):/i

function normalizeMarkdownUrl(value: string | Blob | null | undefined): string | null {
  if (typeof value !== 'string') return null
  const url = value.trim()
  return url === '' ? null : url
}

function getMarkdownUrlScheme(value: string): string | null {
  const match = URL_SCHEME_RE.exec(value)
  return match === null ? null : match[1].toLowerCase()
}

function isRelativeMarkdownPath(value: string): boolean {
  return value.startsWith('./') || value.startsWith('../') || (value.startsWith('/') && !value.startsWith('//'))
}

export function sanitizeMarkdownHref(value: string | null | undefined): string | null {
  const normalized = normalizeMarkdownUrl(value)
  if (normalized === null) return null
  if (normalized.startsWith('#') || normalized.startsWith('?') || isRelativeMarkdownPath(normalized)) return normalized

  const scheme = getMarkdownUrlScheme(normalized)
  return scheme !== null && SAFE_LINK_PROTOCOLS.has(scheme) ? normalized : null
}

export function resolveMarkdownImageSrc(value: string | Blob | null | undefined): string | null {
  const normalized = normalizeMarkdownUrl(value)
  if (normalized === null) return null
  if (DATA_IMAGE_PREFIX_RE.test(normalized)) return normalized
  if (isRelativeMarkdownPath(normalized)) {
    return toAbsoluteBackendUrl(normalized)
  }

  const scheme = getMarkdownUrlScheme(normalized)
  if (scheme === null || !SAFE_IMAGE_PROTOCOLS.has(scheme)) return null
  if (scheme === 'blob') return normalized
  if (isBlockedMarkdownImageTarget(normalized)) return null
  return normalized
}
