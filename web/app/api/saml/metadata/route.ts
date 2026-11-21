import { type NextRequest, NextResponse } from 'next/server'

import { API_V1_BASE_URL } from '@/lib/env'
import { isSamlEnabled } from '@/lib/server-auth-route'

export const runtime = 'nodejs'

function xmlNoStore(xml: string, status = 200) {
  const response = new NextResponse(xml, { status })
  response.headers.set('Content-Type', 'application/samlmetadata+xml; charset=utf-8')
  response.headers.set('Cache-Control', 'no-store')
  response.headers.set('Pragma', 'no-cache')
  return response
}

export async function GET(req: NextRequest) {
  // Safe default: feature is OFF unless explicitly enabled.
  if (!isSamlEnabled()) {
    return xmlNoStore('Not Found', 404)
  }

  const providerId = req.nextUrl.searchParams.get('provider_id')?.trim()
  const url = new URL(`${API_V1_BASE_URL}/auth/saml/metadata`)
  if (providerId !== undefined && providerId !== '') url.searchParams.set('provider_id', providerId)

  const backendResponse = await fetch(url, { method: 'GET', cache: 'no-store' }).catch(() => null)
  if (backendResponse === null) {
    return xmlNoStore('Unable to reach auth backend', 502)
  }
  const xml = await backendResponse.text().catch(() => null)
  if (!backendResponse.ok) {
    const message = xml === null || xml === '' ? `SAML metadata unavailable (${backendResponse.status})` : xml
    return xmlNoStore(message, backendResponse.status)
  }
  if (xml === null) {
    return xmlNoStore('Unable to read metadata response', 502)
  }
  if (xml === '') {
    return xmlNoStore('Empty metadata response', 502)
  }
  return xmlNoStore(xml)
}
