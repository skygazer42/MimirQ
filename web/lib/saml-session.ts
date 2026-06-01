import type { AuthResponse } from '@/types'
import { base64UrlDecodeToBytes, base64UrlEncode, decodeUtf8, encodeUtf8 } from '@/lib/encoding'

export const SAML_BRIDGE_COOKIE_NAME = 'mimirq_saml_bridge'
export const SAML_BRIDGE_COOKIE_PATH = '/auth/saml/callback'
const SAML_BRIDGE_CLEAR_COOKIE_ATTRIBUTES = [
  'Max-Age=0',
  `Path=${SAML_BRIDGE_COOKIE_PATH}`,
  'SameSite=Lax',
  'Secure',
] as const

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

function fromBase64Url(value: string): Uint8Array | null {
  const normalized = String(value || '').trim()
  if (!normalized) return null

  try {
    return base64UrlDecodeToBytes(normalized)
  } catch {
    return null
  }
}

function readBridgeCookie(): string | null {
  if (typeof document === 'undefined') return null
  const prefix = `${SAML_BRIDGE_COOKIE_NAME}=`
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
  return base64UrlEncode(encodeUtf8(JSON.stringify(payload)))
}

export function clearSamlBridgeState(): void {
  if (typeof document === 'undefined') return
  document.cookie = `${SAML_BRIDGE_COOKIE_NAME}=; ${SAML_BRIDGE_CLEAR_COOKIE_ATTRIBUTES.join('; ')}`
}

export function consumeSamlBridgeState(): SamlBridgeState | null {
  const raw = readBridgeCookie()
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
      typeof (parsed.session).token?.access_token === 'string'
    ) {
      return {
        kind: 'success',
        session: parsed.session,
        returnTo: parsed.returnTo,
      }
    }
  } catch {
    return null
  }

  return null
}
