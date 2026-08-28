import { NextRequest, NextResponse } from 'next/server'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'
export const maxDuration = 600

const DEFAULT_BACKEND_BASE_URL = 'http://127.0.0.1:8000'
const DEFAULT_LONG_TIMEOUT_MS = 10 * 60_000
const HOP_BY_HOP_HEADERS = [
  'connection',
  'content-length',
  'keep-alive',
  'proxy-authenticate',
  'proxy-authorization',
  'te',
  'trailer',
  'transfer-encoding',
  'upgrade',
] as const

type RouteContext = {
  params: Promise<{ documentId: string }>
}

function trimTrailingSlashes(value: string): string {
  return String(value || '').trim().replace(/\/+$/, '')
}

function isHttpUrl(value: string): boolean {
  try {
    const url = new URL(value)
    return url.protocol === 'http:' || url.protocol === 'https:'
  } catch {
    return false
  }
}

function resolveParsingBackendBase(env: NodeJS.ProcessEnv = process.env): string {
  const candidates = [env.API_INTERNAL_URL, env.NEXT_PUBLIC_API_URL, DEFAULT_BACKEND_BASE_URL]
  for (const candidate of candidates) {
    const normalized = trimTrailingSlashes(candidate || '')
    if (isHttpUrl(normalized)) return normalized
  }
  return DEFAULT_BACKEND_BASE_URL
}

function resolveParsingProxyTimeoutMs(env: NodeJS.ProcessEnv = process.env): number {
  const parsed = Number(String(env.NEXT_PUBLIC_API_LONG_TIMEOUT_MS || '').trim())
  return Number.isFinite(parsed) && parsed > 0 ? parsed : DEFAULT_LONG_TIMEOUT_MS
}

function requestHeaders(req: NextRequest): Headers {
  const headers = new Headers(req.headers)
  headers.delete('host')
  for (const header of HOP_BY_HOP_HEADERS) headers.delete(header)
  return headers
}

function responseHeaders(upstream: Response): Headers {
  const headers = new Headers(upstream.headers)
  for (const header of HOP_BY_HOP_HEADERS) headers.delete(header)
  headers.delete('content-encoding')
  return headers
}

function proxyError(error: unknown): NextResponse {
  const name = error instanceof Error ? error.name : ''
  const timedOut = name === 'TimeoutError' || name === 'AbortError'
  return NextResponse.json(
    {
      detail: timedOut
        ? 'Parsing request timed out before the backend responded'
        : 'Parsing backend is unavailable',
    },
    {
      status: timedOut ? 504 : 502,
      headers: { 'Cache-Control': 'no-store' },
    },
  )
}

export async function POST(req: NextRequest, { params }: RouteContext) {
  const { documentId } = await params
  const incomingUrl = new URL(req.url)
  const target = new URL(
    `/api/v1/parsing/documents/${encodeURIComponent(documentId)}/parse`,
    `${resolveParsingBackendBase()}/`,
  )
  target.search = incomingUrl.search

  const requestBody = await req.arrayBuffer()
  let upstream: Response
  try {
    upstream = await fetch(target, {
      method: 'POST',
      headers: requestHeaders(req),
      body: requestBody.byteLength ? requestBody : undefined,
      cache: 'no-store',
      redirect: 'manual',
      signal: AbortSignal.timeout(resolveParsingProxyTimeoutMs()),
    })
  } catch (error) {
    return proxyError(error)
  }

  const responseBody = await upstream.arrayBuffer()
  return new NextResponse(responseBody, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: responseHeaders(upstream),
  })
}
