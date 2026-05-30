import { API_BASE_URL } from '@/lib/env'

const BLOCKED_HOSTNAME_SUFFIXES = ['.internal', '.local', '.localhost']

let BACKEND_ORIGIN = ''
try {
  BACKEND_ORIGIN = new URL(API_BASE_URL).origin
} catch {
  BACKEND_ORIGIN = ''
}

function normalizeHost(rawHostname: string): string {
  const hostname = String(rawHostname || '').trim().toLowerCase()
  const withoutBrackets =
    hostname.startsWith('[') && hostname.endsWith(']') ? hostname.slice(1, -1) : hostname
  return withoutBrackets.split('%')[0] || withoutBrackets
}

function isPrivateIpv4(hostname: string): boolean {
  const parts = hostname.split('.')
  if (parts.length !== 4) return false

  const octets = parts.map((part) => Number(part))
  if (octets.some((octet) => !Number.isInteger(octet) || octet < 0 || octet > 255)) return false

  const [first, second] = octets
  return (
    first === 0 ||
    first === 10 ||
    first === 127 ||
    (first === 169 && second === 254) ||
    (first === 172 && second >= 16 && second <= 31) ||
    (first === 192 && second === 168) ||
    (first === 100 && second >= 64 && second <= 127)
  )
}

function isPrivateIpv6(hostname: string): boolean {
  const normalized = hostname.toLowerCase()
  if (!normalized.includes(':')) return false
  if (normalized === '::' || normalized === '::1') return true
  if (normalized.startsWith('fc') || normalized.startsWith('fd')) return true

  const compact = normalized.replaceAll(':', '')
  return compact.startsWith('fe8') || compact.startsWith('fe9') || compact.startsWith('fea') || compact.startsWith('feb')
}

export function parseMarkdownImageUrl(rawUrl: string | null | undefined): URL | null {
  const raw = typeof rawUrl === 'string' ? rawUrl.trim() : ''
  if (!raw) return null

  try {
    const parsed = new URL(raw)
    const protocol = parsed.protocol.toLowerCase()
    return protocol === 'http:' || protocol === 'https:' ? parsed : null
  } catch {
    return null
  }
}

export function isBlockedMarkdownImageHost(hostname: string): boolean {
  const normalized = normalizeHost(hostname)
  if (!normalized) return true
  if (normalized === 'localhost') return true
  if (BLOCKED_HOSTNAME_SUFFIXES.some((suffix) => normalized.endsWith(suffix))) return true
  return isPrivateIpv4(normalized) || isPrivateIpv6(normalized)
}

export function isBlockedMarkdownImageTarget(rawUrl: string | null | undefined): boolean {
  const parsed = parseMarkdownImageUrl(rawUrl)
  return parsed ? isBlockedMarkdownImageHost(parsed.hostname) : false
}

export function isSameBackendMarkdownImageUrl(rawUrl: string | null | undefined): boolean {
  const parsed = parseMarkdownImageUrl(rawUrl)
  return Boolean(parsed && BACKEND_ORIGIN && parsed.origin === BACKEND_ORIGIN)
}

export function buildMarkdownImageProxyUrl(rawUrl: string): string {
  return `/api/markdown-image?src=${encodeURIComponent(rawUrl)}`
}
