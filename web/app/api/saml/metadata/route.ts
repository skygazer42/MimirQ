import { NextRequest, NextResponse } from 'next/server'

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

function escapeXml(value: string): string {
  return String(value || '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&apos;')
}

function resolveOrigin(req: NextRequest): string {
  const xfProto = String(req.headers.get('x-forwarded-proto') || '').trim()
  const xfHost = String(req.headers.get('x-forwarded-host') || '').trim()
  if (xfProto && xfHost) return `${xfProto}://${xfHost}`
  return req.nextUrl.origin
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

  const origin = resolveOrigin(req)
  const entityId = `${origin}/api/saml/metadata`
  const acsUrl = `${origin}/api/saml/acs`

  // Minimal, unsigned metadata skeleton.
  // Enterprises typically require signed requests and a configured cert/keypair;
  // those are intentionally omitted in this skeleton.
  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<EntityDescriptor xmlns="urn:oasis:names:tc:SAML:2.0:metadata" entityID="${escapeXml(entityId)}">
  <SPSSODescriptor protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
    <AssertionConsumerService
      Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
      Location="${escapeXml(acsUrl)}"
      index="1"
      isDefault="true"
    />
  </SPSSODescriptor>
</EntityDescriptor>
`

  return xmlNoStore(xml)
}

