import { lookup } from 'node:dns/promises'
import type { LookupAddress } from 'node:dns'
import http, { type IncomingHttpHeaders } from 'node:http'
import https from 'node:https'

import { NextRequest, NextResponse } from 'next/server'

import {
  isAllowedMarkdownImageContentType,
  isBlockedMarkdownImageTarget,
  parseMarkdownImageUrl,
  readMarkdownImageBody,
  selectMarkdownImageAddress,
} from '@/lib/markdown-image-proxy'
import { mintMarkdownImageProxyToken, resolveMarkdownImageProxyToken } from '@/lib/markdown-image-proxy-token'

export const runtime = 'nodejs'

const MAX_IMAGE_BYTES = 10 * 1024 * 1024
const IMAGE_FETCH_TIMEOUT_MS = 10_000

type PinnedImageResponse = {
  status: number
  headers: IncomingHttpHeaders
  body: Uint8Array<ArrayBuffer>
}

class ImageFetchError extends Error {
  constructor(readonly code: 'image_fetch_failed' | 'image_too_large' | 'invalid_image_src') {
    super(code)
  }
}

function headerValue(headers: IncomingHttpHeaders, name: string): string {
  const value = headers[name]
  return String(Array.isArray(value) ? value[0] || '' : value || '').trim()
}

async function fetchPinnedImage(target: URL): Promise<PinnedImageResponse> {
  const started = Date.now()
  let dnsTimeout: ReturnType<typeof setTimeout> | undefined
  const timeout = new Promise<never>((_, reject) => {
    dnsTimeout = setTimeout(
      () => reject(new ImageFetchError('image_fetch_failed')),
      IMAGE_FETCH_TIMEOUT_MS,
    )
  })
  let addresses: LookupAddress[]
  try {
    addresses = await Promise.race([lookup(target.hostname, { all: true, verbatim: true }), timeout])
  } finally {
    clearTimeout(dnsTimeout)
  }
  const pinned = selectMarkdownImageAddress(addresses)
  if (!pinned) throw new ImageFetchError('invalid_image_src')

  const remainingMs = Math.max(1, IMAGE_FETCH_TIMEOUT_MS - (Date.now() - started))
  const transport = target.protocol === 'https:' ? https : http
  return new Promise((resolve, reject) => {
    const request = transport.get(
      target,
      {
        headers: { Accept: 'image/*' },
        family: pinned.family,
        lookup: (_hostname, _options, callback) => callback(null, pinned.address, pinned.family),
        signal: AbortSignal.timeout(remainingMs),
      },
      async (response) => {
        const status = response.statusCode || 502
        const contentLength = Number(headerValue(response.headers, 'content-length'))
        if (Number.isFinite(contentLength) && contentLength > MAX_IMAGE_BYTES) {
          response.destroy()
          reject(new ImageFetchError('image_too_large'))
          return
        }

        try {
          const body = await readMarkdownImageBody(response, MAX_IMAGE_BYTES)
          resolve({ status, headers: response.headers, body })
        } catch (error) {
          response.destroy()
          reject(error instanceof RangeError ? new ImageFetchError('image_too_large') : error)
        }
      },
    )
    request.on('error', reject)
  })
}

function jsonNoStore(data: unknown, init?: { status?: number }) {
  const response = NextResponse.json(data, init)
  response.headers.set('Cache-Control', 'no-store')
  response.headers.set('Pragma', 'no-cache')
  return response
}

function resolveImageTarget(req: NextRequest): { target: URL | null; error: string | null } {
  const rawToken = String(req.nextUrl.searchParams.get('token') || '').trim()
  if (rawToken) {
    const resolvedSrc = resolveMarkdownImageProxyToken(rawToken)
    const target = parseMarkdownImageUrl(resolvedSrc)
    if (!target || isBlockedMarkdownImageTarget(target.toString())) {
      return { target: null, error: 'invalid_image_token' }
    }
    return { target, error: null }
  }

  const rawSrc = String(req.nextUrl.searchParams.get('src') || '').trim()
  const target = parseMarkdownImageUrl(rawSrc)
  if (!target || isBlockedMarkdownImageTarget(target.toString())) {
    return { target: null, error: 'invalid_image_src' }
  }
  return { target, error: null }
}

export async function GET(req: NextRequest) {
  const { target, error } = resolveImageTarget(req)
  if (!target || error) {
    return jsonNoStore({ error }, { status: 400 })
  }

  let upstream: PinnedImageResponse
  try {
    upstream = await fetchPinnedImage(target)
  } catch (fetchError) {
    const code = fetchError instanceof ImageFetchError ? fetchError.code : 'image_fetch_failed'
    const status = code === 'image_too_large' ? 413 : code === 'invalid_image_src' ? 400 : 502
    return jsonNoStore({ error: code }, { status })
  }

  if (upstream.status >= 300 && upstream.status < 400) {
    return jsonNoStore({ error: 'image_redirect_blocked' }, { status: 400 })
  }
  if (upstream.status < 200 || upstream.status >= 300) {
    return jsonNoStore({ error: 'image_fetch_failed' }, { status: 502 })
  }

  const contentType = headerValue(upstream.headers, 'content-type').toLowerCase()
  if (!isAllowedMarkdownImageContentType(contentType)) {
    return jsonNoStore({ error: 'image_content_type_invalid' }, { status: 415 })
  }

  const headers = new Headers()
  headers.set('Content-Type', contentType)
  headers.set('Cache-Control', 'public, max-age=300, stale-while-revalidate=86400')
  headers.set('X-Content-Type-Options', 'nosniff')

  const etag = headerValue(upstream.headers, 'etag')
  if (etag) headers.set('ETag', etag)
  const lastModified = headerValue(upstream.headers, 'last-modified')
  if (lastModified) headers.set('Last-Modified', lastModified)

  return new NextResponse(upstream.body, {
    status: 200,
    headers,
  })
}

export async function POST(req: NextRequest) {
  let body: unknown
  try {
    body = await req.json()
  } catch {
    return jsonNoStore({ error: 'invalid_image_src' }, { status: 400 })
  }

  const rawSrc =
    body && typeof body === 'object' && 'src' in body && typeof body.src === 'string'
      ? body.src.trim()
      : ''
  const target = parseMarkdownImageUrl(rawSrc)
  if (!target || isBlockedMarkdownImageTarget(target.toString())) {
    return jsonNoStore({ error: 'invalid_image_src' }, { status: 400 })
  }

  const token = mintMarkdownImageProxyToken(target.toString())
  if (!token) {
    return jsonNoStore({ error: 'proxy_secret_unavailable' }, { status: 503 })
  }

  return jsonNoStore({
    src: `/api/markdown-image?token=${encodeURIComponent(token)}`,
  })
}
