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

function jsonNoStore(data: any, init?: { status?: number }) {
  const resp = NextResponse.json(data, init)
  resp.headers.set('Cache-Control', 'no-store')
  resp.headers.set('Pragma', 'no-cache')
  return resp
}

export async function POST(_req: NextRequest) {
  // Safe default: feature is OFF unless explicitly enabled.
  if (!isSamlEnabled()) {
    return jsonNoStore({ error: 'saml_disabled' }, { status: 404 })
  }

  // Skeleton placeholder.
  // A real implementation must:
  // - validate SAMLResponse signature + audience + NotBefore/NotOnOrAfter
  // - map NameID / email to a MimirQ account (and optional group sync)
  // - mint a backend JWT session (or exchange via a trusted backend endpoint)
  return jsonNoStore({ error: 'saml_not_implemented' }, { status: 501 })
}

