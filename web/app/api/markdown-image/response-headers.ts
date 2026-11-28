import type { IncomingHttpHeaders } from 'node:http'

export function readMarkdownImageHeader(headers: IncomingHttpHeaders, name: string): string | undefined {
  const value = headers[name]
  const header = Array.isArray(value) ? value[0] : value
  return header?.trim()
}

export function buildMarkdownImageResponseHeaders(contentType: string, upstreamHeaders: IncomingHttpHeaders): Headers {
  const headers = new Headers()
  headers.set('Content-Type', contentType)
  headers.set('Cache-Control', 'private, no-store')
  headers.set('Pragma', 'no-cache')
  headers.set('X-Content-Type-Options', 'nosniff')

  const etag = readMarkdownImageHeader(upstreamHeaders, 'etag')
  if (etag) headers.set('ETag', etag)
  const lastModified = readMarkdownImageHeader(upstreamHeaders, 'last-modified')
  if (lastModified) headers.set('Last-Modified', lastModified)

  return headers
}
