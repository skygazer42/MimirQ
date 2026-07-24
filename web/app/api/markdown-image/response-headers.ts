import type { IncomingHttpHeaders } from 'node:http'

function headerValue(headers: IncomingHttpHeaders, name: string): string {
  const value = headers[name]
  return String(Array.isArray(value) ? value[0] || '' : value || '').trim()
}

export function buildMarkdownImageResponseHeaders(
  contentType: string,
  upstreamHeaders: IncomingHttpHeaders,
): Headers {
  const headers = new Headers()
  headers.set('Content-Type', contentType)
  headers.set('Cache-Control', 'private, no-store')
  headers.set('Pragma', 'no-cache')
  headers.set('X-Content-Type-Options', 'nosniff')

  const etag = headerValue(upstreamHeaders, 'etag')
  if (etag) headers.set('ETag', etag)
  const lastModified = headerValue(upstreamHeaders, 'last-modified')
  if (lastModified) headers.set('Last-Modified', lastModified)

  return headers
}
