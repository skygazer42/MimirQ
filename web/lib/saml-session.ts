import type { AuthResponse } from '@/types'

export const SAML_BRIDGE_COOKIE_NAME = 'mimirq_saml_bridge'
export const SAML_BRIDGE_COOKIE_PATH = '/auth/saml/callback'

export type SamlBridgeState =
  | {
      kind: 'success'
      session: AuthResponse
      returnTo: string
    }
  | {
      kind: 'error'
      error: string
    }

function encodeUtf8(value: string): Uint8Array {
  return new TextEncoder().encode(value)
}

function decodeUtf8(value: Uint8Array): string {
  return new TextDecoder().decode(value)
}

function toBase64Url(bytes: Uint8Array): string {
  if (typeof Buffer !== 'undefined') {
    return Buffer.from(bytes).toString('base64url')
  }

  let out = ''
  for (const byte of bytes) out += String.fromCharCode(byte)
  return btoa(out).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '')
}

function fromBase64Url(value: string): Uint8Array | null {
  const normalized = String(value || '').trim()
  if (!normalized) return null

  try {
    if (typeof Buffer !== 'undefined') {
      return new Uint8Array(Buffer.from(normalized, 'base64url'))
    }

    const padded = normalized.replace(/-/g, '+').replace(/_/g, '/').padEnd(Math.ceil(normalized.length / 4) * 4, '=')
    const binary = atob(padded)
    return Uint8Array.from(binary, (char) => char.charCodeAt(0))
  } catch {
    return null
  }
}

function readCookie(name: string): string | null {
  if (typeof document === 'undefined') return null
  const prefix = `${name}=`
  const parts = document.cookie.split(';')
  for (const rawPart of parts) {
    const part = rawPart.trim()
    if (part.startsWith(prefix)) {
      return decodeURIComponent(part.slice(prefix.length))
    }
  }
  return null
}

export function encodeSamlBridgeState(payload: SamlBridgeState): string {
  return toBase64Url(encodeUtf8(JSON.stringify(payload)))
}

export function clearSamlBridgeState(): void {
  if (typeof document === 'undefined') return
  document.cookie = `${SAML_BRIDGE_COOKIE_NAME}=; Max-Age=0; Path=${SAML_BRIDGE_COOKIE_PATH}; SameSite=Lax`
}

export function consumeSamlBridgeState(): SamlBridgeState | null {
  const raw = readCookie(SAML_BRIDGE_COOKIE_NAME)
  clearSamlBridgeState()
  if (!raw) return null

  const bytes = fromBase64Url(raw)
  if (!bytes) return null

  try {
    const parsed = JSON.parse(decodeUtf8(bytes)) as Partial<SamlBridgeState> | null
    if (!parsed || typeof parsed !== 'object') return null

    if (parsed.kind === 'error' && typeof parsed.error === 'string') {
      return { kind: 'error', error: parsed.error }
    }

    if (
      parsed.kind === 'success' &&
      parsed.session &&
      typeof parsed.returnTo === 'string' &&
      typeof (parsed.session as AuthResponse).token?.access_token === 'string'
    ) {
      return {
        kind: 'success',
        session: parsed.session as AuthResponse,
        returnTo: parsed.returnTo,
      }
    }
  } catch {
    return null
  }

  return null
}
