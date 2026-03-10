import { NextRequest, NextResponse } from 'next/server'

import { API_V1_BASE_URL } from '@/lib/env'

export const runtime = 'nodejs'

function readEnv(name: string): string {
  return String(process.env[name] || '').trim()
}

function isFalsey(value: string): boolean {
  const v = String(value || '').trim().toLowerCase()
  return v === '0' || v === 'false' || v === 'no' || v === 'off' || v === 'disabled'
}

function isSamlEnabled(): boolean {
  const enabled = readEnv('SAML_ENABLED')
  if (!enabled) return false
  return !isFalsey(enabled)
}

function xmlNoStore(xml: string, init?: { status?: number }) {
  const resp = new NextResponse(xml, { status: init?.status ?? 200 })
  resp.headers.set('Content-Type', 'application/samlmetadata+xml; charset=utf-8')
  resp.headers.set('Cache-Control', 'no-store')
  resp.headers.set('Pragma', 'no-cache')
  return resp
}

export async function GET(req: NextRequest) {
  // Safe default: feature is OFF unless explicitly enabled.
  if (!isSamlEnabled()) {
    return xmlNoStore('Not Found', { status: 404 })
  }

  const providerId = String(req.nextUrl.searchParams.get('provider_id') || '').trim() || undefined
  const url = new URL(`${API_V1_BASE_URL}/auth/saml/metadata`)
  if (providerId) url.searchParams.set('provider_id', providerId)

  const backendRes = await fetch(url, { method: 'GET', cache: 'no-store' }).catch(() => null)
  if (!backendRes) {
    return xmlNoStore('Unable to reach auth backend', { status: 502 })
  }
  if (!backendRes.ok) {
    const errorText = (await backendRes.text().catch(() => null)) || ''
    return xmlNoStore(errorText || `SAML metadata unavailable (${backendRes.status})`, { status: backendRes.status })
  }

  const xml = (await backendRes.text().catch(() => null)) || ''
  if (!xml) {
    return xmlNoStore('Empty metadata response', { status: 502 })
  }
  return xmlNoStore(xml)
}
