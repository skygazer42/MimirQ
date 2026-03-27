import { NextRequest, NextResponse } from 'next/server'

import { isBlockedMarkdownImageTarget, parseMarkdownImageUrl } from '@/lib/markdown-image-proxy'

export const runtime = 'nodejs'

const MAX_IMAGE_BYTES = 10 * 1024 * 1024

function jsonNoStore(data: unknown, init?: { status?: number }) {
  const response = NextResponse.json(data, init)
  response.headers.set('Cache-Control', 'no-store')
  response.headers.set('Pragma', 'no-cache')
  return response
}

export async function GET(req: NextRequest) {
  const rawSrc = String(req.nextUrl.searchParams.get('src') || '').trim()
  const target = parseMarkdownImageUrl(rawSrc)
  if (!target || isBlockedMarkdownImageTarget(target.toString())) {
    return jsonNoStore({ error: 'invalid_image_src' }, { status: 400 })
  }

  let upstream: Response
  try {
    upstream = await fetch(target.toString(), {
      headers: {
        Accept: 'image/*',
      },
      redirect: 'manual',
    })
  } catch {
    return jsonNoStore({ error: 'image_fetch_failed' }, { status: 502 })
  }

  if (upstream.status >= 300 && upstream.status < 400) {
    return jsonNoStore({ error: 'image_redirect_blocked' }, { status: 400 })
  }
  if (!upstream.ok) {
    return jsonNoStore({ error: 'image_fetch_failed' }, { status: 502 })
  }

  const contentType = String(upstream.headers.get('content-type') || '').trim().toLowerCase()
  if (!contentType.startsWith('image/')) {
    return jsonNoStore({ error: 'image_content_type_invalid' }, { status: 415 })
  }

  const contentLengthRaw = upstream.headers.get('content-length')
  const contentLength = contentLengthRaw ? Number(contentLengthRaw) : Number.NaN
  if (Number.isFinite(contentLength) && contentLength > MAX_IMAGE_BYTES) {
    return jsonNoStore({ error: 'image_too_large' }, { status: 413 })
  }
  if (!upstream.body) {
    return jsonNoStore({ error: 'image_fetch_failed' }, { status: 502 })
  }

  const headers = new Headers()
  headers.set('Content-Type', contentType)
  headers.set('Cache-Control', 'public, max-age=300, stale-while-revalidate=86400')
  headers.set('X-Content-Type-Options', 'nosniff')

  const etag = upstream.headers.get('etag')
  if (etag) headers.set('ETag', etag)
  const lastModified = upstream.headers.get('last-modified')
  if (lastModified) headers.set('Last-Modified', lastModified)

  return new NextResponse(upstream.body, {
    status: 200,
    headers,
  })
}
